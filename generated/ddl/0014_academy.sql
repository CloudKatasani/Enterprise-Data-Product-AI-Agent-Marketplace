-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- modules, paths, enrollments, assessments and certifications

-- academy_module: A learning unit, optionally bound to an asset so it can be offered in context.
CREATE TABLE academy_module (
  module_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  body_ref TEXT NOT NULL,
  estimated_minutes INT NOT NULL,
  asset_type TEXT CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT,
  sandbox_tier TEXT NOT NULL DEFAULT 'demo' CHECK (sandbox_tier IN ('demo','none')),
  sort_order INT NOT NULL
);
ALTER TABLE academy_module ENABLE ROW LEVEL SECURITY;
ALTER TABLE academy_module FORCE ROW LEVEL SECURITY;
CREATE POLICY academy_module_tenant_isolation ON academy_module
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON academy_module TO app_role;
GRANT UPDATE, DELETE ON academy_module TO app_role;

-- learning_path: An ordered set of modules for a persona, ending in a certification.
CREATE TABLE learning_path (
  path_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  title TEXT NOT NULL,
  persona TEXT NOT NULL,
  summary TEXT NOT NULL,
  module_ids TEXT[] NOT NULL,
  certification_code TEXT
);
ALTER TABLE learning_path ENABLE ROW LEVEL SECURITY;
ALTER TABLE learning_path FORCE ROW LEVEL SECURITY;
CREATE POLICY learning_path_tenant_isolation ON learning_path
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON learning_path TO app_role;
GRANT UPDATE, DELETE ON learning_path TO app_role;

-- enrollment: A party's progress through a path.
CREATE TABLE enrollment (
  enrollment_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  path_id TEXT NOT NULL REFERENCES learning_path(path_id),
  party_id TEXT NOT NULL REFERENCES party(party_id),
  state TEXT NOT NULL CHECK (state IN ('enrolled','in_progress','completed','lapsed')),
  completed_module_ids TEXT[] NOT NULL DEFAULT '{}',
  enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  UNIQUE (path_id, party_id)
);
ALTER TABLE enrollment ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrollment FORCE ROW LEVEL SECURITY;
CREATE POLICY enrollment_tenant_isolation ON enrollment
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON enrollment TO app_role;
GRANT UPDATE, DELETE ON enrollment TO app_role;

-- assessment_result: One assessment attempt. The pass mark is a rubric value, not a constant.
CREATE TABLE assessment_result (
  result_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  enrollment_id TEXT NOT NULL REFERENCES enrollment(enrollment_id),
  module_id TEXT NOT NULL REFERENCES academy_module(module_id),
  score_pct NUMERIC(5,2) NOT NULL,
  passed BOOLEAN NOT NULL,
  rubric_version_id TEXT NOT NULL REFERENCES rubric_version(rubric_version_id),
  attempted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE assessment_result ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_result FORCE ROW LEVEL SECURITY;
CREATE POLICY assessment_result_tenant_isolation ON assessment_result
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON assessment_result TO app_role;
GRANT UPDATE, DELETE ON assessment_result TO app_role;

-- certification: A held certification, with expiry so competence claims stay current.
CREATE TABLE certification (
  certification_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  code TEXT NOT NULL,
  party_id TEXT NOT NULL REFERENCES party(party_id),
  path_id TEXT NOT NULL REFERENCES learning_path(path_id),
  issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,
  UNIQUE (code, party_id)
);
ALTER TABLE certification ENABLE ROW LEVEL SECURITY;
ALTER TABLE certification FORCE ROW LEVEL SECURITY;
CREATE POLICY certification_tenant_isolation ON certification
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON certification TO app_role;
GRANT UPDATE, DELETE ON certification TO app_role;
