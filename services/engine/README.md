# services/engine

Python FastAPI service. It will hold the scheduler (M3), the independent checker (M4), re-planning (M6), and the file checker (M7).

- Python 3.12, managed by [uv](https://docs.astral.sh/uv/). `uv sync` creates `.venv` from `uv.lock`.
- Code lives in `src/brimline_engine/`, tests in `tests/`.
- Quality: `ruff check`, `ruff format --check`, `mypy` (strict), `pytest`. All of them run in `make gate`.

Run it on its own: `uv run uvicorn brimline_engine.main:app --reload --port 8000`, then open `http://localhost:8000/health`.
