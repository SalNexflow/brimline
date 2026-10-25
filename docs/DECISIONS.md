# Decisions

Every decision, deviation from the brief, and addition. Newest at the bottom of each milestone. Keep entries short:
**what**, **why**, **alternative considered**.

## M0. Scaffold and quality gate (2026-10-25)

| # | Decision | Why | Alternative considered |
|---|---|---|---|
| D1 | Moved `BRIEF.md` and `MILESTONES.md` into `docs/`. | CLAUDE.md refers to `docs/BRIEF.md`; paths should match the instructions. | Leave them in the root and edit CLAUDE.md. |
| D2 | Added `config/` (dated config) to the suggested layout. | Hard rule 8 ("config, not memory") needs one obvious home for model names, prices, thresholds, weights. | Scatter config per service. |
| D3 | All task logic lives in one Node script, `scripts/tasks.mjs`. `make <x>` and `pnpm <x>` are thin aliases of it. | Tested on this machine: from PowerShell, GNU make ran recipes with `cmd.exe` (and `bash` on PATH is WSL, not Git Bash); from Git Bash it used bash. Node is always installed and behaves the same everywhere. | Shell recipes in the Makefile (flaky across shells); `just` (another tool to install). |
| D4 | Python tooling is **uv** with `uv.lock`, Python pinned to 3.12. | One command creates the venv with the right Python; lockfile makes installs reproducible. 3.12 is the safest version for OR-Tools (M3) and mypy. | pip + venv + requirements.txt; Python 3.14 (newer, wheel support less certain). |
| D5 | pnpm installed with `npm i -g pnpm`, not corepack. | `corepack enable` needs admin rights on Windows (EPERM writing to Program Files). | Run corepack as admin. |
| D6 | TypeScript pinned to 6.0.x, not 7.0. | `typescript-eslint` 8.72 (used by `eslint-config-next`) supports TypeScript `<6.1.0`. | TypeScript 7 with no type-aware linting. |
| D7 | PostgreSQL 18.6 (alpine) on host port 5433. | Current stable. 5433 avoids clashing with a locally installed Postgres. Volume mounts at `/var/lib/postgresql`, the Postgres 18 image layout. | Postgres 17. |
| D8 | Vitest for web unit tests, Playwright (Chromium only) for browser tests. | Vitest needs little config with TypeScript. Chromium only keeps setup and CI small. | Jest; all three Playwright browsers. |
| D9 | The gate does not touch the database in M0. | Nothing to test yet. `setup` starts Postgres and waits for its health check. DB tests join the gate in M1. | A ping test in M0 that proves little. |
| D10 | Added `gate-selftest`: copies the repo's committed files into a throwaway folder, plants five deliberate errors one at a time, and requires the gate to fail on each. Refuses to run on a dirty git tree. | Turns "the gate fails on errors" into a command result, not a claim (hard rule 11). Working on a copy means the real tree is never modified. | A manual demonstration. |
