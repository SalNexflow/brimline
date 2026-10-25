"""Who may do what. Pure functions, no database, no model (hard rule 4).

Every API route calls `can()` before acting, and every order query applies `order_scope()`.
The decisions are listed by hand in tests/test_permissions.py.
"""

from dataclasses import dataclass
from typing import Literal

Role = Literal["staff", "planner", "operator", "customer"]
Action = Literal[
    "order.list",
    "order.read",
    "order.create",
    "order.history.read",
    "customer.list",
    "material.list",
]


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: Role
    customer_id: int | None  # set only for customers


@dataclass(frozen=True)
class OrderTarget:
    """The order being read, or the order about to be created, identified by its customer."""

    customer_id: int


# Actions a role may take on any target.
_ANY_TARGET: dict[str, frozenset[str]] = {
    "staff": frozenset(
        {
            "order.list",
            "order.read",
            "order.create",
            "order.history.read",
            "customer.list",
            "material.list",
        }
    ),
    "planner": frozenset({"order.list", "order.read", "order.history.read", "material.list"}),
    "operator": frozenset({"order.list", "order.read", "material.list"}),
}

# Actions a role may take only on targets that belong to its own customer.
_OWN_TARGET: dict[str, frozenset[str]] = {
    "customer": frozenset({"order.list", "order.read", "order.create", "material.list"}),
}

# Actions with no single target. For customers, order.list is narrowed by order_scope().
_TARGETLESS = frozenset({"order.list", "customer.list", "material.list"})


def can(actor: Actor, action: Action, target: OrderTarget | None = None) -> bool:
    if action in _ANY_TARGET.get(actor.role, frozenset()):
        return True
    if action not in _OWN_TARGET.get(actor.role, frozenset()):
        return False  # default deny
    if actor.customer_id is None:
        return False  # a customer without a customer id fails closed
    if action in _TARGETLESS:
        return True
    return target is not None and target.customer_id == actor.customer_id


def order_scope(actor: Actor) -> int | None:
    """The only customer whose orders this actor may see, or None for all customers."""
    if actor.role != "customer":
        return None
    if actor.customer_id is None:
        raise PermissionError("customer user has no customer id")
    return actor.customer_id
