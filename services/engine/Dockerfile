# The engine (FastAPI), for `make demo` and the hosted demo (M11). Built from the repository root
# (it needs config/, db/migrations/ and the recorded replies in eval/recordings/).
#   docker build -f services/engine/Dockerfile -t brimline-engine .
FROM python:3.12-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so a code change does not reinstall them.
COPY services/engine/pyproject.toml services/engine/uv.lock services/engine/README.md services/engine/
RUN cd services/engine && uv sync --locked --no-dev --no-install-project

COPY config/ config/
COPY db/migrations/ db/migrations/
COPY eval/recordings/ eval/recordings/
COPY services/engine/src/ services/engine/src/
RUN cd services/engine && uv sync --locked --no-dev

# Not root inside the container.
RUN useradd --system --uid 10001 brimline
USER brimline

WORKDIR /app/services/engine
ENV PORT=8000
EXPOSE 8000
# Migrate (and seed an empty database) as the owner, then serve as the app role. With
# DEMO_RESET_ON_START=1 the database is reset to this week's demo first (db reset --demo).
CMD ["sh", "-c", "if [ \"${DEMO_RESET_ON_START:-0}\" = 1 ]; then .venv/bin/python -m brimline_engine.db reset --demo; else .venv/bin/python -m brimline_engine.db setup; fi && exec .venv/bin/uvicorn brimline_engine.main:app --host 0.0.0.0 --port ${PORT}"]
