# db

Database migrations and seed data for PostgreSQL. Empty until M1.

- The migration tool is chosen in M1 and recorded in `docs/DECISIONS.md`.
- The audit log is append-only, enforced by a database trigger (hard rule 6).
- Seed data is fake and generated from `config/`, so every run produces identical data.
