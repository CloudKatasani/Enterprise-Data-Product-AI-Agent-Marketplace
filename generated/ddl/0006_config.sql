-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- rubrics, policies and feature flags

-- rubric: A named body of versioned configuration: quality, ranking, mesh, demand, value, finops.
CREATE TABLE rubric (
  rubric_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  code TEXT NOT NULL,
  description TEXT NOT NULL,
  current_version_id TEXT,
  UNIQUE (tenant_id, code)
);
ALTER TABLE rubric ENABLE ROW LEVEL SECURITY;
ALTER TABLE rubric FORCE ROW LEVEL SECURITY;
CREATE POLICY rubric_tenant_isolation ON rubric
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON rubric TO app_role;
GRANT UPDATE, DELETE ON rubric TO app_role;

-- rubric_version: An immutable rubric version. Every score records the id it was computed under.
CREATE TABLE rubric_version (
  rubric_version_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  rubric_id TEXT NOT NULL REFERENCES rubric(rubric_id),
  semver TEXT NOT NULL,
  source_hash TEXT NOT NULL,  -- sha256 of the YAML that produced this version.
  payload JSONB NOT NULL,  -- The whole rubric document, so a score can be replayed exactly.
  effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  superseded_at TIMESTAMPTZ,
  created_by TEXT NOT NULL,
  UNIQUE (rubric_id, semver)
);
ALTER TABLE rubric_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE rubric_version FORCE ROW LEVEL SECURITY;
CREATE POLICY rubric_version_tenant_isolation ON rubric_version
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON rubric_version TO app_role;
GRANT UPDATE, DELETE ON rubric_version TO app_role;

-- rubric_criterion: One addressable value inside a rubric version: a weight, threshold, band or target.
CREATE TABLE rubric_criterion (
  criterion_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  rubric_version_id TEXT NOT NULL REFERENCES rubric_version(rubric_version_id) ON DELETE CASCADE,
  path TEXT NOT NULL,  -- Dotted path into the rubric document, e.g. dimensions.freshness.weight
  kind TEXT NOT NULL CHECK (kind IN ('weight','threshold','band','multiplier','target','reference','formula','flag','list')),
  numeric_value NUMERIC(14,6),
  text_value TEXT,
  scope TEXT,  -- Optional qualifier, e.g. the archetype an override applies to.
  UNIQUE (rubric_version_id, path, scope)
);
CREATE INDEX rubric_criterion_lookup_idx ON rubric_criterion (rubric_version_id, path);
ALTER TABLE rubric_criterion ENABLE ROW LEVEL SECURITY;
ALTER TABLE rubric_criterion FORCE ROW LEVEL SECURITY;
CREATE POLICY rubric_criterion_tenant_isolation ON rubric_criterion
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON rubric_criterion TO app_role;
GRANT UPDATE, DELETE ON rubric_criterion TO app_role;

-- policy: An access, residency, licence or separation-of-duties policy.
CREATE TABLE policy (
  policy_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  code TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('access','residency','licence','sod','retention','purpose')),
  description TEXT NOT NULL,
  current_version_id TEXT,
  UNIQUE (tenant_id, code)
);
ALTER TABLE policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy FORCE ROW LEVEL SECURITY;
CREATE POLICY policy_tenant_isolation ON policy
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON policy TO app_role;
GRANT UPDATE, DELETE ON policy TO app_role;

-- policy_version: An immutable policy version. Every decision records the version in force.
CREATE TABLE policy_version (
  policy_version_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  policy_id TEXT NOT NULL REFERENCES policy(policy_id),
  semver TEXT NOT NULL,
  rules JSONB NOT NULL,
  effective_from TIMESTAMPTZ NOT NULL DEFAULT now(),
  superseded_at TIMESTAMPTZ,
  UNIQUE (policy_id, semver)
);
ALTER TABLE policy_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_version FORCE ROW LEVEL SECURITY;
CREATE POLICY policy_version_tenant_isolation ON policy_version
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON policy_version TO app_role;
GRANT UPDATE, DELETE ON policy_version TO app_role;

-- feature_flag: A typed flag. Release and experiment flags carry a max age the lint enforces.
CREATE TABLE feature_flag (
  flag_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  code TEXT NOT NULL,
  flag_type TEXT NOT NULL CHECK (flag_type IN ('release','experiment','operational')),
  enabled BOOLEAN NOT NULL DEFAULT false,
  description TEXT NOT NULL,
  owner_party_id TEXT NOT NULL REFERENCES party(party_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  UNIQUE (tenant_id, code)
);
ALTER TABLE feature_flag ENABLE ROW LEVEL SECURITY;
ALTER TABLE feature_flag FORCE ROW LEVEL SECURITY;
CREATE POLICY feature_flag_tenant_isolation ON feature_flag
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON feature_flag TO app_role;
GRANT UPDATE, DELETE ON feature_flag TO app_role;
