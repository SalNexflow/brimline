-- Whether purchase orders changed after a plan was made (the materials page's "Plan again" notice).
-- Comparing times mixed two clocks: a plan's created_at is the shop's "as of" time (pinned by DEMO_CLOCK),
-- a purchase order's is the real time (DEFECT_LOG #111). The audit log is append-only (a trigger enforces
-- it), so the number of purchase-order entries in it only grows: a plan keeps the count it had seen when it
-- read its inputs, and orders changed since then exactly when the count is higher now.
ALTER TABLE schedules
    ADD COLUMN order_changes_seen integer NOT NULL DEFAULT 0 CHECK (order_changes_seen >= 0);

-- Plans that exist already are taken as up to date with today's orders; with 0 every one would say
-- "Plan again" on a database that has any purchase-order history (review of DEFECT_LOG #111, #112).
UPDATE schedules SET order_changes_seen = (
    SELECT count(*) FROM audit_log
    WHERE action IN ('purchase_order.record', 'purchase_order.receive', 'purchase_order.cancel')
);
