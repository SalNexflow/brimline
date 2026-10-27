-- M6: disruptions and re-planning.
--
-- A disruption is a planner's message and the typed events it was confirmed as. Once confirmed it
-- is pending until a plan that includes it is approved; only then do its effects become facts (downtimes,
-- material delays, rush flags, cancellations, lost prints), in the approval's transaction.

CREATE TABLE disruptions (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message      text NOT NULL,         -- the planner's words, exactly as typed ('' if entered by hand)
    received_at  timestamptz NOT NULL,  -- times in the message are read from this moment
    ai_call_id   bigint REFERENCES ai_calls (id),
    parsed       jsonb,                 -- the model's validated reply, kept as it came (null: by hand)
    events       jsonb NOT NULL,        -- the events the planner confirmed, with resolved times
    review       jsonb,                 -- what code could not settle when it read the message
    -- review: read by the model, waiting for the planner to confirm or correct the events;
    -- pending: confirmed, included in every plan until one that includes it is approved.
    status       text NOT NULL DEFAULT 'review'
                 CHECK (status IN ('review', 'pending', 'applied', 'dismissed')),
    created_by   bigint NOT NULL REFERENCES users (id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    decided_by   bigint REFERENCES users (id),
    decided_at   timestamptz,
    applied_in   bigint,                -- the schedule whose approval applied it
    CONSTRAINT decided_disruptions_say_who CHECK (
        (status IN ('review', 'pending')) = (decided_by IS NULL AND decided_at IS NULL)
    )
);

CREATE FUNCTION disruptions_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'disruptions are records and are never deleted';
    END IF;
    IF NEW.message IS DISTINCT FROM OLD.message OR NEW.parsed IS DISTINCT FROM OLD.parsed
       OR NEW.received_at IS DISTINCT FROM OLD.received_at OR NEW.ai_call_id IS DISTINCT FROM OLD.ai_call_id THEN
        RAISE EXCEPTION 'disruption %: what was reported cannot change', OLD.id;
    END IF;
    -- The planner may correct the events only while reviewing them.
    IF NEW.events IS DISTINCT FROM OLD.events AND OLD.status <> 'review' THEN
        RAISE EXCEPTION 'disruption % is %: its events cannot change', OLD.id, OLD.status;
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'review' AND NEW.status IN ('pending', 'dismissed'))
        OR (OLD.status = 'pending' AND NEW.status IN ('applied', 'dismissed'))
    ) THEN
        RAISE EXCEPTION 'disruption % cannot go from % to %', OLD.id, OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER disruptions_guard BEFORE UPDATE OR DELETE ON disruptions
    FOR EACH ROW EXECUTE FUNCTION disruptions_guard();

-- Facts written when a plan is approved.
CREATE TABLE machine_downtimes (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    machine_id     bigint NOT NULL REFERENCES machines (id),
    starts_at      timestamptz NOT NULL,
    ends_at        timestamptz,           -- null: until further notice (stays down past any horizon)
    disruption_id  bigint NOT NULL REFERENCES disruptions (id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_at IS NULL OR ends_at > starts_at)
);

CREATE TABLE material_delays (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id    bigint NOT NULL REFERENCES materials (id),
    available_at   timestamptz NOT NULL,
    disruption_id  bigint NOT NULL REFERENCES disruptions (id),
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- A running print's expected end, when a planner has said it will run over (print_overrun).
ALTER TABLE tasks ADD COLUMN expected_end timestamptz;

-- What a plan was made against and what it would change, for the review and for approval.
ALTER TABLE schedules
    ADD COLUMN previous_id bigint REFERENCES schedules (id),
    ADD COLUMN disruption_ids bigint[] NOT NULL DEFAULT '{}',
    ADD COLUMN effects jsonb NOT NULL DEFAULT '{}',   -- lost prints, cancellations, overruns
    ADD COLUMN diff jsonb,                            -- computed by code against previous_id
    ADD COLUMN summary jsonb,                         -- the AI summary (or the code's), from the diff only
    ADD COLUMN summary_ai_call_id bigint REFERENCES ai_calls (id);

-- The new columns are part of the saved version too: none of them may change after insert.
CREATE OR REPLACE FUNCTION schedules_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'schedules are versions and are never deleted';
    END IF;
    IF NEW.document IS DISTINCT FROM OLD.document
       OR NEW.fingerprint IS DISTINCT FROM OLD.fingerprint
       OR NEW.anchor IS DISTINCT FROM OLD.anchor
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.previous_id IS DISTINCT FROM OLD.previous_id
       OR NEW.disruption_ids IS DISTINCT FROM OLD.disruption_ids
       OR NEW.effects IS DISTINCT FROM OLD.effects
       OR NEW.diff IS DISTINCT FROM OLD.diff
       OR NEW.summary IS DISTINCT FROM OLD.summary
       OR NEW.summary_ai_call_id IS DISTINCT FROM OLD.summary_ai_call_id THEN
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

GRANT SELECT, INSERT, UPDATE ON disruptions TO brimline_app;
GRANT SELECT, INSERT ON machine_downtimes, material_delays TO brimline_app;
