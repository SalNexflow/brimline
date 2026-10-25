# Brimline

Production planning for a **fictional** made-to-order 3D-print and CNC shop: a messy customer request becomes a quote,
the work is planned across machines by a constraint solver, every plan is proven valid by an independent checker,
and the day is re-planned when something breaks. AI reads language and explains; code decides prices, dates,
permissions, and schedules.

> Status: **M1 (base app, database, demo roles).** Demo login for four roles, orders by hand, append-only audit log.
> All data is synthetic.
> Results tables will appear here only once `make eval` and `make bench` produce them.

## Layout

| Path | What lives there |
|---|---|
| `apps/web` | Next.js web app (TypeScript strict) |
| `services/engine` | Python FastAPI engine: scheduler, checker, file checker |
| `db` | Migrations and seed |
| `config` | Dated config: model names, prices, thresholds, solver weights |
| `eval` | Evaluation datasets and results |
| `data` | Fake shop data and generated test models |
| `scripts` | Task runner (`tasks.mjs`) and the gate self-test |
| `docs` | Brief, milestones, decisions, defect log, ideas |

## Requirements

Git, Node 24 LTS, pnpm, [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for the engine), Docker, and optionally GNU make.

## Commands

Every command works as `make <name>` or `pnpm run <name>`. Both call `scripts/tasks.mjs`, so they behave the same in
PowerShell, Git Bash, and CI. (Use `pnpm run`, not bare `pnpm`: `pnpm setup` is a built-in pnpm command.)

First run: `make setup` then `make gate`.

| Command | What it does |
|---|---|
| `setup` | Install dependencies and the Playwright browser, create `.env`, start PostgreSQL |
| `dev` | Run database, engine (port 8000) and web (port 3000) |
| `gate` | The quality gate: types, lint, format, unit tests, engine tests, browser test |
| `test` | Unit tests only (web and engine) |
| `db-reset` | Drop, migrate, and re-seed the dev database from `config/shop.toml` |
| `api-types` | Regenerate the web's TypeScript types from the engine's OpenAPI schema |
| `gate-selftest` | Proves the gate fails: plants deliberate errors in a throwaway copy and checks each is caught at the right step. Refuses to run on a dirty git tree |
| `eval` | Run all evaluations (from M2) |
| `bench` | Scheduler benchmark against baselines (from M3) |

## Demo login

Sign-in is a list of seeded demo people (staff, planner, operator, customer), with no passwords. The engine signs a
short-lived session token; the web keeps it in an httpOnly cookie. This is a demo mechanism, not real authentication:
it only works while `DEMO_LOGIN=true`, and the default is off.

## Not affiliated

Brimline is a portfolio project. It is not affiliated with any real company and uses no real customer data, brands, or copyrighted models.
