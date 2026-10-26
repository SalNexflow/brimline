"""The CP-SAT scheduler (Google OR-Tools). Same rules as the baselines, optimised as a whole.

Variables per job: a "scheduled" flag; a start time per task; one optional machine interval per
eligible machine (exactly one is used if the job is scheduled).
Hard constraints: one task at a time per machine; tasks in order; machine tasks start inside a
shift and after the material arrives; manual tasks fit inside one shift; at most `staff` manual
tasks at once; fixed tasks stay put; consecutive jobs of different material on one machine are
`changeover_minutes` apart; everything ends within the horizon.
Objective (weights from config/scheduler.toml): late jobs and minutes late (rush jobs count
more), changeovers, the finish time, and a large penalty for each job left unscheduled.

Two ways to handle changeovers:
  simple   pairwise: any two jobs of different material on the same machine are separated by
           the changeover time. The objective counts *distinct materials per machine* as a proxy
           for the number of changeovers (exact count needs the job sequence).
  circuit  AddCircuit per machine chooses the job sequence explicitly, so the changeover time
           applies between consecutive jobs and the objective counts changeovers exactly.
Repeatable: fixed seed, one worker, deterministic time limit. The search is hinted with the EDD
schedule, so it starts from a good feasible answer.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

from ortools.sat.python import cp_model

from brimline_engine.scheduling.calendar import machine_start_ranges, manual_start_ranges
from brimline_engine.scheduling.config import SchedulerConfig, Weights
from brimline_engine.scheduling.durations import eligible_machines, task_durations
from brimline_engine.scheduling.model import (
    MANUAL,
    TASK_ORDER,
    Instance,
    Job,
    JobPlan,
    Schedule,
    Slot,
    TaskKind,
)

Variant = Literal["simple", "circuit"]


@dataclass
class _JobVars:
    job: Job
    scheduled: cp_model.IntVar
    starts: dict[TaskKind, cp_model.IntVar]
    durations: dict[TaskKind, int]
    on: dict[str, cp_model.IntVar] = field(default_factory=dict)  # machine code -> literal

    def end(self, kind: TaskKind) -> cp_model.LinearExprT:
        return self.starts[kind] + self.durations[kind]


def _domain(ranges: list[tuple[int, int]]) -> cp_model.Domain:
    return cp_model.Domain.from_intervals([[lo, hi] for lo, hi in ranges])


def _job_vars(
    model: cp_model.CpModel, instance: Instance, job: Job, cfg: SchedulerConfig
) -> _JobVars | None:
    """Variables for one job, or None if no placement can ever satisfy the rules."""
    fixed = next((f for f in instance.fixed if f.job_id == job.id), None)
    durations = task_durations(job, cfg.durations)
    if fixed is not None:
        durations.pop("prep", None)  # a running or finished task's prep is done
    machines = [m.code for m in eligible_machines(job, instance.machines)]
    if fixed is not None:
        machines = [fixed.machine]
    if not machines:
        return None
    starts: dict[TaskKind, cp_model.IntVar] = {}
    for kind in TASK_ORDER:
        if kind not in durations:
            continue
        latest = cp_model.Domain(0, instance.horizon - durations[kind])
        if kind in MANUAL:
            domain = _domain(manual_start_ranges(durations[kind], instance.shifts))
        elif fixed is not None:
            domain = cp_model.Domain(fixed.start, fixed.start)
        else:
            domain = _domain(machine_start_ranges(instance.shifts)).intersection_with(
                cp_model.Domain(job.release, instance.horizon)
            )
        domain = domain.intersection_with(latest)
        if domain.is_empty():
            return None
        starts[kind] = model.new_int_var_from_domain(domain, f"{kind}_{job.id}")
    scheduled = model.new_bool_var(f"scheduled_{job.id}")
    if fixed is not None:
        model.add(scheduled == 1)
    jv = _JobVars(job, scheduled, starts, durations)
    for code in machines:
        jv.on[code] = model.new_bool_var(f"on_{job.id}_{code}")
    model.add(sum(jv.on.values()) == scheduled)
    kinds = [k for k in TASK_ORDER if k in durations]
    for before, after in pairwise(kinds):
        model.add(starts[after] >= jv.end(before)).only_enforce_if(scheduled)
    return jv


def solve(
    instance: Instance,
    cfg: SchedulerConfig,
    *,
    variant: Variant = "simple",
    hint: Schedule | None = None,
    deterministic_time: float | None = None,
    weights: Weights | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Schedule:
    w = weights or cfg.weights
    model = cp_model.CpModel()
    horizon = instance.horizon
    co_time = cfg.durations.changeover_minutes
    all_vars: list[_JobVars] = []
    impossible: list[str] = []
    for job in instance.jobs:
        jv = _job_vars(model, instance, job, cfg)
        if jv is None:
            impossible.append(job.id)
        else:
            all_vars.append(jv)

    # Machines: one task at a time; changeovers between different materials.
    machine_intervals: dict[str, list[tuple[_JobVars, cp_model.IntervalVar]]] = {}
    manual_intervals: list[cp_model.IntervalVar] = []
    for jv in all_vars:
        for code, on in jv.on.items():
            interval = model.new_optional_fixed_size_interval_var(
                jv.starts["machine"], jv.durations["machine"], on, f"m_{jv.job.id}_{code}"
            )
            machine_intervals.setdefault(code, []).append((jv, interval))
        for kind in MANUAL:
            if kind in jv.starts:
                manual_intervals.append(
                    model.new_optional_fixed_size_interval_var(
                        jv.starts[kind], jv.durations[kind], jv.scheduled, f"{kind}i_{jv.job.id}"
                    )
                )
    for entries in machine_intervals.values():
        model.add_no_overlap([interval for _, interval in entries])
    if manual_intervals:
        model.add_cumulative(manual_intervals, [1] * len(manual_intervals), instance.staff)

    changeover_terms: list[cp_model.LinearExprT] = []
    for code, entries in machine_intervals.items():
        if variant == "simple":
            changeover_terms.append(_simple_changeovers(model, code, entries, co_time))
        else:
            changeover_terms.append(_circuit_changeovers(model, code, entries, co_time))

    # Lateness and finish time.
    finish = model.new_int_var(0, horizon, "finish_time")
    objective: list[cp_model.LinearExprT] = []
    for jv in all_vars:
        last = [k for k in TASK_ORDER if k in jv.starts][-1]
        completion = jv.end(last)
        multiplier = w.rush_multiplier if jv.job.rush else 1
        tardiness = model.new_int_var(0, horizon, f"tardiness_{jv.job.id}")
        late = model.new_bool_var(f"late_{jv.job.id}")
        model.add(tardiness >= completion - jv.job.due).only_enforce_if(jv.scheduled)
        model.add(tardiness <= horizon * late)
        model.add(finish >= completion).only_enforce_if(jv.scheduled)
        objective += [
            w.late_job * multiplier * late,
            w.tardiness_per_minute * multiplier * tardiness,
            w.unscheduled_job * (1 - jv.scheduled),
        ]
    objective += [w.changeover * term for term in changeover_terms]
    objective.append(w.finish_time_per_minute * finish)
    model.minimize(sum(objective))

    if hint is not None:
        _add_hint(model, all_vars, hint)

    solver = cp_model.CpSolver()
    solver.parameters.random_seed = cfg.solver.random_seed
    solver.parameters.num_workers = cfg.solver.workers
    solver.parameters.max_deterministic_time = (
        deterministic_time or cfg.solver.deterministic_time_seconds
    )
    started = clock()
    status = solver.solve(model)
    wall = clock() - started

    info: dict[str, object] = {
        "variant": variant,
        "status": solver.status_name(status),
        "solver_objective": solver.objective_value
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        else None,
        "solver_bound": solver.best_objective_bound,
        "deterministic_time": round(solver.deterministic_time, 2),
        "wall_seconds": round(wall, 2),
        "hinted": hint is not None,
    }
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # No answer within the limit: report every job as unscheduled rather than invent one.
        return Schedule(f"cpsat-{variant}", (), tuple(j.id for j in instance.jobs), info)

    plans: list[JobPlan] = []
    unscheduled = list(impossible)
    for jv in all_vars:
        if not solver.boolean_value(jv.scheduled):
            unscheduled.append(jv.job.id)
            continue
        machine = next(code for code, on in jv.on.items() if solver.boolean_value(on))
        slots = tuple(
            Slot(kind, solver.value(start), solver.value(start) + jv.durations[kind])
            for kind, start in jv.starts.items()
        )
        plans.append(JobPlan(jv.job.id, machine, slots))
    return Schedule(f"cpsat-{variant}", tuple(plans), tuple(unscheduled), info)


def _simple_changeovers(
    model: cp_model.CpModel,
    code: str,
    entries: list[tuple[_JobVars, cp_model.IntervalVar]],
    co_time: int,
) -> cp_model.LinearExprT:
    """Pairwise separation for different materials; returns (distinct materials used - 1)."""
    for i, (a, _) in enumerate(entries):
        for b, _ in entries[i + 1 :]:
            if a.job.material == b.job.material or co_time == 0:
                continue
            a_first = model.new_bool_var(f"order_{code}_{a.job.id}_{b.job.id}")
            both = [a.on[code], b.on[code]]
            model.add(b.starts["machine"] >= a.end("machine") + co_time).only_enforce_if(
                [*both, a_first]
            )
            model.add(a.starts["machine"] >= b.end("machine") + co_time).only_enforce_if(
                [*both, ~a_first]
            )
    used: dict[str, cp_model.IntVar] = {}
    for jv, _ in entries:
        material = jv.job.material
        if material not in used:
            used[material] = model.new_bool_var(f"uses_{code}_{material}")
        model.add_implication(jv.on[code], used[material])
    machine_used = model.new_bool_var(f"used_{code}")
    model.add_max_equality(machine_used, list(used.values()))
    return sum(used.values()) - machine_used


def _circuit_changeovers(
    model: cp_model.CpModel,
    code: str,
    entries: list[tuple[_JobVars, cp_model.IntervalVar]],
    co_time: int,
) -> cp_model.LinearExprT:
    """The job sequence on this machine as a circuit; returns the exact number of changeovers."""
    arcs: list[tuple[int, int, cp_model.LiteralT]] = []
    empty = model.new_bool_var(f"empty_{code}")
    model.add_bool_or([jv.on[code] for jv, _ in entries] + [empty])
    for jv, _ in entries:
        model.add_implication(empty, ~jv.on[code])
    arcs.append((0, 0, empty))
    changes: list[cp_model.IntVar] = []
    for i, (a, _) in enumerate(entries, start=1):
        arcs.append((0, i, model.new_bool_var(f"first_{code}_{a.job.id}")))
        arcs.append((i, 0, model.new_bool_var(f"last_{code}_{a.job.id}")))
        arcs.append((i, i, ~a.on[code]))  # skipped when the job is on another machine
        for k, (b, _) in enumerate(entries, start=1):
            if i == k:
                continue
            follows = model.new_bool_var(f"next_{code}_{a.job.id}_{b.job.id}")
            arcs.append((i, k, follows))
            gap = co_time if a.job.material != b.job.material else 0
            model.add(b.starts["machine"] >= a.end("machine") + gap).only_enforce_if(follows)
            if a.job.material != b.job.material:
                changes.append(follows)
    model.add_circuit(arcs)
    return sum(changes)


def _add_hint(model: cp_model.CpModel, all_vars: list[_JobVars], hint: Schedule) -> None:
    plans = {p.job_id: p for p in hint.plans}
    for jv in all_vars:
        plan = plans.get(jv.job.id)
        model.add_hint(jv.scheduled, plan is not None)
        for code, on in jv.on.items():
            model.add_hint(on, plan is not None and plan.machine == code)
        if plan is None:
            continue
        for kind, start in jv.starts.items():
            slot = plan.slot(kind)
            if slot is not None:
                model.add_hint(start, slot.start)
