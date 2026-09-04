-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- reference taxonomies and tenancy

-- tenant: A deployment boundary. Every tenant-scoped row names one.
CREATE TABLE tenant (
  tenant_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  deployment_mode TEXT NOT NULL CHECK (deployment_mode IN ('multi_tenant','single_tenant')),
  residency_regions TEXT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT ON tenant TO app_role;
GRANT UPDATE, DELETE ON tenant TO app_role;

-- industry: Industry taxonomy. Seeded from manifests/taxonomies/industry.yaml.
CREATE TABLE industry (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  sort_order INT NOT NULL
);
GRANT SELECT, INSERT ON industry TO app_role;
GRANT UPDATE, DELETE ON industry TO app_role;

-- business_domain: Business domain taxonomy (customer, network, risk, supply chain, ...).
CREATE TABLE business_domain (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  sort_order INT NOT NULL
);
GRANT SELECT, INSERT ON business_domain TO app_role;
GRANT UPDATE, DELETE ON business_domain TO app_role;

-- product_archetype: Product archetype; drives the quality rubric's archetype overrides.
CREATE TABLE product_archetype (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  sort_order INT NOT NULL
);
GRANT SELECT, INSERT ON product_archetype TO app_role;
GRANT UPDATE, DELETE ON product_archetype TO app_role;

-- sensitivity_tier: Sensitivity ladder. rank_order is what derive_sensitivity maximises (I5).
CREATE TABLE sensitivity_tier (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  rank_order INT NOT NULL UNIQUE,
  requires_purpose BOOLEAN NOT NULL,
  description TEXT NOT NULL
);
GRANT SELECT, INSERT ON sensitivity_tier TO app_role;
GRANT UPDATE, DELETE ON sensitivity_tier TO app_role;

-- purpose_category: Permitted purposes a grant may be bound to. Purpose is mandatory above Internal.
CREATE TABLE purpose_category (
  code TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  requires_free_text BOOLEAN NOT NULL,
  sort_order INT NOT NULL
);
GRANT SELECT, INSERT ON purpose_category TO app_role;
GRANT UPDATE, DELETE ON purpose_category TO app_role;

-- source_system: Upstream system of record. Shared sources are what the data mesh links on.
CREATE TABLE source_system (
  source_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  owner_team TEXT NOT NULL,
  criticality TEXT NOT NULL CHECK (criticality IN ('tier1','tier2','tier3')),
  description TEXT NOT NULL
);
ALTER TABLE source_system ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_system FORCE ROW LEVEL SECURITY;
CREATE POLICY source_system_tenant_isolation ON source_system
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON source_system TO app_role;
GRANT UPDATE, DELETE ON source_system TO app_role;
