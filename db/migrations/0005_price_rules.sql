-- Price rules: dated, versioned, insert-only (docs/DECISIONS.md D35).
-- "Editing" prices means adding a new version with an effective date. A version and its rates
-- can never change afterwards, so every quote that names a version can always be explained.

CREATE TABLE price_rule_sets (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    effective_from          date NOT NULL,
    setup_cents             integer NOT NULL CHECK (setup_cents >= 0),
    rush_multiplier_percent integer NOT NULL CHECK (rush_multiplier_percent BETWEEN 100 AND 500),
    note                    text NOT NULL DEFAULT '',
    created_by              bigint REFERENCES users (id),  -- null only for the seeded version
    created_at              timestamptz NOT NULL DEFAULT now(),
    -- The transaction that created the version: rates may only be added in that same one.
    created_txid            xid8 NOT NULL DEFAULT pg_current_xact_id()
);
CREATE INDEX price_rule_sets_effective_idx ON price_rule_sets (effective_from DESC, id DESC);

CREATE TABLE price_material_rates (
    rule_set_id    bigint NOT NULL REFERENCES price_rule_sets (id),
    material_id    bigint NOT NULL REFERENCES materials (id),
    cents_per_gram integer NOT NULL CHECK (cents_per_gram >= 0),
    PRIMARY KEY (rule_set_id, material_id)
);

CREATE TABLE price_machine_rates (
    rule_set_id      bigint NOT NULL REFERENCES price_rule_sets (id),
    process          text NOT NULL CHECK (process IN ('fdm', 'resin', 'cnc')),
    cents_per_minute integer NOT NULL CHECK (cents_per_minute >= 0),
    PRIMARY KEY (rule_set_id, process)
);

CREATE TABLE price_post_process_rates (
    rule_set_id    bigint NOT NULL REFERENCES price_rule_sets (id),
    kind           text NOT NULL CHECK (kind IN ('sanding', 'painting', 'assembly')),
    cents_per_part integer NOT NULL CHECK (cents_per_part >= 0),
    PRIMARY KEY (rule_set_id, kind)
);

CREATE FUNCTION price_rules_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'price rules are versioned: % on % is not allowed; add a new version', TG_OP, TG_TABLE_NAME;
END;
$$;

CREATE FUNCTION price_rates_only_with_their_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT created_txid FROM price_rule_sets WHERE id = NEW.rule_set_id) <> pg_current_xact_id() THEN
        RAISE EXCEPTION 'rates can only be added in the transaction that created their version';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['price_rule_sets', 'price_material_rates', 'price_machine_rates', 'price_post_process_rates']
    LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION price_rules_reject_change()', t || '_immutable', t);
        EXECUTE format('CREATE TRIGGER %I BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION price_rules_reject_change()', t || '_no_truncate', t);
        IF t <> 'price_rule_sets' THEN
            EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION price_rates_only_with_their_version()', t || '_same_transaction', t);
        END IF;
    END LOOP;
END;
$$;

-- Staff add versions through the engine; nobody changes or removes one.
GRANT SELECT ON price_rule_sets, price_material_rates, price_machine_rates, price_post_process_rates TO brimline_app;
GRANT INSERT (effective_from, setup_cents, rush_multiplier_percent, note, created_by) ON price_rule_sets TO brimline_app;
GRANT INSERT ON price_material_rates, price_machine_rates, price_post_process_rates TO brimline_app;
