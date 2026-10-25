---
description: Add one honest row to docs/DEFECT_LOG.md for a bug that was introduced and later caught
argument-hint: <short description of the defect>
---

Add one row to the table in `docs/DEFECT_LOG.md` for this defect: $ARGUMENTS

1. Find the facts before writing. Use `git log`, `git show`, and the test or tool output that exposed the bug.
   Identify the commit that introduced it and the one that fixed it, if they exist.
2. Fill every column:
   - **#**: next number in the table.
   - **Date**: today, as YYYY-MM-DD.
   - **Milestone**: where the bug was introduced.
   - **What was wrong**: the observable wrong behaviour, in one plain sentence.
   - **How it was introduced**: the real cause (for example a wrong assumption, a missing case, a copied value). Do not soften it.
   - **How it was caught**: the exact test, check, review, or observation.
   - **Where caught**: one of gate / test / review / checker / manual.
   - **Fix and regression test**: the fix commit and the name of the test that now guards it.
     If there is no regression test yet, write "MISSING" and say so to the user.
3. Be honest. If it was caught late or by luck, say so. Do not invent details you could not verify; write "unknown" instead.
4. Show the user the row you added.
