#!/bin/sh
# Runs once, when the database volume is created (docker-entrypoint-initdb.d), as the
# superuser. Closes the limits kept in D34 (M11):
#   * the owner that runs migrations and the seed is NOT a superuser, so it cannot switch
#     triggers off with session_replication_role (the audit log's append-only trigger holds);
#   * only the owner may connect to the "postgres" maintenance database;
#   * only the owner may take advisory locks, so the app role cannot stall a migration.
# The superuser is used for nothing else. On a hosted database without a superuser (Neon),
# docs/SECURITY.md says which of these the host enforces and which it does not.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE brimline_owner WITH LOGIN NOSUPERUSER CREATEDB CREATEROLE NOREPLICATION NOBYPASSRLS
    PASSWORD '${POSTGRES_OWNER_PASSWORD}';
CREATE DATABASE brimline OWNER brimline_owner;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
GRANT CONNECT ON DATABASE postgres TO brimline_owner;
SQL

# Advisory-lock functions: revoked from everyone but the owner, in template1 (so every database
# created later, such as the test databases, inherits it) and in brimline.
for db in template1 brimline; do
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<'SQL'
DO $$
DECLARE f regprocedure;
BEGIN
    FOR f IN SELECT p.oid::regprocedure FROM pg_proc p
             JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'pg_catalog' AND p.proname LIKE 'pg%advisory%'
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', f);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO brimline_owner', f);
    END LOOP;
END
$$;
SQL
done
