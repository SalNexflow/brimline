"""The CP-SAT scheduler (Google OR-Tools). Same rules as the baselines, optimised as a whole.

Variables per job: a "scheduled" flag; a start time per task; one optional machine interval per
eligible machine (exactly one is used if the job is scheduled).
Hard constraints: one task at a time per machine; tasks in order; machine tasks start inside a
shift and after the material arrives; manual tasks fit inside one shift; at most `staff` manual
tasks at once; fixed tasks stay put and always block their machine; consecutive jobs of
different material on one machine are `changeover_minutes` apart (not required between two fixed
tasks); everything ends within the horizon.
Objective (weights from config/scheduler.toml): late jobs and minutes late (rush jobs count
more), changeovers, the finish time, and a large penalty for each job left unscheduled.

Changeovers ("simple" model): any two jobs of different material on the same machine are
separated by the changeover time (equivalent to the rule for consecutive jobs). The objective
counts *distinct materials per machine* as a stand-in for the number of changeovers, so its
"OPTIMAL" is optimal for that stand-in, not for the real changeover count; info["objective"]
says so. An exact AddCircuit model was built and measured and lost at 80 jobs, so it was removed
(docs/DECISIONS.md D49).
Repeatable: fixed seed, one worker, deterministic time limit. The search is hinted with a full
solution built from the EDD schedule (every variable gets a value). If CP-SAT still finds no
solution within the limit, the EDD schedule is returned, labelled as a fallback in info.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise

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
from brimline_engine.scheduling.validation import check_instance

METHOD = "cpsat-simple"  # the name in schedules and in eval/results/BENCH.md


@dataclass
class _JobVars:
    job: Job
    scheduled: cp_model.IntVar
    starts: dict[TaskKind, cp_model.IntVar]
    durations: dict[TaskKind, int]
    fixed_start: int | None  # the machine task's start if it is fixed (running or done)
    on: dict[str, cp_model.IntVar] = field(default_factory=dict)  # machine code -> literal
    tardiness: cp_model.IntVar | None = None
    late: cp_model.IntVar | None = None

    def end(self, kind: TaskKind) -> cp_model.LinearExprT:
        return self.starts[kind] + self.durations[kind]

    @property
    def fixed(self) -> bool:
        return self.fixed_start is not None


@dataclass
class _Extras:
    """Auxiliary variables, kept so the hint can give every one of them a value."""

    finish: cp_model.IntVar
    order: list[tuple[str, str, str, cp_model.IntVar]] = field(
        default_factory=list
    )  # a, b, machine, "a first"
    used: dict[tuple[str, str], cp_model.IntVar] = field(
        default_factory=dict
    )  # (machine, material)
    machine_used: dict[str, cp_model.IntVar] = field(default_factory=dict)


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
    machines = (
        [fixed.machine]
        if fixed is not None
        else [m.code for m in eligible_machines(job, instance.machines)]
    )
    if not machines:
        return None
    starts: dict[TaskKind, cp_model.IntVar] = {}
    blocked_only = False  # a fixed task whose later tasks cannot fit: it still blocks its machine
    for kind in TASK_ORDER:
        if kind not in durations:
            continue
        if kind == "machine" and fixed is not None:
            domain = cp_model.Domain(fixed.start, fixed.start)
        else:
            latest = cp_model.Domain(0, instance.horizon - durations[kind])
            if kind in MANUAL:
                domain = _domain(manual_start_ranges(durations[kind], instance.shifts))
            else:
                domain = _domain(machine_start_ranges(instance.shifts)).intersection_with(
                    cp_model.Domain(job.release, instance.horizon)
                )
            domain = domain.intersection_with(latest)
        if domain.is_empty():
            if fixed is None:
                return None
            blocked_only = True
            break
        starts[kind] = model.new_int_var_from_domain(domain, f"{kind}_{job.id}")
    if blocked_only:
        starts = {"machine": starts["machine"]}
        durations = {"machine": durations["machine"]}
    scheduled = model.new_bool_var(f"scheduled_{job.id}")
    jv = _JobVars(job, scheduled, starts, durations, fixed.start if fixed is not None else None)
    for code in machines:
        jv.on[code] = model.new_bool_var(f"on_{job.id}_{code}")
    if fixed is not None:
        model.add(jv.on[fixed.machine] == 1)  # always blocks the machine, scheduled or not
        if blocked_only:
            model.add(scheduled == 0)
    else:
        model.add(sum(jv.on.values()) == scheduled)
    kinds = list(starts)
    for before, after in pairwise(kinds):
        model.add(starts[after] >= jv.end(before)).only_enforce_if(scheduled)
    return jv


def solve(
    instance: Instance,
    cfg: SchedulerConfig,
    *,
    hint: Schedule | None = None,
    deterministic_time: float | None = None,
    weights: Weights | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Schedule:
    check_instance(instance, cfg.durations)
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
    machine_intervals: dict[str, list[_JobVars]] = {}
    manual_intervals: list[cp_model.IntervalVar] = []
    intervals: dict[str, list[cp_model.IntervalVar]] = {}
    for jv in all_vars:
        for code, on in jv.on.items():
            intervals.setdefault(code, []).append(
                model.new_optional_fixed_size_interval_var(
                    jv.starts["machine"], jv.durations["machine"], on, f"m_{jv.job.id}_{code}"
                )
            )
            machine_intervals.setdefault(code, []).append(jv)
        # TASK_ORDER, not the MANUAL set: a set's order changes from one Python process to the
        # next (string hashing is randomised), which changed the model and so the schedule.
        for kind in TASK_ORDER:
            if kind in MANUAL and kind in jv.starts:
                manual_intervals.append(
                    model.new_optional_fixed_size_interval_var(
                        jv.starts[kind], jv.durations[kind], jv.scheduled, f"{kind}i_{jv.job.id}"
                    )
                )
    for code_intervals in intervals.values():
        model.add_no_overlap(code_intervals)
    if manual_intervals:
        model.add_cumulative(manual_intervals, [1] * len(manual_intervals), instance.staff)

    # A fixed task may already run past the horizon; the finish time must be allowed to follow it.
    finish_ub = max(
        [horizon]
        + [
            jv.fixed_start + jv.durations["machine"]
            for jv in all_vars
            if jv.fixed_start is not None
        ]
    )
    extras = _Extras(finish=model.new_int_var(0, finish_ub, "finish_time"))
    changeover_terms: list[cp_model.LinearExprT] = []
    for code, jobs in machine_intervals.items():
        changeover_terms.append(_simple_changeovers(model, code, jobs, co_time, extras))

    # Lateness and finish time.
    objective: list[cp_model.LinearExprT] = []
    for jv in all_vars:
        completion = jv.end(list(jv.starts)[-1])
        multiplier = w.rush_multiplier if jv.job.rush else 1
        # A job already overdue can be late by more than the horizon (finding from M3 review).
        jv.tardiness = model.new_int_var(
            0, finish_ub - min(0, jv.job.due), f"tardiness_{jv.job.id}"
        )
        jv.late = model.new_bool_var(f"late_{jv.job.id}")
        model.add(jv.tardiness >= completion - jv.job.due).only_enforce_if(jv.scheduled)
        model.add(jv.tardiness <= (finish_ub - min(0, jv.job.due)) * jv.late)
        model.add(extras.finish >= completion).only_enforce_if(jv.scheduled)
        objective += [
            w.late_job * multiplier * jv.late,
            w.tardiness_per_minute * multiplier * jv.tardiness,
            w.unscheduled_job * (1 - jv.scheduled),
        ]
    objective += [w.changeover * term for term in changeover_terms]
    objective.append(w.finish_time_per_minute * extras.finish)
    model.minimize(sum(objective))

    if hint is not None:
        _add_hint(model, all_vars, extras, hint)

    solver = cp_model.CpSolver()
    solver.parameters.random_seed = cfg.solver.random_seed
    solver.parameters.num_workers = cfg.solver.workers
    solver.parameters.max_deterministic_time = (
        deterministic_time or cfg.solver.deterministic_time_seconds
    )
    started = clock()
    status = solver.solve(model)
    wall = clock() - started

    found = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    info: dict[str, object] = {
        "variant": "simple",
        "status": solver.status_name(status),
        "objective": "stand-in changeovers",
        "solver_objective": solver.objective_value if found else None,
        "solver_bound": solver.best_objective_bound if found else None,
        "deterministic_time": round(solver.deterministic_time, 2),
        "wall_seconds": round(wall, 2),
        "hinted": hint is not None,
        "fallback": None,
    }
    method = METHOD
    if not found:
        if hint is not None:
            # Nothing found in the limit: give back the hint, saying so, rather than nothing.
            info["fallback"] = hint.method
            return Schedule(method, hint.plans, hint.unscheduled, info)
        return Schedule(method, (), tuple(j.id for j in instance.jobs), info)

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
    return Schedule(method, tuple(plans), tuple(unscheduled), info)


def _simple_changeovers(
    model: cp_model.CpModel, code: str, jobs: list[_JobVars], co_time: int, extras: _Extras
) -> cp_model.LinearExprT:
    """Pairwise separation for different materials; returns (distinct materials used - 1)."""
    for i, a in enumerate(jobs):
        for b in jobs[i + 1 :]:
            if a.job.material == b.job.material or co_time == 0 or (a.fixed and b.fixed):
                continue
            a_first = model.new_bool_var(f"order_{code}_{a.job.id}_{b.job.id}")
            extras.order.append((a.job.id, b.job.id, code, a_first))
            both = [a.on[code], b.on[code]]
            model.add(b.starts["machine"] >= a.end("machine") + co_time).only_enforce_if(
                [*both, a_first]
            )
            model.add(a.starts["machine"] >= b.end("machine") + co_time).only_enforce_if(
                [*both, ~a_first]
            )
    used: dict[str, cp_model.IntVar] = {}
    for jv in jobs:
        material = jv.job.material
        if material not in used:
            used[material] = model.new_bool_var(f"uses_{code}_{material}")
            extras.used[(code, material)] = used[material]
        model.add_implication(jv.on[code], used[material])
    machine_used = model.new_bool_var(f"used_{code}")
    extras.machine_used[code] = machine_used
    model.add_max_equality(machine_used, list(used.values()))
    return sum(used.values()) - machine_used


def _add_hint(
    model: cp_model.CpModel, all_vars: list[_JobVars], extras: _Extras, hint: Schedule
) -> None:
    """A value for every variable, from the hint schedule, so CP-SAT starts from a complete
    solution instead of having to repair a partial one (finding from the M3 review)."""
    plans = {p.job_id: p for p in hint.plans}
    starts: dict[str, int] = {}
    machine_of: dict[str, str] = {}
    finish = 0
    for jv in all_vars:
        plan = plans.get(jv.job.id)
        model.add_hint(jv.scheduled, plan is not None)
        for code, on in jv.on.items():
            model.add_hint(on, jv.fixed or (plan is not None and plan.machine == code))
        tardiness = 0
        if plan is not None:
            for kind, start in jv.starts.items():
                slot = plan.slot(kind)
                if slot is not None:
                    model.add_hint(start, slot.start)
            machine_slot = plan.slot("machine")
            assert machine_slot is not None
            starts[jv.job.id] = machine_slot.start
            machine_of[jv.job.id] = plan.machine
            tardiness = max(0, plan.completion - jv.job.due)
            finish = max(finish, plan.completion)
        elif jv.fixed_start is not None:  # blocks its machine even when not scheduled
            starts[jv.job.id] = jv.fixed_start
            machine_of[jv.job.id] = next(iter(jv.on))
        assert jv.tardiness is not None and jv.late is not None
        model.add_hint(jv.tardiness, tardiness)
        model.add_hint(jv.late, tardiness > 0)
    model.add_hint(extras.finish, finish)
    for a, b, code, a_first in extras.order:
        if machine_of.get(a) == code and machine_of.get(b) == code and a in starts and b in starts:
            model.add_hint(a_first, starts[a] < starts[b])
    materials = {jv.job.id: jv.job.material for jv in all_vars}
    for (code, material), var in extras.used.items():
        model.add_hint(
            var, any(m == code and materials[j] == material for j, m in machine_of.items())
        )
    for code, var in extras.machine_used.items():
        model.add_hint(var, code in machine_of.values())
