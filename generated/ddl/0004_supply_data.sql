-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- data products, versions, columns, contracts and endpoints

-- data_product: A governed, contracted, owned dataset published for consumption.
-- invariants: I5, I7
CREATE TABLE data_product (
  product_id TEXT PRIMARY KEY,  -- DP-<IND>-<NNN>
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  name TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK (length(purpose) BETWEEN 20 AND 400),
  industry_code TEXT NOT NULL REFERENCES industry(code),
  domain_code TEXT NOT NULL REFERENCES business_domain(code),
  archetype_code TEXT NOT NULL REFERENCES product_archetype(code),
  sensitivity_tier TEXT NOT NULL,  -- I5: DERIVED from columns by trigger; never written directly.
  certification TEXT NOT NULL CHECK (certification IN ('certified','published','beta','deprecated')),
  owner_party_id TEXT NOT NULL REFERENCES party(party_id),
  current_version TEXT NOT NULL,
  grain TEXT NOT NULL,
  history_months INT NOT NULL,
  known_limitations TEXT NOT NULL CHECK (length(trim(known_limitations)) > 10 AND lower(trim(known_limitations)) NOT IN ('none','n/a','tbd')),  -- I7: a limitation section that says 'none' is not a limitation section.
  tier TEXT NOT NULL CHECK (tier IN ('tier1','tier2','tier3')),  -- Tier weighting for estate scoring (15.1).
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX data_product_taxonomy_idx ON data_product (industry_code, domain_code);
CREATE INDEX data_product_certification_idx ON data_product (certification);
CREATE INDEX data_product_owner_idx ON data_product (owner_party_id);
ALTER TABLE data_product ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_product FORCE ROW LEVEL SECURITY;
CREATE POLICY data_product_tenant_isolation ON data_product
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON data_product TO app_role;
GRANT UPDATE, DELETE ON data_product TO app_role;

-- data_product_version: A published version of a product. Publication is snapshotted, never mutated.
CREATE TABLE data_product_version (
  product_version_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  product_id TEXT NOT NULL REFERENCES data_product(product_id),
  semver TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','published','deprecated','retired')),
  change_summary TEXT NOT NULL,
  schema_stability TEXT NOT NULL CHECK (schema_stability IN ('additive_only','breaking_allowed','frozen')),
  published_at TIMESTAMPTZ,
  published_by TEXT REFERENCES party(party_id),
  deprecated_at TIMESTAMPTZ,
  UNIQUE (product_id, semver)
);
ALTER TABLE data_product_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_product_version FORCE ROW LEVEL SECURITY;
CREATE POLICY data_product_version_tenant_isolation ON data_product_version
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON data_product_version TO app_role;
GRANT UPDATE, DELETE ON data_product_version TO app_role;

-- data_product_column: Column-level metadata and classification. Sensitivity derives from here (I5).
CREATE TABLE data_product_column (
  column_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  product_id TEXT NOT NULL REFERENCES data_product(product_id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  business_name TEXT NOT NULL,
  data_type TEXT NOT NULL,
  nullable BOOLEAN NOT NULL,
  classification TEXT[] NOT NULL DEFAULT '{}',  -- pii, phi, pci, identifier, financial, ...
  sensitivity_code TEXT NOT NULL REFERENCES sensitivity_tier(code),
  description TEXT NOT NULL,
  masking_policy TEXT,
  ordinal INT NOT NULL,
  UNIQUE (product_id, name)
);
CREATE INDEX data_product_column_order_idx ON data_product_column (product_id, ordinal);
ALTER TABLE data_product_column ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_product_column FORCE ROW LEVEL SECURITY;
CREATE POLICY data_product_column_tenant_isolation ON data_product_column
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON data_product_column TO app_role;
GRANT UPDATE, DELETE ON data_product_column TO app_role;

-- data_contract_version: The enforceable promise a product makes. Conformance is measured against it.
CREATE TABLE data_contract_version (
  contract_version_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  product_id TEXT NOT NULL REFERENCES data_product(product_id),
  semver TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','active','superseded')),
  schema_stability TEXT NOT NULL,
  deprecation_notice_days INT NOT NULL,
  minimum_parallel_run_days INT NOT NULL,
  support_hours TEXT NOT NULL,
  p1_response_minutes INT NOT NULL,
  on_call TEXT NOT NULL,
  max_sensitivity TEXT NOT NULL REFERENCES sensitivity_tier(code),
  contains_pii BOOLEAN NOT NULL,
  residency TEXT[] NOT NULL DEFAULT '{}',
  consumer_obligations TEXT[] NOT NULL DEFAULT '{}',
  breach_process TEXT NOT NULL,
  effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (product_id, semver)
);
ALTER TABLE data_contract_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_contract_version FORCE ROW LEVEL SECURITY;
CREATE POLICY data_contract_version_tenant_isolation ON data_contract_version
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON data_contract_version TO app_role;
GRANT UPDATE, DELETE ON data_contract_version TO app_role;

-- contract_guarantee: One measurable guarantee of a contract: freshness, availability, completeness, accuracy.
CREATE TABLE contract_guarantee (
  guarantee_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  contract_version_id TEXT NOT NULL REFERENCES data_contract_version(contract_version_id) ON DELETE CASCADE,
  dimension TEXT NOT NULL CHECK (dimension IN ('freshness','availability','completeness','accuracy')),
  target_text TEXT NOT NULL,
  target_numeric NUMERIC(12,4),
  unit TEXT NOT NULL,
  measurement_window TEXT NOT NULL,
  measured_at_grain TEXT NOT NULL,
  reference_system TEXT,
  UNIQUE (contract_version_id, dimension)
);
ALTER TABLE contract_guarantee ENABLE ROW LEVEL SECURITY;
ALTER TABLE contract_guarantee FORCE ROW LEVEL SECURITY;
CREATE POLICY contract_guarantee_tenant_isolation ON contract_guarantee
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON contract_guarantee TO app_role;
GRANT UPDATE, DELETE ON contract_guarantee TO app_role;

-- endpoint: A consumption surface: SQL, REST, MCP, stream or share.
CREATE TABLE endpoint (
  endpoint_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  product_id TEXT NOT NULL REFERENCES data_product(product_id) ON DELETE CASCADE,
  surface TEXT NOT NULL CHECK (surface IN ('sql','rest','mcp','stream','share')),
  uri TEXT NOT NULL,
  auth_mode TEXT NOT NULL,
  required_scope TEXT NOT NULL,
  row_limit INT,
  documentation_ref TEXT NOT NULL,
  UNIQUE (product_id, surface)
);
ALTER TABLE endpoint ENABLE ROW LEVEL SECURITY;
ALTER TABLE endpoint FORCE ROW LEVEL SECURITY;
CREATE POLICY endpoint_tenant_isolation ON endpoint
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON endpoint TO app_role;
GRANT UPDATE, DELETE ON endpoint TO app_role;
