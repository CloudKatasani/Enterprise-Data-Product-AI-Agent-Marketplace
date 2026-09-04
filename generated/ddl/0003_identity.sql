-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- parties, org units and role assignments

-- org_unit: Organisational tree used for approval routing and adoption breadth.
CREATE TABLE org_unit (
  org_unit_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  name TEXT NOT NULL,
  parent_org_unit_id TEXT REFERENCES org_unit(org_unit_id),
  cost_centre TEXT
);
ALTER TABLE org_unit ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_unit FORCE ROW LEVEL SECURITY;
CREATE POLICY org_unit_tenant_isolation ON org_unit
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON org_unit TO app_role;
GRANT UPDATE, DELETE ON org_unit TO app_role;

-- party: A person, team, service principal or agent identity. Agents hold their own.
CREATE TABLE party (
  party_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  party_type TEXT NOT NULL CHECK (party_type IN ('person','team','service','agent')),
  display_name TEXT NOT NULL,
  email TEXT,
  org_unit_id TEXT REFERENCES org_unit(org_unit_id),
  external_subject TEXT,  -- OIDC subject or SCIM external id; never a password.
  mfa_enforced BOOLEAN NOT NULL DEFAULT false,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX party_external_subject_key ON party (external_subject) WHERE external_subject IS NOT NULL;
ALTER TABLE party ENABLE ROW LEVEL SECURITY;
ALTER TABLE party FORCE ROW LEVEL SECURITY;
CREATE POLICY party_tenant_isolation ON party
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON party TO app_role;
GRANT UPDATE, DELETE ON party TO app_role;

-- role_assignment: Marketplace role held by a party. MFA is enforced for the privileged four.
CREATE TABLE role_assignment (
  assignment_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  party_id TEXT NOT NULL REFERENCES party(party_id),
  role_code TEXT NOT NULL CHECK (role_code IN ('consumer','owner','steward','architect','security','privacy','administrator')),
  scope_type TEXT NOT NULL CHECK (scope_type IN ('tenant','domain','product','agent')),
  scope_id TEXT,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  granted_by TEXT NOT NULL REFERENCES party(party_id),
  UNIQUE (party_id, role_code, scope_type, scope_id)
);
ALTER TABLE role_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_assignment FORCE ROW LEVEL SECURITY;
CREATE POLICY role_assignment_tenant_isolation ON role_assignment
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON role_assignment TO app_role;
GRANT UPDATE, DELETE ON role_assignment TO app_role;
