-- M10: quoted versus actual, and failed prints.
--
-- Operators record why an attempt failed and, for a print or machining task, the grams it used.
-- Two reasons are set by code only: a print lost when its machine went down, and running work
-- stopped because its order was cancelled (both when a planner approves the re-plan).
-- The rule "a failed task has a reason" holds for new rows only (NOT VALID): a database that
-- already holds a failed task, like the hosted demo during the day, must still migrate.
ALTER TABLE tasks
    ADD COLUMN failure_reason text CHECK (failure_reason IN
        ('warping', 'bed_adhesion', 'layer_shift', 'clog', 'spaghetti', 'damaged_in_finishing', 'other',
         'machine_down', 'order_cancelled')),
    ADD COLUMN failure_note text CHECK (char_length(failure_note) <= 500),
    ADD COLUMN material_used_g integer CHECK (material_used_g > 0 AND material_used_g <= 1000000),
    ADD CONSTRAINT tasks_reason_only_when_failed CHECK (failure_reason IS NULL OR status = 'failed'),
    ADD CONSTRAINT tasks_grams_only_on_machines CHECK (material_used_g IS NULL OR kind = 'machine');
ALTER TABLE tasks ADD CONSTRAINT tasks_failed_has_reason
    CHECK (status <> 'failed' OR failure_reason IS NOT NULL) NOT VALID;

-- One row per finished job, written by code when the job's last task is done: what was quoted
-- against what every attempt really used, both priced with the quote's own price rules. Frozen
-- (append-only), so a report always shows what was known when the job finished.
-- Synthetic history (seeded for the demo and labelled on the Reports page) has no job.
CREATE TABLE job_outcomes (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id            bigint UNIQUE REFERENCES jobs (id),
    synthetic         boolean NOT NULL DEFAULT false,
    label             text NOT NULL,
    material_id       bigint NOT NULL REFERENCES materials (id),
    process           text NOT NULL CHECK (process IN ('fdm', 'resin', 'cnc')),
    quantity          integer NOT NULL CHECK (quantity > 0),
    price_rule_set_id bigint REFERENCES price_rule_sets (id),
    estimated_cents   integer CHECK (estimated_cents > 0),  -- NULL: the order had no quote
    actual_cents      integer CHECK (actual_cents >= 0),
    estimated_minutes integer NOT NULL CHECK (estimated_minutes > 0),
    actual_seconds    integer NOT NULL CHECK (actual_seconds >= 0),
    estimated_grams   integer CHECK (estimated_grams > 0),
    actual_grams      integer CHECK (actual_grams >= 0),
    grams_assumed     integer NOT NULL DEFAULT 0 CHECK (grams_assumed >= 0),
    attempts          integer NOT NULL CHECK (attempts >= 1),
    failed_attempts   integer NOT NULL CHECK (failed_attempts >= 0 AND failed_attempts < attempts),
    failure_reasons   text[] NOT NULL DEFAULT '{}',
    finished_at       timestamptz NOT NULL,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (synthetic = (job_id IS NULL)),
    CHECK ((estimated_cents IS NULL) = (actual_cents IS NULL)),
    CHECK (synthetic OR (estimated_cents IS NULL) = (price_rule_set_id IS NULL))
);
CREATE INDEX job_outcomes_material_idx ON job_outcomes (material_id);
CREATE TRIGGER job_outcomes_append_only BEFORE UPDATE OR DELETE ON job_outcomes
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER job_outcomes_no_truncate BEFORE TRUNCATE ON job_outcomes
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
GRANT SELECT, INSERT ON job_outcomes TO brimline_app;
