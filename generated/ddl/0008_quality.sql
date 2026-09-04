-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: e507de7741ea403b819f92cb7ca8a9c4f98bcabab341c6a1026c556f8d22cf7f  generated_at: 2026-09-04T03:37:55+00:00

-- rules, results, immutable score snapshots and incidents

-- quality_rule: An executable expectation declared by a product manifest.
CREATE TABLE quality_rule (
  rule_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  product_id TEXT NOT NULL REFERENCES data_product(product_id) ON DELETE CASCADE,
  dimension TEXT NOT NULL CHECK (dimension IN ('completeness','accuracy','freshness','consistency','validity','uniqueness')),
  rule_type TEXT NOT NULL,
  target_columns TEXT[] NOT NULL DEFAULT '{}',
  threshold_pct NUMERIC(6,3),
  target_text TEXT,
  tolerance_minutes INT,
  severity TEXT NOT NULL CHECK (severity IN ('critical','high','medium','low')),
  enabled BOOLEAN NOT NULL DEFAULT true
);
ALTER TABLE quality_rule ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_rule FORCE ROW LEVEL SECURITY;
CREATE POLICY quality_rule_tenant_isolation ON quality_rule
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON quality_rule TO app_role;
GRANT UPDATE, DELETE ON quality_rule TO app_role;

-- quality_result: One evaluation of one rule. The evidence a composite is computed from.
CREATE TABLE quality_result (
  result_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  rule_id TEXT NOT NULL REFERENCES quality_rule(rule_id),
  product_id TEXT NOT NULL REFERENCES data_product(product_id),
  observed_pct NUMERIC(9,4),  -- For a rule expressed as a percentage against a threshold.
  observed_value NUMERIC(14,4),  -- For a rule expressed as a measure against a tolerance, such as freshness lag in minutes.
  observed_unit TEXT,
  observed_text TEXT,
  passed BOOLEAN NOT NULL,
  rows_evaluated BIGINT,
  source TEXT NOT NULL CHECK (source IN ('dmf','soda','montecarlo','internal','manual')),
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX quality_result_recent_idx ON quality_result (product_id, evaluated_at DESC);
ALTER TABLE quality_result ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_result FORCE ROW LEVEL SECURITY;
CREATE POLICY quality_result_tenant_isolation ON quality_result
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON quality_result TO app_role;
GRANT UPDATE, DELETE ON quality_result TO app_role;

-- quality_score_snapshot: An immutable composite score, replayable from its evidence and rubric version.
-- invariants: I2
CREATE TABLE quality_score_snapshot (
  snapshot_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  product_id TEXT NOT NULL REFERENCES data_product(product_id),
  rubric_version_id TEXT NOT NULL REFERENCES rubric_version(rubric_version_id),  -- I2: a score without the rubric it was computed under is meaningless.
  composite NUMERIC(5,2) NOT NULL,
  completeness NUMERIC(5,2),
  accuracy NUMERIC(5,2),
  freshness NUMERIC(5,2),
  consistency NUMERIC(5,2),
  validity NUMERIC(5,2),
  uniqueness NUMERIC(5,2),
  band TEXT NOT NULL,  -- Resolved from rubric bands, never from code.
  blocker_applied TEXT,  -- Which hard blocker capped the composite, if any.
  evidence_ref JSONB NOT NULL,  -- rule_ids + result_ids that produced this score.
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX quality_snapshot_recent_idx ON quality_score_snapshot (product_id, computed_at DESC);
ALTER TABLE quality_score_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_score_snapshot FORCE ROW LEVEL SECURITY;
CREATE POLICY quality_score_snapshot_tenant_isolation ON quality_score_snapshot
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
-- rule 6: append-only. History is written, never rewritten.
REVOKE UPDATE, DELETE ON quality_score_snapshot FROM app_role;
GRANT SELECT, INSERT ON quality_score_snapshot TO app_role;

-- incident: A detected breach. Severity is computed from blast radius, never chosen.
CREATE TABLE incident (
  incident_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent','source_system','kpi')),
  asset_id TEXT NOT NULL,
  signal TEXT NOT NULL,
  guarantee_breached TEXT,
  severity TEXT NOT NULL CHECK (severity IN ('sev1','sev2','sev3','sev4')),
  severity_inputs JSONB NOT NULL,  -- consumer count x sensitivity rank x guarantee, so severity is auditable.
  status TEXT NOT NULL CHECK (status IN ('open','mitigating','resolved','closed')),
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  notified_at TIMESTAMPTZ,
  resolved_at TIMESTAMPTZ,
  root_cause TEXT,
  owner_context TEXT  -- Owners may add context; they cannot suppress consumer notification.
);
CREATE INDEX incident_asset_idx ON incident (asset_type, asset_id, status);
ALTER TABLE incident ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident FORCE ROW LEVEL SECURITY;
CREATE POLICY incident_tenant_isolation ON incident
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON incident TO app_role;
GRANT UPDATE, DELETE ON incident TO app_role;

-- incident_impact: Who an incident reached. Drives banners on every affected listing.
CREATE TABLE incident_impact (
  impact_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  incident_id TEXT NOT NULL REFERENCES incident(incident_id) ON DELETE CASCADE,
  affected_asset_type TEXT NOT NULL CHECK (affected_asset_type IN ('data_product','agent')),
  affected_asset_id TEXT NOT NULL,
  consumer_count INT NOT NULL,
  notified_at TIMESTAMPTZ,
  banner_active BOOLEAN NOT NULL DEFAULT true,
  UNIQUE (incident_id, affected_asset_type, affected_asset_id)
);
ALTER TABLE incident_impact ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident_impact FORCE ROW LEVEL SECURITY;
CREATE POLICY incident_impact_tenant_isolation ON incident_impact
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON incident_impact TO app_role;
GRANT UPDATE, DELETE ON incident_impact TO app_role;
