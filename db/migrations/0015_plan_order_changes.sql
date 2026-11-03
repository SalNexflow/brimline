-- Whether purchase orders changed after a plan was made (the materials page's "Plan again" notice).
-- Comparing times mixed two clocks: a plan's created_at is the shop's "as of" time (pinned by DEMO_CLOCK),
-- a purchase order's is the real time (DEFECT_LOG #111). The audit log is append-only (a trigger enforces
-- it), so the number of purchase-order entries in it only grows: a plan keeps the count it had seen when it
-- read its inputs, and orders changed since then exactly when the count is higher now.
ALTER TABLE schedules
    ADD COLUMN order_changes_seen integer NOT NULL DEFAULT 0 CHECK (order_changes_seen >= 0);
