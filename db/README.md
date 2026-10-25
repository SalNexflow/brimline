# db

PostgreSQL migrations: plain SQL files in `migrations/`, applied in name order by
`services/engine/src/brimline_engine/db/migrate.py` (see docs/DECISIONS.md D18).

- **Never edit an applied migration.** The runner stores each file's checksum and refuses a changed one. Add a new file.
- **Two roles.** The owner (`POSTGRES_USER`) runs migrations and the seed. The engine connects as `brimline_app`,
  which gets only the grants written at the end of each migration and cannot change the schema.
- **The audit log is append-only:** triggers reject UPDATE, DELETE and TRUNCATE for everyone, and the app role has only
  SELECT and INSERT on it (hard rule 6).
- Seed data comes from `config/shop.toml`; two seeds from empty produce identical rows.
