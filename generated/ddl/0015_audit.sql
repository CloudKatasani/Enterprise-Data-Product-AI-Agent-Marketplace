-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- immutable audit events and publication snapshots

-- audit_event: Immutable record of anything touching access, publication or scores. 7-year retention.
CREATE TABLE audit_event (
  audit_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  event_name TEXT NOT NULL,
  actor_party_id TEXT REFERENCES party(party_id),
  on_behalf_of TEXT REFERENCES party(party_id),  -- Delegated identity: both identities are logged (section 19).
  asset_type TEXT,
  asset_id TEXT,
  purpose_code TEXT REFERENCES purpose_category(code),
  outcome TEXT NOT NULL,
  detail JSONB NOT NULL,
  policy_version_id TEXT REFERENCES policy_version(policy_version_id),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  retain_until TIMESTAMPTZ NOT NULL
);
CREATE INDEX audit_asset_idx ON audit_event (asset_type, asset_id, occurred_at DESC);
CREATE INDEX audit_actor_idx ON audit_event (actor_party_id, occurred_at DESC);
CREATE INDEX audit_event_name_idx ON audit_event (event_name, occurred_at DESC);
ALTER TABLE audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_event FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_event_tenant_isolation ON audit_event
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
-- rule 6: append-only. History is written, never rewritten.
REVOKE UPDATE, DELETE ON audit_event FROM app_role;
GRANT SELECT, INSERT ON audit_event TO app_role;

-- publication_snapshot: The exact bundle that reached the shelf, replayable for rollback and audit.
CREATE TABLE publication_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  version_ref TEXT NOT NULL,
  gate_results JSONB NOT NULL,
  bundle JSONB NOT NULL,  -- Pinned model, params, prompt hash, tool bindings, contract and KPI versions.
  published_by TEXT NOT NULL REFERENCES party(party_id),
  published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX publication_asset_idx ON publication_snapshot (asset_type, asset_id, published_at DESC);
ALTER TABLE publication_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE publication_snapshot FORCE ROW LEVEL SECURITY;
CREATE POLICY publication_snapshot_tenant_isolation ON publication_snapshot
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
-- rule 6: append-only. History is written, never rewritten.
REVOKE UPDATE, DELETE ON publication_snapshot FROM app_role;
GRANT SELECT, INSERT ON publication_snapshot TO app_role;
