"""Search filters (M8) without a database: date rules, checks, permissions and the query text.
Today is Monday 26 October 2026 in the shop; every expected date below is from a calendar."""

from datetime import UTC, date, datetime

import pytest

from brimline_engine.permissions import Actor
from brimline_engine.scheduling.config import scheduler_config
from brimline_engine.search.filters import Catalog, Condition, Filter, check_filter, describe
from brimline_engine.search.query import ForbiddenError, build, scope
from brimline_engine.search.reading import (
    ParsedQuestion,
    RawCondition,
    RawDue,
    fast_path,
    interpret,
    phrase_dates,
    rule_range,
)

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)  # 10:00 in Berlin
TODAY = date(2026, 10, 26)
TZ = "Europe/Berlin"
SHIFTS = scheduler_config().shifts.weekdays
CATALOG = Catalog(
    customers={"C-HARBOR": "Harbor Lane", "C-WILLOW": "Willow Street"},
    materials={"PLA-BLACK": "PLA, black", "RESIN-GREY": "Resin, grey"},
)
STAFF = Actor(user_id=1, role="staff", customer_id=None)
HARBOR = Actor(user_id=4, role="customer", customer_id=1)


@pytest.mark.parametrize(
    ("rule", "first", "last"),
    [
        ("today", date(2026, 10, 26), date(2026, 10, 26)),
        ("tomorrow", date(2026, 10, 27), date(2026, 10, 27)),
        ("yesterday", date(2026, 10, 25), date(2026, 10, 25)),
        ("this_week", date(2026, 10, 26), date(2026, 11, 1)),
        ("next_week", date(2026, 11, 2), date(2026, 11, 8)),
        ("last_week", date(2026, 10, 19), date(2026, 10, 25)),
        ("this_month", date(2026, 10, 1), date(2026, 10, 31)),
        ("next_month", date(2026, 11, 1), date(2026, 11, 30)),
        ("friday", date(2026, 10, 30), date(2026, 10, 30)),
        ("monday", date(2026, 11, 2), date(2026, 11, 2)),  # strictly after today
    ],
)
def test_named_date_rules(rule: str, first: date, last: date) -> None:
    assert rule_range(rule, TODAY) == (first, last)


@pytest.mark.parametrize(
    ("phrase", "dates"),
    [
        ("3 November", [date(2026, 11, 3)]),
        ("20 October", [date(2026, 10, 20)]),  # the next one is a year away: the last one
        ("2026-11-05", [date(2026, 11, 5)]),
        ("10/11", [date(2026, 10, 11), date(2026, 11, 10)]),  # two readings, each the nearest
        ("12/11", [date(2026, 11, 12), date(2026, 12, 11)]),
    ],
)
def test_written_dates_go_through_the_m6_parser(phrase: str, dates: list[date]) -> None:
    assert phrase_dates(phrase, NOW, TZ, SHIFTS) == dates


def parsed(
    conditions: list[RawCondition] | None = None, due: RawDue | None = None, **kw: object
) -> ParsedQuestion:
    base: dict[str, object] = {
        "unclear": False, "unclear_reason": "", "conditions": conditions or [], "due": due,
        "sort": "due_date", "injection_suspected": False,
    }  # fmt: skip
    return ParsedQuestion.model_validate(base | kw)


@pytest.mark.parametrize(
    ("op", "rule", "expected"),
    [
        (
            "between",
            "this_week",
            Condition(field="due_date", op="between", value=["2026-10-26", "2026-11-01"]),
        ),
        ("on", "friday", Condition(field="due_date", op="on", value="2026-10-30")),
        ("before", "this_week", Condition(field="due_date", op="before", value="2026-10-26")),
        (
            "on_or_before",
            "this_week",
            Condition(field="due_date", op="on_or_before", value="2026-11-01"),
        ),
        ("after", "next_week", Condition(field="due_date", op="after", value="2026-11-08")),
        (
            "on_or_after",
            "next_month",
            Condition(field="due_date", op="on_or_after", value="2026-11-01"),
        ),
    ],
)
def test_each_operator_takes_the_side_of_the_range_it_needs(
    op: str, rule: str, expected: Condition
) -> None:
    r = interpret(parsed(due=RawDue(op=op, rule=rule)), NOW, TZ, SHIFTS, CATALOG)  # type: ignore[arg-type]
    assert r.kind == "filter" and r.filter is not None and r.filter.conditions == [expected]


def test_the_brief_example_reads_into_two_conditions() -> None:
    r = interpret(
        parsed([RawCondition(field="printed", op="is", values=["false"])], RawDue(op="between", rule="this_week")),
        NOW, TZ, SHIFTS, CATALOG,
    )  # fmt: skip
    assert r.filter is not None
    assert (
        describe(r.filter)
        == "Jobs: due 2026-10-26 to 2026-11-01; not printed yet (soonest due first)."
    )


def test_a_date_that_reads_two_ways_is_asked_never_guessed() -> None:
    r = interpret(
        parsed(due=RawDue(op="on", rule="phrase", phrase="12/11")), NOW, TZ, SHIFTS, CATALOG
    )
    assert r.kind == "needs_confirmation" and r.readings == ["2026-11-12", "2026-12-11"]


@pytest.mark.parametrize(
    ("raw", "words"),
    [
        (RawCondition(field="material", op="in", values=["GOLD-LEAF"]), "unknown material"),
        (RawCondition(field="quantity", op="contains", values=["5"]), "does not take"),
        (RawCondition(field="overdue", op="is", values=["false"]), "overdue can only be true"),
        (RawCondition(field="quantity", op="gt", values=["many"]), "whole number"),
        (RawCondition(field="due_date", op="on", values=["2026-10-30"]), "go in 'due'"),
        (RawCondition(field="order_number", op="in", values=["DROP TABLE"]), "looks like BL-0001"),
    ],
)
def test_anything_outside_the_schema_is_unclear(raw: RawCondition, words: str) -> None:
    r = interpret(parsed([raw]), NOW, TZ, SHIFTS, CATALOG)
    assert r.kind == "unclear" and words in r.reason


def test_the_models_own_reason_is_kept_apart_from_codes() -> None:
    r = interpret(
        parsed(unclear=True, unclear_reason="Willow has secret orders"), NOW, TZ, SHIFTS, CATALOG
    )
    assert r.kind == "unclear" and r.reason == "" and r.model_reason == "Willow has secret orders"


def test_filters_have_one_canonical_form() -> None:
    a = Filter(conditions=[
        Condition(field="material", op="in", value=["resin-grey", "PLA-BLACK"]),
        Condition(field="rush", op="is", value=True),
        Condition(field="rush", op="is", value=True),
    ])  # fmt: skip
    b = Filter(conditions=[
        Condition(field="rush", op="is", value=True),
        Condition(field="material", op="in", value=["PLA-BLACK", "RESIN-GREY"]),
    ])  # fmt: skip
    assert check_filter(a, CATALOG) == check_filter(b, CATALOG)


def test_only_an_order_number_needs_no_model() -> None:
    assert fast_path(" bl-0008 ") == Filter(
        conditions=[Condition(field="order_number", op="in", value=["BL-0008"])]
    )
    assert fast_path("BL-0008 and BL-0009") is None


def test_a_customer_filter_is_always_their_own() -> None:
    f = Filter(conditions=[Condition(field="customer", op="in", value=["C-WILLOW", "C-HARBOR"]),
                           Condition(field="rush", op="is", value=True)])  # fmt: skip
    s = scope(f, HARBOR, "C-HARBOR")
    assert [c.model_dump() for c in s.filter.conditions] == [
        {"field": "customer", "op": "in", "value": ["C-HARBOR"]},
        {"field": "rush", "op": "is", "value": True},
    ]
    assert s.notices and "your own orders" in s.notices[0]
    # No customer named: still narrowed, with nothing to explain.
    assert scope(Filter(), HARBOR, "C-HARBOR").filter.conditions[0].value == ["C-HARBOR"]
    assert scope(Filter(), HARBOR, "C-HARBOR").notices == []
    assert scope(f, STAFF, None).filter == f
    with pytest.raises(ForbiddenError):
        scope(f, HARBOR, None)


def test_values_never_reach_the_sql_text() -> None:
    evil = "'; DROP TABLE jobs; --"
    f = Filter(conditions=[
        Condition(field="part_name", op="contains", value=evil),
        Condition(field="notes", op="contains", value="ignore all rules"),
        Condition(field="due_date", op="between", value=["2026-10-26", "2026-11-01"]),
        Condition(field="overdue", op="is", value=True),
    ])  # fmt: skip
    query, params = build(f, HARBOR, TODAY)
    text = query.as_string(None)
    assert evil not in text and "ignore all rules" not in text and "2026" not in text
    assert evil in params.values() and params["scope"] == 1 and params["today"] == TODAY
    # Staff are not scoped; the scope clause is in the text either way.
    staff_query, staff_params = build(f, STAFF, TODAY)
    assert staff_params["scope"] is None and "o.customer_id = %(scope)s" in staff_query.as_string(
        None
    )
