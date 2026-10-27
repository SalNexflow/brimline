-- M5: planning runs, versioned schedules, and the tasks operators work from.
--
-- Guards in the database, on top of the checks in the engine (hard rule 7):
--   * at most one approved schedule at a time (partial unique index);
--   * a schedule's plan document never changes once saved, and its status only moves
--     draft -> approved | discarded, approved -> superseded;
--   * a task can only be written for the approved schedule, so an unapproved plan can never
--     reach an operator's queue.

-- What the scheduler needs to know about a job (docs/SCHEDULE_RULES.md). Nullable: a job without
-- them is shown as "cannot plan: missing ...", never guessed.
ALTER TABLE jobs
    ADD COLUMN minutes_per_part integer CHECK (minutes_per_part > 0),
    ADD COLUMN part_x_mm integer CHECK (part_x_mm > 0),
    ADD COLUMN part_y_mm integer CHECK (part_y_mm > 0),
    ADD COLUMN part_z_mm integer CHECK (part_z_mm > 0),
    ADD COLUMN post_processing text[] NOT NULL DEFAULT '{}'
        CHECK (post_processing <@ ARRAY['sanding', 'painting', 'assembly']);

-- One row per press of "Plan day". The solve runs in the background; the board polls this row.
CREATE TABLE planning_runs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status       text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    phase        text NOT NULL DEFAULT 'queued',  -- what it is doing now, for the progress display
    progress     jsonb NOT NULL DEFAULT '{}',     -- best schedule so far, share of the work budget
    error        text,
    requested_by bigint NOT NULL REFERENCES users (id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    started_at   timestamptz,
    finished_at  timestamptz,
    schedule_id  bigint  -- set when done; the schedule refers back to this run
);
-- One run at a time: a second "Plan day" while one is running gets the running one.
CREATE UNIQUE INDEX planning_runs_one_active ON planning_runs ((true))
    WHERE status IN ('queued', 'running');

CREATE SEQUENCE schedule_version_seq;

CREATE TABLE schedules (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version     integer NOT NULL UNIQUE DEFAULT nextval('schedule_version_seq'),
    status      text NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'approved', 'superseded', 'discarded')),
    run_id      bigint NOT NULL UNIQUE REFERENCES planning_runs (id),
    anchor      timestamptz NOT NULL,  -- minute 0 of the plan: Monday 08:00 shop time
    document    jsonb NOT NULL,        -- the brimline-plan/1 document the checker reads
    fingerprint text NOT NULL,         -- of the planning inputs; approval refuses a stale plan
    solver_info jsonb NOT NULL,        -- method, status, times (shown, never used as the check)
    unplannable jsonb NOT NULL DEFAULT '[]',  -- jobs left out for missing data, and why
    created_by  bigint NOT NULL REFERENCES users (id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    decided_by  bigint REFERENCES users (id),
    decided_at  timestamptz,
    CONSTRAINT decided_schedules_say_who CHECK (
        (status = 'draft') = (decided_by IS NULL AND decided_at IS NULL)
    )
);
-- At most one approved schedule (added requirement M5.3).
CREATE UNIQUE INDEX schedules_one_approved ON schedules ((true)) WHERE status = 'approved';

ALTER TABLE planning_runs ADD CONSTRAINT planning_runs_schedule_fk
    FOREIGN KEY (schedule_id) REFERENCES schedules (id);

CREATE FUNCTION schedules_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'schedules are versions and are never deleted';
    END IF;
    IF NEW.document IS DISTINCT FROM OLD.document
       OR NEW.fingerprint IS DISTINCT FROM OLD.fingerprint
       OR NEW.anchor IS DISTINCT FROM OLD.anchor
       OR NEW.run_id IS DISTINCT FROM OLD.run_id THEN
        RAISE EXCEPTION 'schedule % is a saved version: its plan cannot change', OLD.version;
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'draft' AND NEW.status IN ('approved', 'discarded'))
        OR (OLD.status = 'approved' AND NEW.status = 'superseded')
    ) THEN
        RAISE EXCEPTION 'schedule % cannot go from % to %', OLD.version, OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER schedules_guard BEFORE UPDATE OR DELETE ON schedules
    FOR EACH ROW EXECUTE FUNCTION schedules_guard();

-- The tasks table from 0001 was never used; it is rebuilt around schedules and the scheduler's
-- four task kinds (prep, machine, post, finish).
DROP TABLE tasks;

CREATE TABLE tasks (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    schedule_id   bigint NOT NULL REFERENCES schedules (id),
    job_id        bigint NOT NULL REFERENCES jobs (id),
    seq           integer NOT NULL CHECK (seq > 0),
    kind          text NOT NULL CHECK (kind IN ('prep', 'machine', 'post', 'finish')),
    machine_id    bigint REFERENCES machines (id),
    planned_start timestamptz NOT NULL,
    planned_end   timestamptz NOT NULL,
    actual_start  timestamptz,
    actual_end    timestamptz,
    status        text NOT NULL DEFAULT 'planned'
                  CHECK (status IN ('planned', 'running', 'done', 'failed', 'cancelled')),
    UNIQUE (schedule_id, job_id, seq),
    CHECK (planned_end > planned_start),
    -- Server-clock times; a task marked done in the same instant it started is allowed.
    CHECK (actual_end >= actual_start),
    CHECK ((kind = 'machine') = (machine_id IS NOT NULL)),
    CHECK ((status IN ('running', 'done', 'failed')) = (actual_start IS NOT NULL)),
    CHECK ((status IN ('done', 'failed')) = (actual_end IS NOT NULL))
);
CREATE INDEX tasks_schedule_idx ON tasks (schedule_id);
CREATE INDEX tasks_job_idx ON tasks (job_id);

CREATE FUNCTION tasks_only_for_the_approved_schedule() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    schedule_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'tasks are never deleted';
    END IF;
    SELECT status INTO schedule_status FROM schedules WHERE id = NEW.schedule_id;
    IF schedule_status IS DISTINCT FROM 'approved' THEN
        RAISE EXCEPTION 'tasks can only be written for the approved schedule (schedule is %)',
            schedule_status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER tasks_only_for_the_approved_schedule BEFORE INSERT OR UPDATE OR DELETE ON tasks
    FOR EACH ROW EXECUTE FUNCTION tasks_only_for_the_approved_schedule();

GRANT SELECT, INSERT, UPDATE ON planning_runs, schedules, tasks TO brimline_app;
GRANT USAGE ON SEQUENCE schedule_version_seq TO brimline_app;
