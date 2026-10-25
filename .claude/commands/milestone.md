---
description: Plan-first workflow for one Brimline milestone (plan, wait for approval, build, gate, summary)
argument-hint: <milestone id, e.g. M2>
---

You are starting milestone **$ARGUMENTS** of Brimline.

1. Read `CLAUDE.md`, then the $ARGUMENTS section of `docs/MILESTONES.md`, the parts of `docs/BRIEF.md` it depends on,
   and the latest entries in `docs/DECISIONS.md` and `docs/DEFECT_LOG.md`.
2. Run `make gate` (or `pnpm run gate`) before changing anything. If it is not green, stop and report why.
3. **Plan first and stop.** Reply with:
   - the deliverables as a short ordered list of small commits (one concern each),
   - the main design choices, each with the alternative you considered and the trade-off,
   - which hard rules from CLAUDE.md this milestone touches and how the design respects them,
   - risks and open questions,
   - the acceptance criteria you will test against, copied from MILESTONES.md plus any you add.
   Then **wait for approval**. Do not write code yet.
4. After approval, build in small commits. Check current library versions and provider docs instead of memory.
   Record every deviation or addition in `docs/DECISIONS.md` (what, why, alternative).
5. Add a test for every bug you fix. Never weaken a test to make it pass. Tests use independently known expected values.
6. Run `make gate` until it is green. Do not call anything done before that.
7. Finish with: (a) what changed and why in plain words, (b) risks and what you are unsure about,
   (c) a 3 to 5 sentence draft for the decision log for the user to rewrite.
8. If you introduced a bug that was later caught, add an honest row to `docs/DEFECT_LOG.md` (use `/log-defect`).

Do not start the next milestone until the user says "continue".
