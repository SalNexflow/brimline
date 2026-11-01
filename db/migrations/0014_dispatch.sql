-- M12: dispatching work to (simulated) machines through an AI agent, with a guard and a human Proceed.
--
-- Where a task's times came from: a person pressing Start and Done (operator), the machine's own count of
-- its print time (machine), or code watching the machine (polled, for protocols that report no time).
ALTER TABLE tasks
    ADD COLUMN time_source text NOT NULL DEFAULT 'operator' CHECK (time_source IN ('operator', 'machine', 'polled')),
    ADD COLUMN machine_seconds integer CHECK (machine_seconds >= 0);
ALTER TABLE job_outcomes
    ADD COLUMN machine_reported boolean NOT NULL DEFAULT false;

-- A planner asks the dispatcher: one run, made against the approved plan of that moment.
CREATE TABLE dispatch_runs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    schedule_id  bigint NOT NULL REFERENCES schedules (id),
    asked_by     bigint NOT NULL REFERENCES users (id),
    proposed_by  text NOT NULL CHECK (proposed_by IN ('agent', 'code')),
    ai_call_id   bigint REFERENCES ai_calls (id),
    note         text NOT NULL DEFAULT '',          -- why code proposed instead of the agent, if it did
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- What the agent (or code) proposed, each pre-checked by the guard. The reason is the model's own words.
CREATE TABLE dispatch_proposals (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       bigint NOT NULL REFERENCES dispatch_runs (id),
    action       text NOT NULL CHECK (action IN ('start_task', 'stop_task')),
    task_id      bigint NOT NULL REFERENCES tasks (id),
    machine_code text NOT NULL,
    reason       text NOT NULL CHECK (char_length(reason) <= 500),
    precheck     text NOT NULL,                     -- 'pass' or the guard's rule code
    precheck_detail text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, action, task_id, machine_code)
);

-- Proceed: a person approves specific proposals. Once per proposal: a second Proceed adds nothing.
CREATE TABLE dispatch_approvals (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id  bigint NOT NULL UNIQUE REFERENCES dispatch_proposals (id),
    approved_by  bigint NOT NULL REFERENCES users (id),
    approved_role text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Every tool call, by the agent or by code, with the guard's verdict and the machine's answer.
CREATE TABLE dispatch_calls (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       bigint NOT NULL REFERENCES dispatch_runs (id),
    made_by      text NOT NULL CHECK (made_by IN ('agent', 'code', 'scripted')),  -- scripted: the eval's misbehaving stand-in
    why_code     text NOT NULL DEFAULT '',          -- "AI budget reached", "agent unavailable", ...
    tool         text NOT NULL CHECK (tool IN ('get_status', 'explain_error', 'start_task', 'stop_task')),
    args         jsonb NOT NULL,
    proposal_id  bigint REFERENCES dispatch_proposals (id),
    verdict      text NOT NULL,                     -- 'allowed' or the guard's rule code
    detail       text NOT NULL DEFAULT '',
    result       jsonb,                             -- the adapter's answer (machine text is untrusted)
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- An approved action that reached its machine successfully. At most once per proposal (rule G02).
CREATE TABLE dispatch_executions (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id  bigint NOT NULL UNIQUE REFERENCES dispatch_proposals (id),
    call_id      bigint NOT NULL REFERENCES dispatch_calls (id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER dispatch_runs_append_only BEFORE UPDATE OR DELETE ON dispatch_runs
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_proposals_append_only BEFORE UPDATE OR DELETE ON dispatch_proposals
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_approvals_append_only BEFORE UPDATE OR DELETE ON dispatch_approvals
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_calls_append_only BEFORE UPDATE OR DELETE ON dispatch_calls
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_executions_append_only BEFORE UPDATE OR DELETE ON dispatch_executions
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_runs_no_truncate BEFORE TRUNCATE ON dispatch_runs
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_proposals_no_truncate BEFORE TRUNCATE ON dispatch_proposals
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_approvals_no_truncate BEFORE TRUNCATE ON dispatch_approvals
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_calls_no_truncate BEFORE TRUNCATE ON dispatch_calls
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER dispatch_executions_no_truncate BEFORE TRUNCATE ON dispatch_executions
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();

GRANT SELECT, INSERT ON dispatch_runs, dispatch_proposals, dispatch_approvals, dispatch_calls,
    dispatch_executions TO brimline_app;
GRANT UPDATE (time_source, machine_seconds) ON tasks TO brimline_app;
