# Security of the public demo: what is and is not hardened

Brimline is a portfolio project with a fictional shop and fake data. The hosted demo is meant to
be safe to leave open, not to hold anything real. This page says plainly which protections exist
(with the test that holds each) and which do not.

## Hardened

| Protection | How | Held by |
|---|---|---|
| Permissions on every query, after any AI step | `can()` and `order_scope()` in code; search rewrites a customer's filter and scopes its SQL | `test_permissions.py`, `test_search_*`, gate self-test mutations |
| No model-written SQL | Search builds SQL from fixed pieces; every value is a parameter | `test_values_never_reach_the_sql_text`, the search eval's "blocked" check |
| Model output is never trusted | pydantic schemas, then code checks every value | each feature's tests |
| Model text on screen is grounded | Search shows only words of the question and code's own sentences | `test_text_to_look_for_must_be_words_of_the_question` |
| Append-only audit log and records | Database triggers; the app role cannot change or drop them | `test_audit_log.py` |
| No superuser in the app's path (D34, closed in M11) | Migrations run as a non-superuser owner; the app role has only the grants it needs | `test_migrations.py` |
| Only the web may call the engine | `ENGINE_WEB_KEY`, checked on every request except `/health` | `test_only_the_web_may_call_the_engine_when_a_key_is_set` |
| Model spend | A daily budget counted from recorded call costs and a per-visitor hourly limit; then recorded replies or the by-hand path | `test_demo.py` |
| Storage | Writes refused past a database size and per-table row caps; nightly reset | `test_demo_mode_refuses_writes_past_the_row_cap` |
| Uploaded files | Size, triangle and unzipped-size caps; DOCTYPE refused by the XML parser | `test_files_checks.py` |
| Secrets | Only in `.env` and the hosts' dashboards; a gate step scans tracked files for keys | `scripts/secrets_scan.mjs` (in the gate) |
| Session cookies | httpOnly, SameSite=Lax, signed, revocable | `orders.spec.ts`, `test_session.py` |

## Not hardened (known, accepted for a demo)

- **Shared demo users.** Anyone can sign in as any demo user, including staff; that is the
  point of the demo. Real accounts and passwords are not part of Brimline.
- **No CAPTCHA, no WAF rules of our own.** Abuse is bounded by the model budget, the per-visitor
  limit, the storage caps and the nightly reset, not prevented.
- **The visitor limit is per hashed address.** Someone changing addresses gets a new hourly
  allowance; the daily budget still caps the total.
- **On Neon** there is no superuser, so two things D34 closes locally are not enforced there:
  the app role could take advisory locks and connect to other databases in the project.
  Neither reaches other data: the app role has no grants outside `brimline`'s tables.
- **No security headers beyond the framework defaults** (no strict Content-Security-Policy).
- **Denial of service** on the free tiers (an engine with a small CPU) is not defended.
- **Uploaded files are kept** until the nightly reset; they are only fake test models.
