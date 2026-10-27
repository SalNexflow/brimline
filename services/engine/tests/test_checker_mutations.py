"""The checker against real scheduler output (M4).

1. No false alarms: every plan from FCFS, EDD and CP-SAT passes, and the checker's metrics equal
   the scheduler's own numbers (two independent implementations of one definition).
2. Mutation test: each plan is corrupted by every operator in checker/mutations.py, and every
   corrupted plan must be reported with the expected rule.
The bench runs the same mutation test on every benchmark plan (eval/results/BENCH.md).
"""

from dataclasses import asdict
from functools import cache

import pytest

from brimline_engine.checker import Rules, check_document, load_rules
from brimline_engine.checker.mutations import OPERATORS, mutants
from brimline_engine.checker.rules import Weights
from brimline_engine.scheduling.baselines import edd, fcfs
from brimline_engine.scheduling.config import SchedulerConfig, load_scheduler_config
from brimline_engine.scheduling.cpsat import solve
from brimline_engine.scheduling.export import document
from brimline_engine.scheduling.generator import generate
from brimline_engine.scheduling.metrics import evaluate
from brimline_engine.scheduling.model import Fixed, Instance, Schedule
from brimline_engine.shop_config import load_shop_config
from tests.sched_cases import BARE, CHANGEOVER, DUE_ORDER, WEIGHTS, instance, job

CFG = load_scheduler_config()
RULES = load_rules()


def with_fixed(inst: Instance) -> Instance:
    """The same instance with two jobs' machine tasks fixed where EDD put them (as if running)."""
    plans = edd(inst, CFG.durations).plans[:2]
    fixed = []
    for p in plans:
        slot = p.slot("machine")
        assert slot is not None
        fixed.append(Fixed(p.job_id, p.machine, slot.start))
    return Instance(
        inst.name + "-fixed",
        inst.horizon,
        inst.machines,
        inst.jobs,
        inst.shifts,
        inst.staff,
        tuple(fixed),
    )


@cache
def corpus() -> list[tuple[Instance, Schedule]]:
    shop = load_shop_config()
    out = []
    for seed in (1, 2):
        base = generate(seed, 20, shop, CFG)
        for inst in (base, with_fixed(base)):
            hint = edd(inst, CFG.durations)
            out += [
                (inst, fcfs(inst, CFG.durations)),
                (inst, hint),
                (inst, solve(inst, CFG, hint=hint, deterministic_time=1.0)),
            ]
    return out


def ids() -> list[str]:
    return [f"{i.name}-{s.method}" for i, s in corpus()]


@pytest.mark.parametrize("n", range(len(corpus())), ids=ids())
def test_no_false_alarms_and_the_numbers_agree(n: int) -> None:
    inst, schedule = corpus()[n]
    result = check_document(document(inst, schedule), RULES)
    assert result.violations == ()
    assert result.metrics is not None
    assert asdict(result.metrics) == pytest.approx(asdict(evaluate(inst, schedule, CFG.weights)))


@pytest.mark.parametrize("n", range(len(corpus())), ids=ids())
def test_every_corrupted_plan_is_caught(n: int) -> None:
    inst, schedule = corpus()[n]
    doc = document(inst, schedule)
    missed = [
        (name, code, sorted(check_document(m, RULES).codes()))
        for name, code, m in mutants(doc, RULES, seed=n, per_operator=3)
        if code not in check_document(m, RULES).codes()
    ]
    assert missed == []


def test_every_operator_was_exercised() -> None:
    applied = {
        name
        for n, (inst, s) in enumerate(corpus())
        for name, _, _ in mutants(document(inst, s), RULES, seed=n, per_operator=1)
    }
    assert applied == set(OPERATORS)


def test_the_corpus_really_has_fixed_tasks_and_both_methods() -> None:
    assert {s.method for _, s in corpus()} == {"fcfs", "edd", "cpsat-simple"}
    assert any(i.fixed for i, _ in corpus())


# The scheduler's own hand-worked cases, re-checked with matching stripped-down rules.
BARE_RULES = Rules(
    prep=BARE.prep_minutes,
    setup=BARE.setup_minutes,
    changeover=BARE.changeover_minutes,
    finish_base=BARE.finish_base_minutes,
    finish_per_part=BARE.finish_minutes_per_part,
    cool_down=dict(BARE.cool_down_minutes),
    post_process={},
    staff=5,
    windows=((0, 10_000),),
    weights=Weights(**WEIGHTS.model_dump()),
)
BARE_CFG: SchedulerConfig = CFG.model_copy(update={"durations": BARE, "weights": WEIGHTS})
HAND = {
    "due_order": DUE_ORDER,
    "changeover": CHANGEOVER,
    "fixed_back_to_back": instance(
        job("A", 1, 100),
        job("B", 2, 100, material="PETG"),
        job("C", 3, 10),
        fixed=(Fixed("A", "M1", 0), Fixed("B", "M1", 100)),
    ),
    "fixed_past_horizon": instance(
        job("A", 1, 1500), job("C", 2, 50), horizon=1000, fixed=(Fixed("A", "M1", 0),)
    ),
    "overdue": instance(job("A", 1, 600, due=-9500)),
    "waiting_for_material": instance(
        job("A", 1, 100, due=2000, release=1000), job("B", 2, 100, due=3000)
    ),
}


@pytest.mark.parametrize("method", ["fcfs", "edd", "cpsat"])
@pytest.mark.parametrize("name", HAND)
def test_hand_worked_scheduler_cases_pass_the_checker(name: str, method: str) -> None:
    inst = HAND[name]
    schedule = {
        "fcfs": lambda: fcfs(inst, BARE),
        "edd": lambda: edd(inst, BARE),
        "cpsat": lambda: solve(inst, BARE_CFG),
    }[method]()
    result = check_document(document(inst, schedule), BARE_RULES)
    assert result.violations == ()
    assert result.metrics is not None
    assert asdict(result.metrics) == pytest.approx(asdict(evaluate(inst, schedule, WEIGHTS)))
