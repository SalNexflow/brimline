"""The independent schedule checker (M4).

It imports nothing from the scheduler, only the standard library and its own modules (enforced
by tests/test_checker_independence.py). It reads a plan document (JSON, format brimline-plan/1)
and config/scheduler.toml, recomputes durations, shift windows and metrics itself, and checks
every rule in docs/SCHEDULE_RULES.md.
"""

from brimline_engine.checker.check import CheckResult, Deadline, Metrics, Violation, check
from brimline_engine.checker.document import DocumentError, parse
from brimline_engine.checker.rules import Rules, load_rules, rules_from_toml

__all__ = [
    "CheckResult",
    "Deadline",
    "DocumentError",
    "Metrics",
    "Rules",
    "Violation",
    "check",
    "check_document",
    "load_rules",
    "parse",
    "rules_from_toml",
]


def check_document(doc: object, rules: Rules | None = None) -> CheckResult:
    """Parse a JSON-like document and check it (with config/scheduler.toml unless given rules)."""
    return check(parse(doc), rules if rules is not None else load_rules())
