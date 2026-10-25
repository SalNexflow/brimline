-- Quote requests, AI-drafted quotes, and the record of every model call (docs/DECISIONS.md D36-D40).

CREATE FUNCTION reject_change_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END;
$$;

-- Every model call, whatever its outcome. Costs are in micro-USD from config/models.toml.
CREATE TABLE ai_calls (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purpose            text NOT NULL,                 -- e.g. 'quote_extract'
    mode               text NOT NULL CHECK (mode IN ('live', 'fake', 'off')),
    model              text,
    prompt_version     text NOT NULL,
    outcome            text NOT NULL CHECK (outcome IN ('valid', 'repaired', 'invalid', 'refused', 'error', 'skipped')),
    attempts           smallint NOT NULL CHECK (attempts BETWEEN 0 AND 2),
    input_tokens       integer NOT NULL DEFAULT 0,
    output_tokens      integer NOT NULL DEFAULT 0,
    cache_read_tokens  integer NOT NULL DEFAULT 0,
    cache_write_tokens integer NOT NULL DEFAULT 0,
    cost_micro_usd     bigint NOT NULL DEFAULT 0,
    latency_ms         integer NOT NULL DEFAULT 0,
    error              text,
    created_by         bigint REFERENCES users (id),
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- The customer's words, exactly as received. Never edited.
CREATE TABLE quote_requests (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id  bigint NOT NULL REFERENCES customers (id),
    submitted_by bigint NOT NULL REFERENCES users (id),
    message      text NOT NULL CHECK (length(message) BETWEEN 1 AND 10000),
    received_at  timestamptz NOT NULL DEFAULT now()
);

CREATE SEQUENCE quote_number_seq;

CREATE TABLE quotes (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    quote_number       text NOT NULL UNIQUE DEFAULT ('Q-' || lpad(nextval('quote_number_seq')::text, 4, '0')),
    request_id         bigint NOT NULL UNIQUE REFERENCES quote_requests (id),
    customer_id        bigint NOT NULL REFERENCES customers (id),
    status             text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'rejected')),
    ai_call_id         bigint REFERENCES ai_calls (id),
    ai_draft           jsonb,                          -- the validated model output, kept as it came
    due_rule           jsonb,                          -- the rule the model picked; the date is code's
    due_date           date,
    rush               boolean NOT NULL DEFAULT false,
    notes              text NOT NULL DEFAULT '',
    missing            jsonb NOT NULL DEFAULT '[]',    -- computed by code; approval needs it empty
    questions          jsonb NOT NULL DEFAULT '[]',
    requests_for_staff jsonb NOT NULL DEFAULT '[]',
    price_rule_set_id  bigint REFERENCES price_rule_sets (id),
    price              jsonb,                          -- breakdown, or what is missing to price it
    total_cents        integer CHECK (total_cents >= 0),
    decided_by         bigint REFERENCES users (id),
    decided_at         timestamptz,
    order_id           bigint UNIQUE REFERENCES orders (id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT approved_quotes_are_complete CHECK (
        status <> 'approved'
        OR (total_cents IS NOT NULL AND order_id IS NOT NULL AND decided_by IS NOT NULL AND missing = '[]')
    )
);
CREATE INDEX quotes_customer_id_idx ON quotes (customer_id);

CREATE TABLE quote_lines (
    quote_id           bigint NOT NULL REFERENCES quotes (id),
    line_no            integer NOT NULL CHECK (line_no > 0),
    part_name          text NOT NULL,
    quantity           integer CHECK (quantity > 0),
    material_id        bigint REFERENCES materials (id),
    material_as_written text,
    grams_per_part     integer CHECK (grams_per_part > 0),
    minutes_per_part   integer CHECK (minutes_per_part > 0),
    post_processing    text[] NOT NULL DEFAULT '{}'
                       CHECK (post_processing <@ ARRAY['sanding', 'painting', 'assembly']),
    sources            jsonb NOT NULL DEFAULT '{}',   -- per field: 'ai', 'staff' or 'missing'
    uncertain          text[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (quote_id, line_no)
);

-- Append-only records.
CREATE TRIGGER ai_calls_append_only BEFORE UPDATE OR DELETE ON ai_calls
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER ai_calls_no_truncate BEFORE TRUNCATE ON ai_calls
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER quote_requests_append_only BEFORE UPDATE OR DELETE ON quote_requests
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER quote_requests_no_truncate BEFORE TRUNCATE ON quote_requests
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();

-- A decided quote (approved or rejected) and its lines never change again.
CREATE FUNCTION quotes_frozen_once_decided() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_status text;
BEGIN
    IF TG_TABLE_NAME = 'quotes' THEN
        IF TG_OP = 'DELETE' OR OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'quote % is % and can no longer change', OLD.quote_number, OLD.status;
        END IF;
        RETURN NEW;
    END IF;
    SELECT status INTO current_status FROM quotes WHERE id = COALESCE(NEW.quote_id, OLD.quote_id);
    IF current_status <> 'draft' THEN
        RAISE EXCEPTION 'lines of a % quote can no longer change', current_status;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER quotes_frozen BEFORE UPDATE OR DELETE ON quotes
    FOR EACH ROW EXECUTE FUNCTION quotes_frozen_once_decided();
CREATE TRIGGER quote_lines_frozen BEFORE INSERT OR UPDATE OR DELETE ON quote_lines
    FOR EACH ROW EXECUTE FUNCTION quotes_frozen_once_decided();

-- Grants. The app may record calls and requests but never change them; it may edit a draft
-- quote's working fields, but not which request or customer it belongs to, nor the AI draft.
GRANT SELECT ON ai_calls, quote_requests, quotes, quote_lines TO brimline_app;
GRANT INSERT (purpose, mode, model, prompt_version, outcome, attempts, input_tokens, output_tokens,
              cache_read_tokens, cache_write_tokens, cost_micro_usd, latency_ms, error, created_by)
    ON ai_calls TO brimline_app;
GRANT INSERT (customer_id, submitted_by, message, received_at) ON quote_requests TO brimline_app;
GRANT INSERT (request_id, customer_id, ai_call_id, ai_draft, due_rule, due_date, rush, notes, missing,
              questions, requests_for_staff, price_rule_set_id, price, total_cents)
    ON quotes TO brimline_app;
GRANT UPDATE (status, due_date, rush, notes, missing, price_rule_set_id, price, total_cents,
              decided_by, decided_at, order_id, updated_at)
    ON quotes TO brimline_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON quote_lines TO brimline_app;
GRANT USAGE ON SEQUENCE quote_number_seq TO brimline_app;
