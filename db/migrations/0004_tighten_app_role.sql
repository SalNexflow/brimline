-- Fixes from the M1 adversarial review (docs/DEFECT_LOG.md #6, #9, #10).

-- 1. The app may add audit rows but not choose their id or timestamp. With a full INSERT grant
--    it could backdate entries (`at`) or plant a high `id` (OVERRIDING SYSTEM VALUE) that later
--    collides with the identity sequence and blocks every write.
REVOKE INSERT ON audit_log FROM brimline_app;
GRANT INSERT (actor_user_id, action, entity_type, entity_id, before, after, idempotency_key)
    ON audit_log TO brimline_app;

-- 2. No temporary tables. A temp table named audit_log is found before public.audit_log on the
--    search path, so it could silently swallow audit rows on a pooled connection.
-- 3. Only the app role (and the owner) may connect to this database.
DO $$
BEGIN
    EXECUTE format('REVOKE TEMPORARY, CONNECT ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO brimline_app', current_database());
END;
$$;

-- 4. Sign-out revokes tokens: every token carries the user's session version, and sign-out
--    increments it. The app may change only this one column of users.
ALTER TABLE users ADD COLUMN session_version integer NOT NULL DEFAULT 1 CHECK (session_version > 0);
GRANT UPDATE (session_version) ON users TO brimline_app;
