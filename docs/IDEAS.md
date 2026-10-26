# Ideas not built (yet)

Bigger "nice to have" ideas, one-line pitch each. Not commitments.

- **Pre-commit hook:** run the fast half of the gate (lint, format, types) before each commit.
- **Import-boundary linter:** use `import-linter` contracts to enforce "checker never imports scheduler" in config as well as in a test.
- **Row-level security:** add Postgres RLS policies for customer scoping as a third layer behind `can()` and scoped queries.
- **Audit sign-ins:** record demo logins and sign-outs in the audit log (today only data writes are audited).
- **Expire idempotency keys:** a scheduled job that deletes keys older than, say, 24 hours (keys are not part of the audit trail).
- **Quote emails:** send `questions_for_customer` to the customer from the review page (needs an outbound-mail decision).
- **Price diff on approval:** if the price version changed since the last save, show old and new totals before approving.
- **Batch eval runs:** use the Message Batches API for `make eval --fresh` at half the cost.
- **Fix the colour rule mismatch for single-entry materials (quote prompt v2):** the prompt says "material and colour", the labelling rule says TPU and aluminium need no colour, so the model leaves them empty (q43, h04, h09, h28). Tune the prompt on the **dev split only**, and keep the pre-fix held-out score in `eval/results/RESULTS.md` as the honest number next to the new one.
- **Dates as raw text, resolved by code:** have the model return the deadline exactly as written ("12 januari", "le 20/11") and let code parse it, with month names in every supported language, so a misread like "12 januari" becoming December (h19) cannot happen.
- **Exact changeovers that actually help:** revisit AddCircuit (D49) with longer limits, several workers for a non-repeatable "best effort" mode, or a large-neighbourhood search that re-sequences one machine at a time.
- **Split large jobs** across printers when one machine would make them late.
- **Slicer-based print times** instead of the minutes-per-part formula.
