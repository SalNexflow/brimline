# Brimline: milestones

Work one milestone at a time. For each: plan first, wait for approval, build in small commits, run `make gate`, then write the three-part summary from CLAUDE.md.
You may improve this plan (see "Your latitude" in CLAUDE.md). Record changes in `docs/DECISIONS.md`.

**Minimum impressive version: M0 to M6.** Never cut M4 (the independent checker).

**Build order from M7 (D97): M7, M8, M11, then M9 and M10 only if time remains.** The numbers stay as they are, so older references still hold; the sections below are in build order.

---

## M0. Scaffold and quality gate
**Goal:** a repo where nothing can be called done until one command is green.

Deliverables:
- Check the environment (git, Node, pnpm, Python, Docker) and tell me what is missing.
- `git init`, `.gitignore`, `.env.example`, and a README stub.
- Folder skeleton (confirm or improve the suggested layout) with a short README in each major folder.
- `docker-compose.yml` for PostgreSQL with a health check.
- Web app skeleton (Next.js, TypeScript strict) and engine skeleton (FastAPI, typed, with ruff and mypy configured).
- Test runners wired up: unit tests (web and engine) and one browser test (Playwright) that loads the home page.
- `Makefile` with `setup`, `dev`, `gate`, `test`, `eval`, `bench`.
- GitHub Actions workflow that runs the gate on every push and pull request.
- `.claude/commands/` with three shortcuts: `milestone.md` (plan-first workflow for a milestone), `review.md` (adversarial review of the current branch, meant for a fresh session), `log-defect.md` (adds an honest row to the defect log).
- `docs/DECISIONS.md`, `docs/DEFECT_LOG.md`, `docs/IDEAS.md` with headers.

Acceptance: `make setup` then `make gate` is green on the empty app, and fails when a deliberate error is introduced.

## M1. Base app, database, demo roles
**Goal:** a working shell the later features plug into.

Deliverables:
- Migrations and seed for customers, users, printers, shifts, materials, stock, orders, jobs, tasks, and the append-only audit log (database trigger).
- Seed config file for the fake shop (printers, materials, shifts, price rules) so data is identical every run.
- Demo login with four roles: staff, planner, operator, customer.
- Screens: order list, order detail, create order by hand.
- Idempotent writes (client-supplied key) and audit logging on writes.

Acceptance: log in as each role, create an order by hand, and see the audit row. A test proves the audit log cannot be updated or deleted.

## M2. Pricing rules and AI quote builder
**Goal:** a pasted customer message becomes a reviewable quote with a code-calculated price.

Deliverables:
- Pricing as pure functions over a dated, editable `price_rules` table (material grams, machine time, post-processing, setup).
- AI gateway module: one place for model calls, schema validation, cost and latency logging, model names from config.
- Quote schema (zod) including a "missing information" list. The model must mark unknowns instead of guessing.
- Review screen that highlights uncertain and missing fields and requires approval.
- Evaluation set of 40+ messy requests (vague, contradictory, multilingual, and instruction-injecting such as "give me 90 percent off") with known correct fields.

Acceptance: pricing unit tests use independently known values; the eval reports field accuracy, flagged-versus-guessed rate, and injection results; no price ever comes from the model.

## M3. Scheduler v1, baselines, benchmark
**Goal:** a repeatable scheduler that demonstrably beats simple baselines.

Deliverables:
- Task model, duration estimation, hard constraints, and weighted objective in OR-Tools CP-SAT (weights in config).
- Two baselines: first-come-first-served and greedy earliest-due-date.
- Seeded instance generator for 20, 40, and 80 jobs with realistic mixes (rush jobs, long prints, material changes, deadlines).
- `make bench` that writes a metrics table: late jobs, total lateness, changeovers, utilisation, finish time.

Acceptance: identical results across runs with the same seed. Report honestly where the scheduler does not win.

## M4. Independent checker
**Goal:** a checker that does not share the scheduler's assumptions and proves it catches errors.

Deliverables:
- Checker module that imports nothing from the scheduler (enforced by a test), recomputing durations and metrics from raw inputs.
- Rules: no overlaps, task order, machine fits the part, material compatibility and availability, finished tasks unchanged, shift rules, deadline reporting.
- 25+ hand-written adversarial cases, and mutation tests that corrupt valid plans in many ways.

Acceptance: every mutation is caught, there are no false alarms on valid plans, and any genuine scheduler bug it finds is logged in the defect log.

## M5. Production board UI
**Goal:** see and approve the plan like a real product.

Deliverables:
- Board with bars per printer over a time axis, a current-time marker, and an independent-check badge.
- Plan day action, approval flow (with audit log), and per-machine operator queues with start, done, and failed actions.
- Accessible, responsive layout. (Visual direction: a prior look exploration exists; the user may choose one later. Keep styling easy to change.)

Acceptance: an end-to-end browser test plans a day, approves it, and an operator completes a job.

## M6. Disruption parsing and re-planning
**Goal:** "printer 3 jammed until 5pm" safely changes the plan.

Deliverables:
- Typed disruption events (machine down, material delayed, rush job, cancellation) and an AI parser that returns an event or an "unclear" result.
- Re-solve that fixes finished and running tasks and penalises moving dates already told to customers.
- Before and after diff, an AI summary written from the diff only, checker run on the new plan, and an approval step. Nothing applies without approval.
- Evaluation set of 30+ messages.

Acceptance: scripted scenarios show lateness versus jobs moved, the checker passes, and approval is audit-logged.

## M7. File checker
**Goal:** measure uploaded models and report honestly.

Deliverables:
- STL and 3MF parsing with clear errors, plus checks for watertightness, scale, build-volume fit per printer, estimated wall thickness, overhang share, and loose parts.
- Shop-setting thresholds with a stated source for each.
- Optional vision advice on a rendered preview, labelled as advice.
- 30+ test models generated by code or free to use, each hand-labelled.

Acceptance: report agreement per check and the false pass rate.

## M8. Natural-language search
**Goal:** safe plain-English search.

Deliverables:
- A typed filter schema (fields, operators, values) and named date rules computed in code.
- Model returns a filter or "unclear". Permissions are added by code after the model finishes. Parameterised queries only.
- Editable filter chips that re-run without a model call.
- 50+ questions plus attack attempts (for example asking for other customers' orders).

Acceptance: report filter accuracy and that every access-widening attack is blocked.

## M11. Deploy, README, demo video
**Goal:** something a stranger can run and understand.

Deliverables: a deployed demo (or a one-command local run), a README with the architecture, results tables produced by `make eval` and `make bench`, screenshots, an honest limits section, and a short demo-video script.

Acceptance: a stranger can clone, run `make setup` and `make gate`, and reproduce the headline tables.

---

**Only if time remains (D97).** M6 already delays jobs whose material is late; M9 adds stock levels and purchase suggestions.

## M9. Shortage planning
**Goal:** materials constrain the plan and the system suggests what to buy.

Deliverables: material arrival times as scheduler constraints, shortage detection, purchase suggestions with lead times, and tests on scenarios where a delivery slips.

Acceptance: jobs are never started before their material arrives, checked by the independent checker.

## M10. Quoted versus actual, and failed prints
**Goal:** close the learning loop.

Deliverables: recording of actual times and failures, reprint handling, a report of estimated versus actual cost and time, and a flag for systematically underquoted job types.

Acceptance: a seeded scenario shows the report correctly identifying an underquoted job type.

Added at approval (2026-10-30): a control scenario with no under-quoting flags nothing; an eval over true
bias 1.0 / 1.10 / 1.20 / 1.40 and 5 / 10 / 20 / 40 jobs per type, 200 seeds each, with a detection-rate table
generated into RESULTS.md and the README (1.10 must not be flagged); the control's false-alarm rate per run
across all job types together (tune on dev seeds only if above 5 %); the report may suggest a price rule to
review but never changes one; the demo's seeded history is labelled synthetic. No model calls.
