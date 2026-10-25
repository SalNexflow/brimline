-- Append-only audit log (hard rule 6). Two independent guards:
--   1. Triggers reject UPDATE, DELETE and TRUNCATE for everyone, the owner included.
--   2. The app role is granted only SELECT and INSERT, and does not own the table, so it can
--      neither change rows nor disable or drop the triggers.

CREATE TABLE audit_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at              timestamptz NOT NULL DEFAULT now(),
    actor_user_id   bigint REFERENCES users (id),  -- null only for system actions
    action          text NOT NULL,                 -- e.g. 'order.create'
    entity_type     text NOT NULL,                 -- e.g. 'order'
    entity_id       text NOT NULL,                 -- e.g. 'BL-0004'
    before          jsonb,                         -- null when the entity was created
    after           jsonb,                         -- null when the entity was removed
    idempotency_key text                           -- the client key of the request that wrote it
);
CREATE INDEX audit_log_entity_idx ON audit_log (entity_type, entity_id);

CREATE FUNCTION audit_log_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
END;
$$;

CREATE TRIGGER audit_log_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_reject_change();

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_reject_change();

GRANT SELECT, INSERT ON audit_log TO brimline_app;
