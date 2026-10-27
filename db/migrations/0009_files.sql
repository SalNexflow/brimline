-- M7: uploaded model files, the code-made check report, staff overrides of warnings, and the
-- optional AI advice kept apart from the checks.
--
-- A file belongs to one quote line (uploaded with a quote) or to one job (attached on the
-- board). Rows never change: a new upload is a new row, and the latest one for a line or job is
-- the one that counts. The report and the planning values are written by code from the file.

CREATE SEQUENCE file_number_seq;

CREATE TABLE files (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_number  text NOT NULL UNIQUE DEFAULT ('F-' || lpad(nextval('file_number_seq')::text, 4, '0')),
    customer_id  bigint NOT NULL REFERENCES customers (id),
    quote_id     bigint REFERENCES quotes (id),
    quote_line   integer CHECK (quote_line > 0),
    job_id       bigint REFERENCES jobs (id),
    filename     text NOT NULL CHECK (length(filename) BETWEEN 1 AND 200),
    unit         text NOT NULL,          -- what STL numbers were read as (staff choose; 3MF says)
    material_id  bigint REFERENCES materials (id),  -- the process the checks used
    content      bytea NOT NULL,
    size_bytes   integer NOT NULL CHECK (size_bytes > 0),
    sha256       text NOT NULL,
    report       jsonb NOT NULL,         -- every check: pass, warn, fail or skip, with a reason
    overall      text NOT NULL CHECK (overall IN ('pass', 'warn', 'fail')),
    planning     jsonb NOT NULL,         -- part size, grams, minutes computed from the file, or why not
    uploaded_by  bigint NOT NULL REFERENCES users (id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (quote_id IS NOT NULL AND quote_line IS NOT NULL AND job_id IS NULL)
        OR (quote_id IS NULL AND quote_line IS NULL AND job_id IS NOT NULL)
    )
);
CREATE INDEX files_quote_line ON files (quote_id, quote_line, id);
CREATE INDEX files_job ON files (job_id, id);

-- Staff accept a warning with a reason (never a fail). Logged here and in the audit log.
CREATE TABLE file_overrides (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id        bigint NOT NULL REFERENCES files (id),
    check_name     text NOT NULL,
    reason         text NOT NULL CHECK (length(reason) BETWEEN 3 AND 500),
    overridden_by  bigint NOT NULL REFERENCES users (id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (file_id, check_name)
);

-- Optional vision advice on a rendered preview. Advice only: nothing reads it to decide a check.
CREATE TABLE file_advice (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    file_id     bigint NOT NULL REFERENCES files (id),
    ai_call_id  bigint REFERENCES ai_calls (id),
    advice      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER files_append_only BEFORE UPDATE OR DELETE ON files
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER files_no_truncate BEFORE TRUNCATE ON files
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER file_overrides_append_only BEFORE UPDATE OR DELETE ON file_overrides
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER file_overrides_no_truncate BEFORE TRUNCATE ON file_overrides
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER file_advice_append_only BEFORE UPDATE OR DELETE ON file_advice
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER file_advice_no_truncate BEFORE TRUNCATE ON file_advice
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();

-- Where a quote line's part size came from flows through quote_lines.sources ('file').
ALTER TABLE quote_lines
    ADD COLUMN part_x_mm integer CHECK (part_x_mm > 0),
    ADD COLUMN part_y_mm integer CHECK (part_y_mm > 0),
    ADD COLUMN part_z_mm integer CHECK (part_z_mm > 0);

GRANT SELECT, INSERT ON files, file_overrides, file_advice TO brimline_app;
GRANT USAGE ON SEQUENCE file_number_seq TO brimline_app;

-- Which file set a job's part size, so a later, corrected file may replace it (a size from the
-- seed or from a person is never overwritten by a file).
ALTER TABLE jobs ADD COLUMN part_size_file_id bigint REFERENCES files (id);
