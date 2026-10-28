-- M11: the hosted demo. Model calls record which visitor made them (a keyed hash, never an
-- address) so the per-visitor limit can be counted, and replayed or recorded calls say so.
ALTER TABLE ai_calls DROP CONSTRAINT ai_calls_mode_check;
ALTER TABLE ai_calls ADD CONSTRAINT ai_calls_mode_check
    CHECK (mode IN ('live', 'fake', 'off', 'record', 'replay'));
ALTER TABLE ai_calls ADD COLUMN visitor text CHECK (visitor ~ '^[0-9a-f]{16}$');
CREATE INDEX ai_calls_created_at ON ai_calls (created_at);
CREATE INDEX ai_calls_visitor ON ai_calls (visitor, created_at) WHERE visitor IS NOT NULL;
GRANT INSERT (visitor) ON ai_calls TO brimline_app;
