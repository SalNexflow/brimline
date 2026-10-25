---
description: Adversarial review of the current branch. Run it in a fresh session that did not write the code.
argument-hint: [base branch, default main]
---

You are a sceptical reviewer who did **not** write this code. Your job is to find what is wrong, not to praise it.

Base for comparison: `$ARGUMENTS` (use `main` if empty).

1. Read `CLAUDE.md` (especially the hard rules) and the milestone being worked on in `docs/MILESTONES.md`.
2. Look at the change: `git log --oneline <base>..HEAD` and `git diff <base>...HEAD`. Read each changed file fully.
3. Check, and cite `file:line` for every finding:
   - **Hard rules:** does any model output set a price, date, or permission? Is every model output schema-validated?
     Does the checker import anything from the scheduler? Is any SQL built from model text? Are writes idempotent and
     audit-logged? Can a risky action happen without human approval? Is anything secret committed?
   - **Correctness:** edge cases, time zones and date boundaries, off-by-one, empty inputs, concurrency, error paths.
   - **Tests:** do they use independently known expected values, or values copied from the implementation's output?
     Would they fail if the code were wrong? Was any test weakened? Is a bug fixed without a regression test?
   - **Claims:** is any number in the README or docs not produced by a command?
   - **Explainability:** is anything more complex than it needs to be? Is any choice missing from `docs/DECISIONS.md`?
4. Run `make gate` and report the result honestly.
5. Report findings ranked most severe first: what is wrong, a concrete input or state that triggers it, and a suggested fix.
   Mark each as **confirmed** (you reproduced it) or **plausible** (you reasoned it). If you find nothing serious, say so.

Do not fix anything in this session unless asked. Suggest `/log-defect` for confirmed bugs.
