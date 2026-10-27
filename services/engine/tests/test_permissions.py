"""The permission table, written by hand before the policy existed (hard rule 10).

Each row is one decision a person can check against the brief without reading the code.
Customer 1 and customer 2 are two different fictional customers.
"""

import pytest

from brimline_engine.permissions import Action, Actor, OrderTarget, can, capabilities, order_scope

STAFF = Actor(user_id=1, role="staff", customer_id=None)
PLANNER = Actor(user_id=2, role="planner", customer_id=None)
OPERATOR = Actor(user_id=3, role="operator", customer_id=None)
CUSTOMER_1 = Actor(user_id=4, role="customer", customer_id=1)

OWN = OrderTarget(customer_id=1)  # an order (or new order) belonging to customer 1
OTHER = OrderTarget(customer_id=2)  # an order (or new order) belonging to customer 2

# (actor, action, target, expected allowed)
TABLE: list[tuple[Actor, Action, OrderTarget | None, bool]] = [
    # Staff (front desk): sees and creates orders for any customer, sees history.
    (STAFF, "order.list", None, True),
    (STAFF, "order.read", OTHER, True),
    (STAFF, "order.create", OTHER, True),
    (STAFF, "order.history.read", OTHER, True),
    (STAFF, "customer.list", None, True),
    (STAFF, "material.list", None, True),
    # Planner: reads every order and its history, but does not take orders.
    (PLANNER, "order.list", None, True),
    (PLANNER, "order.read", OTHER, True),
    (PLANNER, "order.create", OTHER, False),
    (PLANNER, "order.history.read", OTHER, True),
    (PLANNER, "customer.list", None, False),
    (PLANNER, "material.list", None, True),
    # Operator: reads orders to know what to make; no history, no order taking.
    (OPERATOR, "order.list", None, True),
    (OPERATOR, "order.read", OTHER, True),
    (OPERATOR, "order.create", OTHER, False),
    (OPERATOR, "order.history.read", OTHER, False),
    (OPERATOR, "customer.list", None, False),
    (OPERATOR, "material.list", None, True),
    # Customer: only their own orders; may create orders only for themselves; never sees history.
    (CUSTOMER_1, "order.list", None, True),  # allowed, but scoped to customer 1 (see below)
    (CUSTOMER_1, "order.read", OWN, True),
    (CUSTOMER_1, "order.read", OTHER, False),
    (CUSTOMER_1, "order.create", OWN, True),
    (CUSTOMER_1, "order.create", OTHER, False),
    (CUSTOMER_1, "order.history.read", OWN, False),
    (CUSTOMER_1, "order.history.read", OTHER, False),
    (CUSTOMER_1, "customer.list", None, False),
    (CUSTOMER_1, "material.list", None, True),
    # Targeted actions without a target are refused rather than guessed.
    (CUSTOMER_1, "order.read", None, False),
    (CUSTOMER_1, "order.create", None, False),
    # --- M2: quotes and price rules (written before the policy change) ---
    # Staff run the front desk: submit on behalf of anyone, edit, approve, and set prices.
    (STAFF, "quote.list", None, True),
    (STAFF, "quote.read", OTHER, True),
    (STAFF, "quote.submit", OTHER, True),
    (STAFF, "quote.edit", OTHER, True),
    (STAFF, "quote.approve", OTHER, True),
    (STAFF, "price_rules.read", None, True),
    (STAFF, "price_rules.write", None, True),
    # Planner: may look at quotes and prices (to see what is coming), never change them.
    (PLANNER, "quote.list", None, True),
    (PLANNER, "quote.read", OTHER, True),
    (PLANNER, "quote.submit", OTHER, False),
    (PLANNER, "quote.edit", OTHER, False),
    (PLANNER, "quote.approve", OTHER, False),
    (PLANNER, "price_rules.read", None, True),
    (PLANNER, "price_rules.write", None, False),
    # Operator: works on orders only; quotes and prices are not their concern.
    (OPERATOR, "quote.list", None, False),
    (OPERATOR, "quote.read", OTHER, False),
    (OPERATOR, "quote.submit", OTHER, False),
    (OPERATOR, "quote.edit", OTHER, False),
    (OPERATOR, "quote.approve", OTHER, False),
    (OPERATOR, "price_rules.read", None, False),
    (OPERATOR, "price_rules.write", None, False),
    # Customer: submits and reads their own requests; can never edit or approve, not even their own.
    (CUSTOMER_1, "quote.list", None, True),  # scoped to customer 1 by order_scope()
    (CUSTOMER_1, "quote.read", OWN, True),
    (CUSTOMER_1, "quote.read", OTHER, False),
    (CUSTOMER_1, "quote.submit", OWN, True),
    (CUSTOMER_1, "quote.submit", OTHER, False),
    (CUSTOMER_1, "quote.edit", OWN, False),
    (CUSTOMER_1, "quote.approve", OWN, False),
    (CUSTOMER_1, "price_rules.read", None, False),
    (CUSTOMER_1, "price_rules.write", None, False),
    # M5 production board. The planner plans and approves (hard rule 7: a human approves);
    # the operator works the queues; staff (front desk) may look at the plan; customers never.
    (PLANNER, "schedule.read", None, True),
    (PLANNER, "schedule.plan", None, True),
    (PLANNER, "schedule.approve", None, True),
    (PLANNER, "queue.read", None, True),
    (PLANNER, "task.update", None, False),
    (OPERATOR, "schedule.read", None, True),
    (OPERATOR, "queue.read", None, True),
    (OPERATOR, "task.update", None, True),
    (OPERATOR, "schedule.plan", None, False),
    (OPERATOR, "schedule.approve", None, False),
    (STAFF, "schedule.read", None, True),
    (STAFF, "schedule.plan", None, False),
    (STAFF, "schedule.approve", None, False),
    (STAFF, "queue.read", None, False),
    (STAFF, "task.update", None, False),
    (CUSTOMER_1, "schedule.read", None, False),
    (CUSTOMER_1, "queue.read", None, False),
    (CUSTOMER_1, "task.update", None, False),
]


@pytest.mark.parametrize(
    ("actor", "action", "target", "expected"),
    TABLE,
    ids=[
        f"{a.role}-{action}-{'own' if t is OWN else 'other' if t is OTHER else 'none'}"
        for a, action, t, _ in TABLE
    ],
)
def test_permission_table(
    actor: Actor, action: Action, target: OrderTarget | None, expected: bool
) -> None:
    assert can(actor, action, target) is expected


def test_unknown_action_is_denied_for_every_role() -> None:
    # Default deny: an action nobody wrote a rule for is refused, even for staff.
    for actor in (STAFF, PLANNER, OPERATOR, CUSTOMER_1):
        assert can(actor, "order.delete", OTHER) is False  # type: ignore[arg-type]


def test_customer_without_customer_id_is_denied_everything() -> None:
    # A broken user row must fail closed, not act as "all customers".
    broken = Actor(user_id=9, role="customer", customer_id=None)
    assert can(broken, "order.list", None) is False
    assert can(broken, "order.read", OrderTarget(customer_id=1)) is False
    with pytest.raises(PermissionError):
        order_scope(broken)


def test_order_scope_limits_customers_to_their_own_orders() -> None:
    # None means "all customers"; a number is the only customer whose orders may be returned.
    assert order_scope(STAFF) is None
    assert order_scope(PLANNER) is None
    assert order_scope(OPERATOR) is None
    assert order_scope(CUSTOMER_1) == 1


def test_capabilities_per_role() -> None:
    assert capabilities(STAFF) == [
        "customer.list",
        "material.list",
        "order.create",
        "order.history.read",
        "order.list",
        "order.read",
        "price_rules.read",
        "price_rules.write",
        "quote.approve",
        "quote.edit",
        "quote.list",
        "quote.read",
        "quote.submit",
        "schedule.read",
    ]
    assert capabilities(PLANNER) == [
        "material.list",
        "order.history.read",
        "order.list",
        "order.read",
        "price_rules.read",
        "queue.read",
        "quote.list",
        "quote.read",
        "schedule.approve",
        "schedule.plan",
        "schedule.read",
    ]
    assert capabilities(OPERATOR) == [
        "material.list",
        "order.list",
        "order.read",
        "queue.read",
        "schedule.read",
        "task.update",
    ]
    assert capabilities(CUSTOMER_1) == [
        "material.list",
        "order.create",
        "order.list",
        "order.read",
        "quote.list",
        "quote.read",
        "quote.submit",
    ]
    assert capabilities(Actor(user_id=9, role="customer", customer_id=None)) == []
