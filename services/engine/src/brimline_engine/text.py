"""String types for anything that reaches the database.

PostgreSQL text cannot hold a NUL byte; without this check such input became a 500
(DEFECT_LOG #7). Rejecting it at the schema boundary turns it into an ordinary 422.
"""

from typing import Annotated

from pydantic import AfterValidator


def _no_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("must not contain NUL characters")
    return value


SafeText = Annotated[str, AfterValidator(_no_nul)]


def plain_text(text: str, limit: int = 400) -> str:
    """Text a machine sent, made safe to store: no control characters (a NUL would fail the
    database's text check and stop a loop that records it), at most `limit` characters. It is
    still untrusted data: shown labelled, never obeyed."""
    return "".join(ch for ch in text if ch.isprintable())[:limit]


# Order numbers look like BL-0001. Anything else cannot be an order, so it never reaches SQL.
ORDER_NUMBER_PATTERN = r"^BL-[0-9]{4,10}$"

# Idempotency keys: printable, URL-safe characters only (UUIDs fit).
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9._:-]{8,200}$"
