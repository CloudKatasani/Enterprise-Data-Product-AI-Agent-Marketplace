-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- KPI register, versions, synonyms and glossary

-- kpi_definition: A business measure with exactly one authoritative definition (I1).
-- invariants: I1
CREATE TABLE kpi_definition (
  kpi_id TEXT PRIMARY KEY,  -- KPI-<DOMAIN>-<NNN>
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  kpi_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','certified','deprecated','superseded')),
  business_definition TEXT NOT NULL,
  numerator_expr TEXT,
  denominator_expr TEXT,
  expression TEXT,
  grains_supported TEXT[] NOT NULL,
  slices_supported TEXT[] NOT NULL,
  inclusions TEXT[] NOT NULL DEFAULT '{}',
  exclusions TEXT[] NOT NULL DEFAULT '{}',
  unit TEXT NOT NULL,
  direction TEXT,
  target NUMERIC,
  domain_code TEXT NOT NULL REFERENCES business_domain(code),
  source_of_record TEXT REFERENCES data_product(product_id),
  steward_party_id TEXT NOT NULL REFERENCES party(party_id),
  forum_approved_at DATE,
  superseded_by TEXT REFERENCES kpi_definition(kpi_id),
  last_reviewed DATE NOT NULL,
  review_months INT NOT NULL
);
CREATE UNIQUE INDEX kpi_one_active ON kpi_definition (tenant_id, lower(kpi_name)) WHERE status IN ('draft','certified');
ALTER TABLE kpi_definition ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_definition FORCE ROW LEVEL SECURITY;
CREATE POLICY kpi_definition_tenant_isolation ON kpi_definition
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON kpi_definition TO app_role;
GRANT UPDATE, DELETE ON kpi_definition TO app_role;

-- kpi_definition_version: Immutable history of a KPI definition; agents pin the version they answered under.
CREATE TABLE kpi_definition_version (
  kpi_version_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  kpi_id TEXT NOT NULL REFERENCES kpi_definition(kpi_id),
  semver TEXT NOT NULL,
  business_definition TEXT NOT NULL,
  expression TEXT,
  change_reason TEXT NOT NULL,
  approved_by TEXT NOT NULL REFERENCES party(party_id),
  effective_from TIMESTAMPTZ NOT NULL,
  UNIQUE (kpi_id, semver)
);
ALTER TABLE kpi_definition_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_definition_version FORCE ROW LEVEL SECURITY;
CREATE POLICY kpi_definition_version_tenant_isolation ON kpi_definition_version
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON kpi_definition_version TO app_role;
GRANT UPDATE, DELETE ON kpi_definition_version TO app_role;

-- kpi_synonym: Alternate names a consumer might search for. Feeds lexical search recall.
CREATE TABLE kpi_synonym (
  synonym_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  kpi_id TEXT NOT NULL REFERENCES kpi_definition(kpi_id) ON DELETE CASCADE,
  term TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('steward','glossary','search_log','bi_tool')),
  UNIQUE (kpi_id, term)
);
ALTER TABLE kpi_synonym ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_synonym FORCE ROW LEVEL SECURITY;
CREATE POLICY kpi_synonym_tenant_isolation ON kpi_synonym
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON kpi_synonym TO app_role;
GRANT UPDATE, DELETE ON kpi_synonym TO app_role;

-- glossary_term: Business vocabulary. Distinct from KPIs: a term need not be measurable.
CREATE TABLE glossary_term (
  term_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  term TEXT NOT NULL,
  definition TEXT NOT NULL,
  domain_code TEXT NOT NULL REFERENCES business_domain(code),
  steward_party_id TEXT NOT NULL REFERENCES party(party_id),
  related_kpi_ids TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL CHECK (status IN ('draft','approved','deprecated')),
  UNIQUE (tenant_id, term)
);
ALTER TABLE glossary_term ENABLE ROW LEVEL SECURITY;
ALTER TABLE glossary_term FORCE ROW LEVEL SECURITY;
CREATE POLICY glossary_term_tenant_isolation ON glossary_term
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON glossary_term TO app_role;
GRANT UPDATE, DELETE ON glossary_term TO app_role;
