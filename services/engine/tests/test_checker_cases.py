"""Hand-written adversarial cases for the checker (M4). Plans are built by hand, not by a
scheduler, and every expected answer is worked out in the comment next to it.

Test rules, small enough to do in your head (not the shop's config):
  prep 10, setup 0, no cool-down, finish 10 (+0 per part), changeover 30, 2 people,
  shifts Mon-Fri 08:00-17:00 -> minutes [0,540), [1440,1980), [2880,3420), ...
Job A: PLA, 1 part x 100 min, due 1000 -> prep 10, machine 100, finish 10.
Its plan "A_OK": prep 0-10, machine on M1 10-110, finish 110-120.
"""

import copy
from dataclasses import asdict
from typing import Any

import pytest

from brimline_engine.checker import DocumentError, Rules, check_document, rules_from_toml

TOML: dict[str, Any] = {
    "durations": {
        "prep_minutes": 10,
        "setup_minutes": 0,
        "changeover_minutes": 30,
        "finish_base_minutes": 10,
        "finish_minutes_per_part": 0,
        "cool_down_minutes": {},
    },
    "staff": {"people_per_shift": 2},
    "shifts": {
        "weekdays": {str(d): ["08:00", "17:00"] for d in range(1, 6)},
        "horizon_days": 7,
    },
    "weights": {
        "late_job": 1000,
        "tardiness_per_minute": 10,
        "changeover": 600,
        "finish_time_per_minute": 1,
        "unscheduled_job": 1_000_000,
        "rush_multiplier": 3,
    },
}
RULES: Rules = rules_from_toml(TOML)
M1 = {"code": "M1", "process": "fdm", "materials": ["PETG", "PLA"], "build_mm": [256, 256, 256]}
M2 = {"code": "M2", "process": "fdm", "materials": ["PETG", "PLA"], "build_mm": [256, 256, 256]}
MILL = {"code": "MILL", "process": "cnc", "materials": ["AL"], "build_mm": [400, 300, 150]}


def job(id_: str, **kw: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": id_,
        "arrival": 1,
        "material": "PLA",
        "process": "fdm",
        "part_mm": [50, 50, 50],
        "quantity": 1,
        "minutes_per_part": 100,
        "post_minutes_per_part": 0,
        "due": 1000,
        "rush": False,
        "release": 0,
    }
    return base | kw


def plan(id_: str, machine: str, *tasks: tuple[str, int, int]) -> dict[str, Any]:
    return {
        "job_id": id_,
        "machine": machine,
        "tasks": [{"kind": k, "start": s, "end": e} for k, s, e in tasks],
    }


def std(id_: str, machine: str, at: int) -> dict[str, Any]:
    """A job like A with prep at `at`: prep at..at+10, machine +10..+110, finish +110..+120."""
    return plan(
        id_,
        machine,
        ("prep", at, at + 10),
        ("machine", at + 10, at + 110),
        ("finish", at + 110, at + 120),
    )


A_OK = std("A", "M1", 0)


def doc(
    jobs: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    unscheduled: tuple[str, ...] = (),
    fixed: tuple[dict[str, Any], ...] = (),
    machines: tuple[dict[str, Any], ...] = (M1, M2, MILL),
    horizon: int = 7 * 1440,
) -> dict[str, Any]:
    # A copy, so a test that breaks its document cannot change shared plans such as A_OK.
    return copy.deepcopy(
        {
            "format": "brimline-plan/1",
            "instance": {
                "name": "hand",
                "horizon": horizon,
                "machines": list(machines),
                "jobs": jobs,
                "fixed": list(fixed),
            },
            "plan": {"method": "hand", "jobs": plans, "unscheduled": list(unscheduled)},
        }
    )


def codes(d: dict[str, Any], rules: Rules = RULES) -> set[str]:
    return check_document(d, rules).codes()


# --- Valid plans: no false alarms -------------------------------------------------------------


def test_valid_single_job_and_its_metrics() -> None:
    r = check_document(doc([job("A")], [A_OK]), RULES)
    assert r.violations == () and r.warnings == ()
    assert r.metrics is not None
    # finish 120, nothing late, no changeover: objective = 120 x 1.
    # Utilisation: 100 machine minutes / (3 machines x 120) = 0.2777...
    assert asdict(r.metrics) == {
        "scheduled": 1,
        "unscheduled": 0,
        "late_jobs": 0,
        "late_or_unscheduled": 0,
        "rush_late_jobs": 0,
        "total_lateness_minutes": 0,
        "changeovers": 0,
        "utilisation": 100 / 360,
        "finish_time": 120,
        "objective": 120,
    }


def test_late_rush_job_is_valid_and_its_lateness_is_reported() -> None:
    # Due 100, done 120: 20 minutes late. Rush x3: 3 x (1000 + 10 x 20) = 3600, + finish 120.
    r = check_document(doc([job("A", due=100, rush=True)], [A_OK]), RULES)
    assert r.valid
    assert r.metrics is not None
    assert (r.metrics.late_jobs, r.metrics.rush_late_jobs, r.metrics.total_lateness_minutes) == (
        1,
        1,
        20,
    )
    assert r.metrics.objective == 3600 + 120
    assert [(d.job, d.tardiness) for d in r.deadlines] == [("A", 20)]


def test_done_exactly_at_due_is_on_time() -> None:
    r = check_document(doc([job("A", due=120)], [A_OK]), RULES)
    assert r.metrics is not None and r.metrics.late_jobs == 0


def test_machine_task_may_start_in_the_last_minute_and_run_overnight() -> None:
    # Prep 529-539 (inside), machine 539-639 (starts 16:59), finish next morning 1440-1450.
    p = plan("A", "M1", ("prep", 529, 539), ("machine", 539, 639), ("finish", 1440, 1450))
    assert codes(doc([job("A")], [p])) == set()


def test_part_may_be_turned_to_fit() -> None:
    # 390 x 140 x 290 on a 400 x 300 x 150 mill: upright it is 290 tall (> 150), but sorted
    # (140, 290, 390) fits (150, 300, 400).
    j = job("A", process="cnc", material="AL", part_mm=[390, 140, 290])
    assert codes(doc([j], [std("A", "MILL", 0)])) == set()


def test_same_material_back_to_back_needs_no_gap() -> None:
    b = plan("B", "M1", ("prep", 10, 20), ("machine", 110, 210), ("finish", 210, 220))
    assert codes(doc([job("A"), job("B")], [A_OK, b])) == set()


def test_different_material_exactly_30_apart_is_fine() -> None:
    b = plan("B", "M1", ("prep", 10, 20), ("machine", 140, 240), ("finish", 240, 250))
    r = check_document(doc([job("A"), job("B", material="PETG")], [A_OK, b]), RULES)
    assert r.valid
    assert r.metrics is not None and r.metrics.changeovers == 1


def test_two_people_may_work_at_once_and_hand_over_on_the_minute() -> None:
    # A and B prep together (2 people); C preps 10-20 as soon as one is free.
    jobs = [job("A"), job("B"), job("C")]
    plans = [
        A_OK,
        std("B", "M2", 0),
        plan("C", "M1", ("prep", 10, 20), ("machine", 110, 210), ("finish", 210, 220)),
    ]
    assert codes(doc(jobs, plans)) == set()


def test_unscheduled_job_is_allowed_and_counted() -> None:
    # B listed unscheduled: valid, but it counts in late_or_unscheduled and costs 1,000,000.
    r = check_document(doc([job("A"), job("B")], [A_OK], unscheduled=("B",)), RULES)
    assert r.valid
    assert r.metrics is not None
    assert (r.metrics.unscheduled, r.metrics.late_or_unscheduled) == (1, 1)
    assert r.metrics.objective == 120 + 1_000_000


def test_fixed_task_is_a_fact_even_off_shift_and_before_release() -> None:
    # Running since before minute 0 (-100), material "released" later on paper: facts win.
    # A fixed job has no prep. Machine -100..0, finish 0-10.
    j = job("A", release=500)
    p = plan("A", "M1", ("machine", -100, 0), ("finish", 0, 10))
    fixed = ({"job_id": "A", "machine": "M1", "start": -100},)
    assert codes(doc([j], [p], fixed=fixed)) == set()


def test_fixed_tasks_back_to_back_need_no_changeover() -> None:
    # A (PLA) 0-100 and B (PETG) 100-200 were run that way: reality skipped the gap.
    fixed = (
        {"job_id": "A", "machine": "M1", "start": 0},
        {"job_id": "B", "machine": "M1", "start": 100},
    )
    pa = plan("A", "M1", ("machine", 0, 100), ("finish", 100, 110))
    pb = plan("B", "M1", ("machine", 100, 200), ("finish", 200, 210))
    assert codes(doc([job("A"), job("B", material="PETG")], [pa, pb], fixed=fixed)) == set()


def test_fixed_task_may_run_past_the_horizon() -> None:
    # Horizon 1440; A has been fixed at 0 for 2000 minutes. Finishing is switched off here so
    # A has no task after the horizon other than the fixed one.
    rules = rules_from_toml(TOML | {"durations": TOML["durations"] | {"finish_base_minutes": 0}})
    p = plan("A", "M1", ("machine", 0, 2000))
    fixed = ({"job_id": "A", "machine": "M1", "start": 0},)
    assert (
        codes(doc([job("A", minutes_per_part=2000)], [p], fixed=fixed, horizon=1440), rules)
        == set()
    )


# --- Plan bookkeeping -------------------------------------------------------------------------


def test_job_missing_from_the_plan() -> None:
    assert codes(doc([job("A"), job("B")], [A_OK])) == {"missing_job"}


def test_job_planned_twice() -> None:
    assert codes(doc([job("A")], [A_OK, A_OK])) == {"duplicate_job"}


def test_job_both_planned_and_unscheduled() -> None:
    assert codes(doc([job("A")], [A_OK], unscheduled=("A",))) == {"duplicate_job"}


def test_planned_job_not_in_the_instance() -> None:
    assert codes(doc([job("A")], [A_OK, std("GHOST", "M2", 200)])) == {"unknown_job"}


def test_unscheduled_job_not_in_the_instance() -> None:
    assert codes(doc([job("A")], [A_OK], unscheduled=("GHOST",))) == {"unknown_job"}


def test_unknown_machine() -> None:
    assert codes(doc([job("A")], [std("A", "M9", 0)])) == {"unknown_machine"}


def test_missing_task() -> None:
    p = plan("A", "M1", ("prep", 0, 10), ("machine", 10, 110))
    assert codes(doc([job("A")], [p])) == {"wrong_tasks"}


def test_post_task_when_none_was_asked_for() -> None:
    p = plan(
        "A", "M1", ("prep", 0, 10), ("machine", 10, 110), ("post", 110, 115), ("finish", 115, 125)
    )
    assert codes(doc([job("A")], [p])) == {"wrong_tasks"}


def test_tasks_listed_out_of_order() -> None:
    # Listed machine first: wrong order of kinds, and prep (0-10) starts before machine ends.
    p = plan("A", "M1", ("machine", 10, 110), ("prep", 0, 10), ("finish", 110, 120))
    assert codes(doc([job("A")], [p])) == {"wrong_tasks", "task_order"}


# --- Durations and order ----------------------------------------------------------------------


def test_machine_task_one_minute_short() -> None:
    p = plan("A", "M1", ("prep", 0, 10), ("machine", 10, 109), ("finish", 109, 119))
    assert codes(doc([job("A")], [p])) == {"wrong_duration"}


def test_post_duration_uses_quantity() -> None:
    # 3 parts x 100 = 300 machine; post 3 x 5 = 15; one minute short on post.
    j = job("A", quantity=3, post_minutes_per_part=5)
    p = plan(
        "A", "M1", ("prep", 0, 10), ("machine", 10, 310), ("post", 310, 324), ("finish", 324, 334)
    )
    assert codes(doc([j], [p])) == {"wrong_duration"}


def test_finish_starts_one_minute_before_the_machine_ends() -> None:
    p = plan("A", "M1", ("prep", 0, 10), ("machine", 10, 110), ("finish", 109, 119))
    assert codes(doc([job("A")], [p])) == {"task_order"}


# --- Machine fit --------------------------------------------------------------------------------


def test_wrong_process() -> None:
    j = job("A", process="cnc", material="PLA")
    assert codes(doc([j], [A_OK])) == {"not_eligible"}


def test_material_not_on_the_machine() -> None:
    assert codes(doc([job("A", material="TPU")], [A_OK])) == {"not_eligible"}


def test_part_one_millimetre_too_long_even_turned() -> None:
    # (401, 10, 10) sorted is (10, 10, 401); the mill's longest side is 400.
    j = job("A", process="cnc", material="AL", part_mm=[401, 10, 10])
    assert codes(doc([j], [std("A", "MILL", 0)])) == {"not_eligible"}


# --- Material and shifts ----------------------------------------------------------------------


def test_machine_starts_one_minute_before_the_material_arrives() -> None:
    assert codes(doc([job("A", release=11)], [A_OK])) == {"before_release"}


def test_machine_task_starting_at_closing_time() -> None:
    # 540 is 17:00 Monday: not in [0, 540). Finish goes to Tuesday morning.
    p = plan("A", "M1", ("prep", 530, 540), ("machine", 540, 640), ("finish", 1440, 1450))
    assert codes(doc([job("A")], [p])) == {"machine_off_shift"}


def test_machine_task_starting_at_the_weekend() -> None:
    # Saturday 09:00 = 5 x 1440 + 60 = 7260; this test rule set has no Saturday shift.
    p = plan("A", "M1", ("prep", 5760, 5770), ("machine", 7260, 7360), ("finish", 10080, 10090))
    assert codes(
        doc([job("A")], [p], horizon=14 * 1440),
        rules_from_toml(TOML | {"shifts": TOML["shifts"] | {"horizon_days": 14}}),
    ) == {"machine_off_shift"}


def test_finish_runs_one_minute_past_closing_time() -> None:
    p = plan("A", "M1", ("prep", 0, 10), ("machine", 10, 110), ("finish", 531, 541))
    assert codes(doc([job("A")], [p])) == {"manual_off_shift"}


def test_manual_task_across_the_night_is_not_inside_one_shift() -> None:
    # Prep 1435-1445 starts before Tuesday's shift opens at 1440.
    p = plan("A", "M1", ("prep", 1435, 1445), ("machine", 1445, 1545), ("finish", 1545, 1555))
    assert codes(doc([job("A")], [p])) == {"manual_off_shift"}


def test_task_before_minute_zero() -> None:
    # Outside every shift, and (since M5) before the moment of planning, which defaults to 0.
    p = plan("A", "M1", ("prep", -10, 0), ("machine", 0, 100), ("finish", 100, 110))
    assert codes(doc([job("A")], [p])) == {"manual_off_shift", "before_plan_start"}


def test_three_manual_tasks_at_one_minute_with_two_people() -> None:
    # A and B prep 0-10; C preps 9-19: at minute 9 three people would be needed.
    jobs = [job("A"), job("B"), job("C")]
    c = plan("C", "MILL", ("prep", 9, 19), ("machine", 19, 119), ("finish", 120, 130))
    c_job = job("C", process="cnc", material="AL")
    plans = [A_OK, std("B", "M2", 0), c]
    r = check_document(doc([jobs[0], jobs[1], c_job], plans), RULES)
    assert r.codes() == {"staff_overload"}
    assert len(r.violations) == 1  # one overload stretch, reported once


def test_past_the_horizon() -> None:
    # Horizon 115: the finish (110-120) ends after it.
    assert codes(doc([job("A")], [A_OK], horizon=115)) == {"past_horizon"}


# --- Machines ---------------------------------------------------------------------------------


def test_machine_tasks_overlap_by_one_minute() -> None:
    b = plan("B", "M1", ("prep", 10, 20), ("machine", 109, 209), ("finish", 209, 219))
    assert codes(doc([job("A"), job("B")], [A_OK, b])) == {"machine_overlap"}


def test_a_long_task_overlapping_two_later_ones_is_caught_twice() -> None:
    # A (3 parts) runs 10-310; B 120-220 and C 240-340 both start inside it. C does not touch
    # its neighbour B, so a check of neighbours only would miss C.
    a = plan("A", "M1", ("prep", 0, 10), ("machine", 10, 310), ("finish", 310, 320))
    b = plan("B", "M1", ("prep", 10, 20), ("machine", 120, 220), ("finish", 220, 230))
    c = plan("C", "M1", ("prep", 20, 30), ("machine", 240, 340), ("finish", 340, 350))
    r = check_document(doc([job("A", quantity=3), job("B"), job("C")], [a, b, c]), RULES)
    assert r.codes() == {"machine_overlap"}
    assert sorted(str(v.job) for v in r.violations) == ["B", "C"]


def test_different_material_only_29_minutes_apart() -> None:
    b = plan("B", "M1", ("prep", 10, 20), ("machine", 139, 239), ("finish", 239, 249))
    assert codes(doc([job("A"), job("B", material="PETG")], [A_OK, b])) == {"changeover"}


def test_changeover_is_still_needed_after_a_fixed_task() -> None:
    # A is fixed (PLA) 0-100; B (PETG) is planned at 100: only fixed-fixed pairs are exempt.
    fixed = ({"job_id": "A", "machine": "M1", "start": 0},)
    pa = plan("A", "M1", ("machine", 0, 100), ("finish", 100, 110))
    pb = plan("B", "M1", ("prep", 0, 10), ("machine", 100, 200), ("finish", 200, 210))
    assert codes(doc([job("A"), job("B", material="PETG")], [pa, pb], fixed=fixed)) == {
        "changeover"
    }


# --- Fixed tasks ------------------------------------------------------------------------------


def test_fixed_task_moved_by_one_minute() -> None:
    fixed = ({"job_id": "A", "machine": "M1", "start": 10},)
    p = plan("A", "M1", ("machine", 11, 111), ("finish", 111, 121))
    assert codes(doc([job("A")], [p], fixed=fixed)) == {"fixed_moved"}


def test_fixed_task_moved_to_another_machine() -> None:
    fixed = ({"job_id": "A", "machine": "M1", "start": 10},)
    p = plan("A", "M2", ("machine", 10, 110), ("finish", 110, 120))
    assert codes(doc([job("A")], [p], fixed=fixed)) == {"fixed_moved"}


def test_fixed_job_must_not_list_its_prep() -> None:
    fixed = ({"job_id": "A", "machine": "M1", "start": 10},)
    assert codes(doc([job("A")], [A_OK], fixed=fixed)) == {"wrong_tasks"}


def test_a_fixed_task_blocks_its_machine_even_if_its_job_is_unscheduled() -> None:
    # A is running 10-110 on M1 but listed unscheduled; B planned on M1 at 50 overlaps it.
    fixed = ({"job_id": "A", "machine": "M1", "start": 10},)
    b = plan("B", "M1", ("prep", 0, 10), ("machine", 50, 150), ("finish", 150, 160))
    r = check_document(doc([job("A"), job("B")], [b], unscheduled=("A",), fixed=fixed), RULES)
    assert r.codes() == {"machine_overlap"}


# --- Impossible instances and malformed documents ----------------------------------------------


def test_overlapping_fixed_tasks_make_the_instance_impossible() -> None:
    fixed = (
        {"job_id": "A", "machine": "M1", "start": 0},
        {"job_id": "B", "machine": "M1", "start": 50},
    )
    r = check_document(doc([job("A"), job("B")], [], unscheduled=("A", "B"), fixed=fixed), RULES)
    assert r.codes() == {"bad_instance"} and r.metrics is None


def test_two_jobs_with_one_id_make_the_instance_impossible() -> None:
    assert codes(doc([job("A"), job("A")], [A_OK])) == {"bad_instance"}


def test_job_with_no_machine_work_makes_the_instance_impossible() -> None:
    assert codes(doc([job("A", minutes_per_part=0)], [], unscheduled=("A",))) == {"bad_instance"}


@pytest.mark.parametrize(
    "break_it",
    [
        lambda d: d.pop("format"),
        lambda d: d.update(format="brimline-plan/0"),
        lambda d: d["plan"]["jobs"][0]["tasks"][0].update(kind="paint"),
        lambda d: d["plan"]["jobs"][0]["tasks"][0].update(start=True),
        lambda d: d["plan"]["jobs"][0]["tasks"][0].update(end="110"),
        lambda d: d["instance"]["jobs"][0].update(part_mm=[50, 50]),
        lambda d: d["instance"]["jobs"][0].pop("release"),
    ],
)
def test_a_malformed_document_is_rejected_not_guessed(break_it: Any) -> None:
    d = doc([job("A")], [A_OK])
    break_it(d)
    with pytest.raises(DocumentError):
        check_document(d, RULES)


# --- Suspicious unscheduled jobs (warnings, not violations) ------------------------------------


def test_unscheduled_job_with_an_idle_machine_is_suspicious() -> None:
    # Only A is planned; B could run on M2 straight away.
    r = check_document(doc([job("A"), job("B")], [A_OK], unscheduled=("B",)), RULES)
    assert r.valid
    assert [(w.code, w.job) for w in r.warnings] == [("suspicious_unscheduled", "B")]


def test_unscheduled_job_whose_material_never_arrives_is_not_suspicious() -> None:
    r = check_document(
        doc([job("A"), job("B", release=7 * 1440)], [A_OK], unscheduled=("B",)), RULES
    )
    assert r.warnings == ()


def test_unscheduled_job_with_no_machine_that_fits_is_not_suspicious() -> None:
    r = check_document(doc([job("A"), job("B", material="TPU")], [A_OK], unscheduled=("B",)), RULES)
    assert r.warnings == ()


def test_unscheduled_job_too_long_for_the_free_time_is_not_suspicious() -> None:
    # One machine, busy 10-110; horizon 1000. B needs 2000 minutes: it cannot fit anywhere.
    r = check_document(
        doc(
            [job("A"), job("B", minutes_per_part=2000)],
            [A_OK],
            unscheduled=("B",),
            machines=(M1,),
            horizon=1000,
        ),
        RULES,
    )
    assert r.warnings == ()


# --- Found by the fresh-context review (M4) -----------------------------------------------------


def test_a_plan_made_for_other_shifts_is_refused() -> None:
    # The document says the shop was open 0-100 only; the config says Mon-Fri 08:00-17:00.
    # The checker must not judge the plan against rules the scheduler did not use.
    d = doc([job("A")], [A_OK])
    d["instance"]["shifts"] = [[0, 100]]
    assert codes(d) == {"bad_instance"}


def test_a_plan_made_for_other_staff_is_refused() -> None:
    d = doc([job("A")], [A_OK])
    d["instance"]["staff"] = 1
    assert codes(d) == {"bad_instance"}


def test_matching_shifts_and_staff_are_accepted() -> None:
    d = doc([job("A")], [A_OK])
    d["instance"]["shifts"] = [list(w) for w in RULES.windows]
    d["instance"]["staff"] = 2
    assert codes(d) == set()


@pytest.mark.parametrize(
    "change",
    [{"post_minutes_per_part": -5}, {"part_mm": [-5000, 10, 10]}, {"part_mm": [0, 10, 10]}],
)
def test_impossible_job_values_are_refused(change: dict[str, Any]) -> None:
    assert codes(doc([job("A", **change)], [A_OK])) == {"bad_instance"}


def test_a_non_positive_horizon_is_refused() -> None:
    assert codes(doc([job("A")], [], unscheduled=("A",), horizon=-5)) == {"bad_instance"}


@pytest.mark.parametrize(
    "add_key",
    [
        lambda d: d["plan"]["jobs"][0]["tasks"][0].update(machine="M2"),
        lambda d: d["instance"]["jobs"][0].update(oops=1),
        lambda d: d["plan"].update(note="x"),
        lambda d: d.update(extra=True),
    ],
)
def test_unknown_keys_are_refused(add_key: Any) -> None:
    d = doc([job("A")], [A_OK])
    add_key(d)
    with pytest.raises(DocumentError, match="unknown keys"):
        check_document(d, RULES)


def test_two_fixed_tasks_back_to_back_count_no_changeover() -> None:
    # A (PLA) and B (PETG) fixed back to back: no changeover happened, so none is counted.
    fixed = (
        {"job_id": "A", "machine": "M1", "start": 0},
        {"job_id": "B", "machine": "M1", "start": 100},
    )
    pa = plan("A", "M1", ("machine", 0, 100), ("finish", 100, 110))
    pb = plan("B", "M1", ("machine", 100, 200), ("finish", 200, 210))
    r = check_document(doc([job("A"), job("B", material="PETG")], [pa, pb], fixed=fixed), RULES)
    assert r.metrics is not None and r.metrics.changeovers == 0


def test_a_changeover_after_an_unscheduled_jobs_fixed_task_is_counted() -> None:
    # A (PLA) runs fixed 0-100 but is unscheduled; B (PETG) follows on M1 at 130: one change.
    fixed = ({"job_id": "A", "machine": "M1", "start": 0},)
    pb = plan("B", "M1", ("prep", 0, 10), ("machine", 130, 230), ("finish", 230, 240))
    r = check_document(
        doc([job("A"), job("B", material="PETG")], [pb], unscheduled=("A",), fixed=fixed), RULES
    )
    assert r.valid
    assert r.metrics is not None and r.metrics.changeovers == 1


def test_utilisation_counts_only_time_from_minute_zero() -> None:
    # A fixed since -1000, 1100 minutes, so it ends at 100; finish 100-110. Only 100 machine
    # minutes fall after minute 0: 100 / (3 machines x 110) = 0.303..., not 1100 / 330 = 3.3.
    fixed = ({"job_id": "A", "machine": "M1", "start": -1000},)
    p = plan("A", "M1", ("machine", -1000, 100), ("finish", 100, 110))
    r = check_document(doc([job("A", minutes_per_part=1100)], [p], fixed=fixed), RULES)
    assert r.valid
    assert r.metrics is not None and r.metrics.utilisation == pytest.approx(100 / 330)
