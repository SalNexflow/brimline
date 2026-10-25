-- Idempotent writes. A key is scoped to (user, endpoint): two users, or two endpoints, may use
-- the same key without ever seeing each other's response.
--
-- The request inserts its key row first, inside the same transaction as the write. A concurrent
-- request with the same key blocks on the primary key until the first commits, then reads the
-- stored response. So exactly one write happens, with no extra locking code.

CREATE TABLE idempotency_keys (
    user_id         bigint NOT NULL REFERENCES users (id),
    endpoint        text NOT NULL,                  -- e.g. 'POST /orders'
    key             text NOT NULL CHECK (length(key) BETWEEN 8 AND 200),
    request_hash    text NOT NULL,                  -- sha256 of the canonical request body
    response_status smallint,                       -- filled before commit, so never seen empty
    response_body   jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, endpoint, key)
);

GRANT SELECT, INSERT, UPDATE ON idempotency_keys TO brimline_app;
