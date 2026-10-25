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
