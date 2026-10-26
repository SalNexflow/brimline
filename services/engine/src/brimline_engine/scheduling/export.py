"""An instance and a schedule as a plain JSON document, the only thing the checker reads.

Data flows one way: scheduler -> JSON -> checker. Only raw inputs and the plan go in; nothing
the scheduler derives (durations, shift windows, eligible machines, metrics) does, so the
checker has to work those out itself. Shifts, staff and weights are not in the document either:
the checker reads them from config/scheduler.toml, as the scheduler does.
"""

from typing import Any

from brimline_engine.scheduling.model import Fixed, Instance, Job, JobPlan, Machine, Schedule

FORMAT = "brimline-plan/1"


def machine_doc(m: Machine) -> dict[str, Any]:
    return {
        "code": m.code,
        "process": m.process,
        "materials": sorted(m.materials),
        "build_mm": list(m.build_mm),
    }


def job_doc(j: Job) -> dict[str, Any]:
    return {
        "id": j.id,
        "arrival": j.arrival,
        "material": j.material,
        "process": j.process,
        "part_mm": list(j.part_mm),
        "quantity": j.quantity,
        "minutes_per_part": j.minutes_per_part,
        "post_minutes_per_part": j.post_minutes_per_part,
        "due": j.due,
        "rush": j.rush,
        "release": j.release,
    }


def fixed_doc(f: Fixed) -> dict[str, Any]:
    return {"job_id": f.job_id, "machine": f.machine, "start": f.start}


def instance_doc(instance: Instance) -> dict[str, Any]:
    return {
        "name": instance.name,
        "horizon": instance.horizon,
        "machines": [machine_doc(m) for m in instance.machines],
        "jobs": [job_doc(j) for j in instance.jobs],
        "fixed": [fixed_doc(f) for f in instance.fixed],
    }


def plan_doc(p: JobPlan) -> dict[str, Any]:
    return {
        "job_id": p.job_id,
        "machine": p.machine,
        "tasks": [{"kind": s.kind, "start": s.start, "end": s.end} for s in p.slots],
    }


def schedule_doc(schedule: Schedule) -> dict[str, Any]:
    return {
        "method": schedule.method,
        "jobs": [plan_doc(p) for p in schedule.plans],
        "unscheduled": list(schedule.unscheduled),
    }


def document(instance: Instance, schedule: Schedule) -> dict[str, Any]:
    return {"format": FORMAT, "instance": instance_doc(instance), "plan": schedule_doc(schedule)}
