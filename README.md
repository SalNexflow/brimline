# Brimline

Production planning for a **fictional** made-to-order 3D-print and CNC shop: a messy customer request becomes a quote,
the work is planned across machines by a constraint solver, every plan is proven valid by an independent checker,
and the day is re-planned when something breaks. AI reads language and explains; code decides prices, dates,
permissions, and schedules.

> Status: **M6 (disruptions and re-planning).** A planner types what broke; the AI proposes typed events, code
> resolves the times, the planner confirms, and the re-plan shows what moves and why before anyone approves it.
> Earlier: **M5 (production board).** A planner presses Plan day (it solves in the background), reads the plan as bars
> per machine with an independent-check badge, and approves it; operators then work per-machine queues. Earlier:
> **M4 (independent checker).** Every plan is re-validated by a checker that shares no code with the
> scheduler and recomputes the numbers from raw inputs; the rules are in `docs/SCHEDULE_RULES.md`. Earlier: **M3
> (scheduler, baselines, benchmark).** A CP-SAT scheduler plans the work across machines and shifts and is
> benchmarked against two greedy baselines in `eval/results/BENCH.md`. Earlier: **M2 (pricing rules and AI quote builder).** A customer message becomes an AI-drafted quote that code prices
> and staff approve into an order. Earlier: demo login for four roles, orders by hand, append-only audit log.
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
| `eval` | Run the evaluations (quote reading, disruption reading, file checker) and write `eval/results/RESULTS.md`, `DISRUPTIONS.md` and `FILES.md` (the first two need model access; see `eval/README.md`) |
| `bench` | Scheduler benchmark against two baselines, every plan re-checked by the independent checker; writes `eval/results/BENCH.md` and fails if the checker disagrees (slow: 25 CP-SAT runs; `--quick` for a smoke run into `eval/results/quick`) |
| `replan-bench` | Re-planning scenarios: lateness versus jobs moved, every re-plan checked; writes `eval/results/REPLAN.md` |

## Known limits

- Plan day runs on one background thread inside the engine process: fine for one engine, not for several
  (a separate worker would be the next step, `docs/DECISIONS.md` D68).
- Plan times are wall-clock minutes in the shop's time zone, so an overnight print across a clock change is
  an hour longer or shorter in real time than its minute count.
- A quote line gets its part size from a checked model file (or staff); a job still missing one is listed as
  "cannot plan" with a link to attach a file. Print-time and weight estimates from a file are rough formulas
  (`config/files.toml`), not a slicer.
- File checks judge overhangs in the orientation the file was saved in, and wall thickness with one ray per
  face, which can miss thin features on finely curved parts. The file-check evaluation uses generated shapes
  only (`eval/results/FILES.md`).
- Material deliveries are not modelled yet: stock is assumed on hand (M6 adds delays).
- When a new plan replaces the approved one, finished manual work (prep, post-processing) of jobs that are
  not yet done is planned again; only machine work carries over as fixed.

## Demo login

Sign-in is a list of seeded demo people (staff, planner, operator, customer), with no passwords. The engine signs a
short-lived session token; the web keeps it in an httpOnly cookie. This is a demo mechanism, not real authentication:
it only works while `DEMO_LOGIN=true`, and the default is off.

## Not affiliated

Brimline is a portfolio project. It is not affiliated with any real company and uses no real customer data, brands, or copyrighted models.
