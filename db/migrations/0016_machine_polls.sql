-- M12b: the Connectivity tab. Every status call to a machine, by the engine's poller or by a person's
-- "Test connection", is recorded here; the tab derives each machine's connection state from these rows.
-- They are telemetry, not the audit log: rows older than `keep_minutes` (config/connectivity.toml) are
-- deleted, so the app role may delete. A person's test is also written to the append-only audit log.
CREATE TABLE machine_polls (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    machine_code  text NOT NULL CHECK (char_length(machine_code) <= 20),
    at            timestamptz NOT NULL,                      -- real time (a record, not the shop clock)
    source        text NOT NULL CHECK (source IN ('poll', 'test')),
    ok            boolean NOT NULL,                          -- the machine gave a usable answer
    response_ms   integer NOT NULL CHECK (response_ms >= 0),
    state         text CHECK (state IN ('idle', 'running', 'done', 'failed', 'offline')),
    error_kind    text CHECK (error_kind IN ('timeout', 'refused', 'unsupported', 'protocol', 'other')),
    error         text NOT NULL DEFAULT '' CHECK (char_length(error) <= 400),        -- what Brimline saw
    machine_says  text NOT NULL DEFAULT '' CHECK (char_length(machine_says) <= 400), -- untrusted
    tested_by     bigint REFERENCES users (id),
    CHECK ((source = 'test') = (tested_by IS NOT NULL)),
    CHECK (ok = (error_kind IS NULL))
);
CREATE INDEX machine_polls_by_machine ON machine_polls (machine_code, at DESC);

-- Test connection's rate limit: one row per person and machine, taken atomically (an upsert that only
-- succeeds when the last test is old enough), so two clicks at once cannot both pass (review of M12b).
-- The app role may not take advisory locks (0004), and the slot is taken and committed before the
-- machine is called, so no transaction stays open while a machine takes its time to answer.
CREATE TABLE connection_test_slots (
    user_id       bigint NOT NULL REFERENCES users (id),
    machine_code  text NOT NULL CHECK (char_length(machine_code) <= 20),
    taken_at      timestamptz NOT NULL,
    PRIMARY KEY (user_id, machine_code)
);

GRANT SELECT, INSERT, DELETE ON machine_polls TO brimline_app;
GRANT SELECT, INSERT, UPDATE ON connection_test_slots TO brimline_app;
