-- M9: material stock, deliveries and shortages.
--
-- Grams per part a person entered for a job (the order form). When it is empty, planning falls
-- back to the job's latest passing file, then to the approved quote's line, and says which it
-- used (docs/DECISIONS.md). Existing rows stay empty: nothing to backfill, nothing to block.
ALTER TABLE jobs ADD COLUMN grams_per_part integer CHECK (grams_per_part > 0 AND grams_per_part <= 100000);

-- An order a person placed with a supplier outside Brimline, recorded so planning can count the
-- delivery. Brimline never orders anything; it only suggests (purchase suggestions are computed,
-- never stored). Status moves open -> received or open -> cancelled, once.
CREATE SEQUENCE purchase_order_number_seq;
CREATE TABLE purchase_orders (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_number    text NOT NULL UNIQUE DEFAULT ('PO-' || lpad(nextval('purchase_order_number_seq')::text, 4, '0')),
    material_id  bigint NOT NULL REFERENCES materials (id),
    grams        integer NOT NULL CHECK (grams > 0 AND grams <= 1000000),
    supplier     text NOT NULL CHECK (char_length(supplier) BETWEEN 1 AND 100),
    expected_at  timestamptz NOT NULL,
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'received', 'cancelled')),
    received_at  timestamptz,
    cancelled_at timestamptz,
    recorded_by  bigint NOT NULL REFERENCES users (id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'received') = (received_at IS NOT NULL)),
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);
CREATE INDEX purchase_orders_open_idx ON purchase_orders (material_id) WHERE status = 'open';

-- Every change to stock, append-only; stock.on_hand_g is the running balance, changed in the
-- same transaction. A print takes its grams when its machine task is done or failed (the
-- recorded grams, or the assumed ones, as in M10). When the record shows less than a print
-- used, the balance stops at 0 and the row says how much was missing (a stock count is due).
CREATE TABLE stock_movements (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id       bigint NOT NULL REFERENCES materials (id),
    grams_delta       integer NOT NULL,
    reason            text NOT NULL CHECK (reason IN ('delivery', 'print')),
    purchase_order_id bigint REFERENCES purchase_orders (id),
    task_id           bigint UNIQUE REFERENCES tasks (id),  -- a print takes its grams once
    missing_g         integer NOT NULL DEFAULT 0 CHECK (missing_g >= 0),
    grams_assumed     boolean NOT NULL DEFAULT false,
    recorded_by       bigint REFERENCES users (id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK ((reason = 'delivery') = (purchase_order_id IS NOT NULL)),
    CHECK ((reason = 'print') = (task_id IS NOT NULL)),
    CHECK ((reason = 'delivery' AND grams_delta > 0) OR (reason = 'print' AND grams_delta <= 0))
);
CREATE INDEX stock_movements_material_idx ON stock_movements (material_id, id);
CREATE TRIGGER stock_movements_append_only BEFORE UPDATE OR DELETE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION reject_change_append_only();
CREATE TRIGGER stock_movements_no_truncate BEFORE TRUNCATE ON stock_movements
    FOR EACH STATEMENT EXECUTE FUNCTION reject_change_append_only();

GRANT SELECT, INSERT ON purchase_orders, stock_movements TO brimline_app;
GRANT UPDATE (status, received_at, cancelled_at) ON purchase_orders TO brimline_app;
GRANT USAGE ON SEQUENCE purchase_order_number_seq TO brimline_app;
GRANT UPDATE (on_hand_g, updated_at) ON stock TO brimline_app;
GRANT UPDATE (grams_per_part) ON jobs TO brimline_app;
