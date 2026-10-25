# CLAUDE.md: Brimline

Read this file first, every session. Then read `docs/BRIEF.md` and `docs/MILESTONES.md`.

## What this project is
**Brimline** is a web platform for a *fictional* made-to-order 3D-print and CNC service shop.
One story end to end: customer message and 3D model file -> AI-drafted quote -> order -> scheduled jobs
-> materials -> disruption and re-plan -> quoted versus actual.

It is a portfolio project built by a person who is learning AI engineering. **All data is fake.**
No real customers, no real brands, no copyrighted 3D models. Do not imitate any real company's product, branding, or UI.

## Where things are
- `docs/BRIEF.md`: the full project brief (what, why, who, how, architecture). Source of truth for intent.
- `docs/MILESTONES.md`: the build order with acceptance criteria. Work one milestone at a time.
- `docs/DECISIONS.md`: every decision, deviation, and idea you add. Create it in M0.
- `docs/DEFECT_LOG.md`: every bug that was introduced and how it was caught. Create it in M0.
- Suggested layout (confirm or improve in M0): `apps/web` (Next.js, TypeScript), `services/engine` (Python, FastAPI),
  `db` (migrations and seed), `eval` (datasets and results), `data` (fake data, generated test models), `scripts`.

## Hard rules (do not break these without my explicit approval)
1. **The AI never computes prices, dates, or permissions.** Code does. Models only turn language into structured data, or explain a result code already computed.
2. **Every model output is validated against a schema** (zod in web, pydantic in engine) before use. Invalid output is rejected or repaired, never trusted.
3. **The checker is independent.** The schedule checker must not import anything from the scheduler. It recomputes everything from raw inputs.
4. **Permissions are enforced in code on every query,** after any AI step. The model has no say.
5. **No model-written SQL.** Natural-language search produces a typed filter only. Our own code builds parameterised queries.
6. **Writes are idempotent and audit-logged.** The audit log is append-only, enforced by a database trigger.
7. **Risky actions need human approval enforced in code** (applying a re-plan, approving a quote).
8. **Config, not memory.** Model names, prices, thresholds, and solver weights live in config files with a date. Check provider docs for current API details instead of relying on memory.
9. **No secrets in git.** Use `.env`; keep `.env.example` current.
10. **Tests use independently known expected values,** not values copied from the implementation's own output.
11. **Do not claim a number you did not measure.** Every figure in the README comes from a command, never typed by hand.

## Your latitude: improve on this plan
The brief is my best current idea, not a ceiling. **If you see a better architecture, algorithm, evaluation, library, feature, or a simpler way, implement it.** I want you to use your judgment.

Rules for doing so:
1. The hard rules above are fixed. If you think one is wrong, say so and wait for my approval.
2. **Record every deviation or addition in `docs/DECISIONS.md`:** what you changed, why, and the alternative you considered. Keep entries short.
3. **Keep every milestone shippable.** Finish a milestone's acceptance criteria before adding extras to it.
4. Ask before adding paid services, accounts, or heavy dependencies, or before touching anything outside this repository.
5. **Keep it explainable.** I must be able to understand and defend every part in an interview. Prefer the simpler design when two are close, and explain choices in plain language.
6. If an idea changes the milestones, update `docs/MILESTONES.md` and tell me.
7. Put bigger "nice to have" ideas you did not build in `docs/IDEAS.md` with a one-line pitch each.

## How to work (every milestone)
1. Read the milestone in `docs/MILESTONES.md` and the relevant parts of `docs/BRIEF.md`.
2. **Plan first.** Reply with the plan, the main design choices with alternatives and trade-offs, risks, and the acceptance criteria you will test against. Wait for my approval. (Small, obvious steps inside an approved plan do not need new approval.)
3. Build in small commits, one concern each. Keep diffs reviewable.
4. Run the quality gate (`make gate`) before calling anything done. It must be green.
5. Add a test for every bug you fix. Never weaken a test to make it pass.
6. Finish with: (a) what changed and why in plain words, (b) risks and what you are unsure about, (c) a 3 to 5 sentence draft for the decision log that I will rewrite in my own words.
7. If you introduced a bug that was later caught, add an honest row to `docs/DEFECT_LOG.md`.

## Commands (created in M0)
- `make setup`: install everything and start the database
- `make dev`: run web, engine, and database
- `make gate`: type checks, lint, unit tests, engine tests, browser tests (the quality gate)
- `make test`: unit tests only
- `make eval`: run all evaluations and write `eval/results/RESULTS.md`
- `make bench`: scheduler benchmark against baselines

## Style
- TypeScript strict mode. Python typed (mypy) and formatted (ruff).
- Small pure functions for pricing, date rules, and filters. They are easy to test.
- Plain names, short functions, comments that explain *why*.
- State why you add any dependency, and pick current stable versions after checking their docs.

## Do not
- Do not let a model decide anything a rule can decide.
- Do not use real personal data, real brands, or copyrighted assets.
- Do not delete or overwrite files outside this repository.
- Do not skip the gate, and do not merge code that nobody can explain.
