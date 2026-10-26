"""Check one plan document from the command line.

    uv run python -m brimline_engine.checker plan.json

Prints the violations, warnings and metrics as JSON; exits 1 if the plan breaks a rule.
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from brimline_engine.checker import check_document


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    result = check_document(json.loads(Path(args[0]).read_text(encoding="utf-8")))
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
