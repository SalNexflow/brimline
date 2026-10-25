"""Print the engine's OpenAPI schema as stable JSON (sorted keys), for generating web types.

uv run python -m brimline_engine.openapi
"""

import json
import sys

from brimline_engine.main import app

if __name__ == "__main__":
    sys.stdout.write(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
