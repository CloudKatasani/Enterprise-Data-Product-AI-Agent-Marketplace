-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- derived columns, search maintenance and append-only enforcement

-- sensitivity_derivation: I5 — data_product.sensitivity_tier is derived from columns, never written.
-- invariants: I5
-- SPEC-QUESTION: BUILD.md 6.2 writes derive_sensitivity as
--   SELECT COALESCE(MAX(t.rank_order), 1)::TEXT ...
-- which yields the rank number ('3'), while data_product.sensitivity_tier is
-- consumed everywhere else as a sensitivity_tier.code ('confidential') — for
-- example data_contract_version.max_sensitivity REFERENCES sensitivity_tier(code).
-- The narrower reading that keeps the value usable is implemented: the function
-- selects the code of the highest-ranked column classification, using exactly the
-- MAX(rank_order) selection rule written in the specification.
CREATE OR REPLACE FUNCTION derive_sensitivity(p_product_id TEXT) RETURNS TEXT AS $$
  SELECT t.code
  FROM data_product_column c
  JOIN sensitivity_tier t ON t.code = c.sensitivity_code
  WHERE c.product_id = p_product_id
  ORDER BY t.rank_order DESC
  LIMIT 1;
$$ LANGUAGE sql STABLE;

-- The lowest tier is the floor for a product that has no classified column yet.
CREATE OR REPLACE FUNCTION lowest_sensitivity_code() RETURNS TEXT AS $$
  SELECT code FROM sensitivity_tier ORDER BY rank_order ASC LIMIT 1;
$$ LANGUAGE sql STABLE;

-- Any value supplied by a writer is discarded and replaced with the derived one,
-- so there is no code path that can set sensitivity directly.
CREATE OR REPLACE FUNCTION data_product_derive_sensitivity() RETURNS TRIGGER AS $$
BEGIN
  NEW.sensitivity_tier :=
    COALESCE(derive_sensitivity(NEW.product_id), lowest_sensitivity_code());
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_product_sensitivity_derived
  BEFORE INSERT OR UPDATE ON data_product
  FOR EACH ROW EXECUTE FUNCTION data_product_derive_sensitivity();

-- Recompute whenever the column set or a classification changes.
CREATE OR REPLACE FUNCTION data_product_column_resensitise() RETURNS TRIGGER AS $$
DECLARE
  affected TEXT := COALESCE(NEW.product_id, OLD.product_id);
BEGIN
  UPDATE data_product
     SET sensitivity_tier = COALESCE(derive_sensitivity(affected), lowest_sensitivity_code())
   WHERE product_id = affected;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_product_column_resensitise
  AFTER INSERT OR UPDATE OR DELETE ON data_product_column
  FOR EACH ROW EXECUTE FUNCTION data_product_column_resensitise();

-- search_document_maintenance: Keep the lexical half of hybrid search in step with its source text.
CREATE OR REPLACE FUNCTION asset_search_document_vector() RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
      setweight(to_tsvector('english', coalesce(NEW.exact_name, '')), 'A')
   || setweight(to_tsvector('english', coalesce(NEW.body, '')), 'B');
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER asset_search_document_vector
  BEFORE INSERT OR UPDATE ON asset_search_document
  FOR EACH ROW EXECUTE FUNCTION asset_search_document_vector();

-- append_only_enforcement: Rule 6 — no code path issues an UPDATE or DELETE against a snapshot table.
-- The REVOKE grants stop a least-privileged application role. The trigger stops
-- everything else, including a superuser session and a migration written in a
-- hurry, so immutability does not depend on which role happens to be connected.
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION
    'table % is append-only; % is not permitted (BUILD.md rule 6)',
    TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER quality_score_snapshot_append_only
  BEFORE UPDATE OR DELETE ON quality_score_snapshot
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE TRIGGER publication_snapshot_append_only
  BEFORE UPDATE OR DELETE ON publication_snapshot
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE TRIGGER audit_event_append_only
  BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- entitlement_grant is history: a grant is ended by writing a revocation row and
-- stamping revoked_at / last_used_at / the two notification columns. Every other
-- column is frozen once written, and the row can never be deleted.
CREATE OR REPLACE FUNCTION entitlement_grant_history_only() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'entitlement_grant is append-only; DELETE is not permitted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF ROW(NEW.grant_id, NEW.request_id, NEW.principal_id, NEW.asset_type, NEW.asset_id,
         NEW.access_level, NEW.purpose_code, NEW.purpose_text, NEW.platform_role,
         NEW.oauth_scopes, NEW.granted_at, NEW.expires_at)
     IS DISTINCT FROM
     ROW(OLD.grant_id, OLD.request_id, OLD.principal_id, OLD.asset_type, OLD.asset_id,
         OLD.access_level, OLD.purpose_code, OLD.purpose_text, OLD.platform_role,
         OLD.oauth_scopes, OLD.granted_at, OLD.expires_at)
  THEN
    RAISE EXCEPTION
      'entitlement_grant terms are immutable; revoke the grant and issue a new one'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
    RAISE EXCEPTION 'entitlement_grant revocation is final' USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER entitlement_grant_history_only
  BEFORE UPDATE OR DELETE ON entitlement_grant
  FOR EACH ROW EXECUTE FUNCTION entitlement_grant_history_only();
