-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- value cases, assumptions and measurements

-- value_case: The quantified case for an asset, with its baseline and attribution confidence.
CREATE TABLE value_case (
  value_case_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  business_outcome TEXT NOT NULL,
  baseline_method TEXT NOT NULL,
  baseline_captured DATE NOT NULL,
  benefit_model TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL CHECK (attribution_confidence IN ('high','medium','low')),
  rubric_version_id TEXT NOT NULL REFERENCES rubric_version(rubric_version_id),
  last_reviewed DATE NOT NULL,
  reviewer_party_id TEXT NOT NULL REFERENCES party(party_id),
  review_due DATE NOT NULL,
  UNIQUE (asset_type, asset_id)
);
ALTER TABLE value_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE value_case FORCE ROW LEVEL SECURITY;
CREATE POLICY value_case_tenant_isolation ON value_case
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON value_case TO app_role;
GRANT UPDATE, DELETE ON value_case TO app_role;

-- value_assumption: A named assumption with its value, sample size and date. Displayed beside any figure.
CREATE TABLE value_assumption (
  assumption_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  value_case_id TEXT NOT NULL REFERENCES value_case(value_case_id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  numeric_value NUMERIC(14,4) NOT NULL,
  unit TEXT NOT NULL,
  sample_size INT,
  source TEXT NOT NULL,
  dated DATE NOT NULL
);
ALTER TABLE value_assumption ENABLE ROW LEVEL SECURITY;
ALTER TABLE value_assumption FORCE ROW LEVEL SECURITY;
CREATE POLICY value_assumption_tenant_isolation ON value_assumption
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON value_assumption TO app_role;
GRANT UPDATE, DELETE ON value_assumption TO app_role;

-- value_measurement: A realised measurement period: deflected hours, value, cost and the ratio.
CREATE TABLE value_measurement (
  measurement_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  value_case_id TEXT NOT NULL REFERENCES value_case(value_case_id),
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  answered_questions BIGINT NOT NULL,
  acceptance_rate NUMERIC(5,4) NOT NULL,
  deflected_hours NUMERIC(14,4) NOT NULL,
  deflected_value_usd NUMERIC(16,4) NOT NULL,
  total_cost_usd NUMERIC(16,4) NOT NULL,
  net_value_usd NUMERIC(16,4) NOT NULL,
  value_ratio NUMERIC(10,4) NOT NULL,
  rubric_version_id TEXT NOT NULL REFERENCES rubric_version(rubric_version_id),
  snapshot_ref TEXT NOT NULL,  -- Board pack and dashboard read the same snapshot so they cannot disagree.
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (value_case_id, period_start, period_end)
);
ALTER TABLE value_measurement ENABLE ROW LEVEL SECURITY;
ALTER TABLE value_measurement FORCE ROW LEVEL SECURITY;
CREATE POLICY value_measurement_tenant_isolation ON value_measurement
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON value_measurement TO app_role;
GRANT UPDATE, DELETE ON value_measurement TO app_role;
