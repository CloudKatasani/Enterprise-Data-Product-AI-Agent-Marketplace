-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: d1f98ff85cc2f0960625524186ad283cf6aa6b90484a80f01f2f65faefd2ca34  generated_at: 2026-09-04T08:33:00+00:00

-- grants, scopes, purpose bindings, revocations and drift

-- entitlement_grant: The record of what was granted. Effective permission lives in the platform, not here.
CREATE TABLE entitlement_grant (
  grant_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  request_id TEXT NOT NULL REFERENCES request(request_id),
  principal_id TEXT NOT NULL REFERENCES party(party_id),
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  access_level TEXT NOT NULL CHECK (access_level IN ('read_metadata','read_data','read_data_pii','agent_invoke','write_back')),
  purpose_code TEXT NOT NULL REFERENCES purpose_category(code),
  purpose_text TEXT NOT NULL,
  platform_role TEXT NOT NULL,  -- MKT_<PRODUCT>_<LEVEL>
  oauth_scopes TEXT[] NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  revocation_reason TEXT,
  last_used_at TIMESTAMPTZ,
  dormant_flagged_at TIMESTAMPTZ,
  renewal_notified_at TIMESTAMPTZ
);
CREATE INDEX entitlement_active_idx ON entitlement_grant (principal_id, asset_id) WHERE revoked_at IS NULL;
CREATE INDEX entitlement_expiry_idx ON entitlement_grant (expires_at) WHERE revoked_at IS NULL;
ALTER TABLE entitlement_grant ENABLE ROW LEVEL SECURITY;
ALTER TABLE entitlement_grant FORCE ROW LEVEL SECURITY;
CREATE POLICY entitlement_grant_tenant_isolation ON entitlement_grant
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
-- rule 6: append-only. History is written, never rewritten.
REVOKE DELETE ON entitlement_grant FROM app_role;
GRANT SELECT, INSERT ON entitlement_grant TO app_role;
GRANT UPDATE ON entitlement_grant TO app_role;

-- grant_scope: Column-level narrowing of a grant. A grant is never wider than its scope rows.
CREATE TABLE grant_scope (
  scope_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  grant_id TEXT NOT NULL REFERENCES entitlement_grant(grant_id),
  scope_kind TEXT NOT NULL CHECK (scope_kind IN ('columns','rows','tools')),
  expression TEXT NOT NULL,
  applied_in_platform BOOLEAN NOT NULL DEFAULT false
);
ALTER TABLE grant_scope ENABLE ROW LEVEL SECURITY;
ALTER TABLE grant_scope FORCE ROW LEVEL SECURITY;
CREATE POLICY grant_scope_tenant_isolation ON grant_scope
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON grant_scope TO app_role;
GRANT UPDATE, DELETE ON grant_scope TO app_role;

-- purpose_binding: The declared purpose attached to a grant and logged with every query under it.
CREATE TABLE purpose_binding (
  binding_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  grant_id TEXT NOT NULL REFERENCES entitlement_grant(grant_id),
  purpose_code TEXT NOT NULL REFERENCES purpose_category(code),
  purpose_text TEXT NOT NULL CHECK (length(trim(purpose_text)) > 5),
  bound_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  bound_by TEXT NOT NULL REFERENCES party(party_id),
  UNIQUE (grant_id, purpose_code)
);
ALTER TABLE purpose_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE purpose_binding FORCE ROW LEVEL SECURITY;
CREATE POLICY purpose_binding_tenant_isolation ON purpose_binding
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON purpose_binding TO app_role;
GRANT UPDATE, DELETE ON purpose_binding TO app_role;

-- revocation: Why a grant ended: expiry, self-revoke, admin revoke, dormancy or drift.
CREATE TABLE revocation (
  revocation_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  grant_id TEXT NOT NULL REFERENCES entitlement_grant(grant_id),
  reason_code TEXT NOT NULL CHECK (reason_code IN ('expired','self_revoked','admin_revoked','dormant','policy_change','drift_reconciliation','offboarded')),
  reason_text TEXT NOT NULL,
  actor_party_id TEXT REFERENCES party(party_id),
  platform_confirmed BOOLEAN NOT NULL DEFAULT false,
  revoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE revocation ENABLE ROW LEVEL SECURITY;
ALTER TABLE revocation FORCE ROW LEVEL SECURITY;
CREATE POLICY revocation_tenant_isolation ON revocation
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON revocation TO app_role;
GRANT UPDATE, DELETE ON revocation TO app_role;

-- entitlement_drift: Nightly reconciliation finding: register says one thing, platform says another.
CREATE TABLE entitlement_drift (
  drift_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  platform TEXT NOT NULL,
  principal_ref TEXT NOT NULL,
  asset_ref TEXT NOT NULL,
  drift_type TEXT NOT NULL CHECK (drift_type IN ('missing_in_platform','extra_in_platform','level_mismatch','expired_but_present')),
  register_state JSONB NOT NULL,
  platform_state JSONB NOT NULL,
  incident_id TEXT REFERENCES incident(incident_id),
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
ALTER TABLE entitlement_drift ENABLE ROW LEVEL SECURITY;
ALTER TABLE entitlement_drift FORCE ROW LEVEL SECURITY;
CREATE POLICY entitlement_drift_tenant_isolation ON entitlement_drift
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON entitlement_drift TO app_role;
GRANT UPDATE, DELETE ON entitlement_drift TO app_role;
