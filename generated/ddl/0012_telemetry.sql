-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- usage, agent interactions, feedback and cost

-- usage_event: A metadata-level consumption event. No row-level customer data (rule 5).
CREATE TABLE usage_event (
  event_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  principal_id TEXT REFERENCES party(party_id),
  surface TEXT NOT NULL,
  event_name TEXT NOT NULL,  -- From the typed event taxonomy; a new name must be added there first.
  purpose_code TEXT REFERENCES purpose_category(code),
  rows_returned BIGINT,
  columns_returned TEXT[],
  outcome TEXT NOT NULL CHECK (outcome IN ('ok','denied','error','throttled')),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX usage_asset_idx ON usage_event (asset_type, asset_id, occurred_at DESC);
CREATE INDEX usage_denied_idx ON usage_event (outcome, occurred_at DESC) WHERE outcome = 'denied';
ALTER TABLE usage_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_event FORCE ROW LEVEL SECURITY;
CREATE POLICY usage_event_tenant_isolation ON usage_event
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON usage_event TO app_role;
GRANT UPDATE, DELETE ON usage_event TO app_role;

-- usage_daily_agg: Pre-aggregated adoption. Card counts and ranking read this, not raw events.
CREATE TABLE usage_daily_agg (
  agg_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  activity_date DATE NOT NULL,
  active_consumers INT NOT NULL,
  distinct_teams INT NOT NULL,
  query_count BIGINT NOT NULL,
  denied_count BIGINT NOT NULL,
  rows_scanned BIGINT NOT NULL,
  UNIQUE (asset_type, asset_id, activity_date)
);
CREATE INDEX usage_agg_recent_idx ON usage_daily_agg (asset_id, activity_date DESC);
ALTER TABLE usage_daily_agg ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily_agg FORCE ROW LEVEL SECURITY;
CREATE POLICY usage_daily_agg_tenant_isolation ON usage_daily_agg
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON usage_daily_agg TO app_role;
GRANT UPDATE, DELETE ON usage_daily_agg TO app_role;

-- agent_interaction: One question answered, with its trace. The evidence behind value and FinOps.
CREATE TABLE agent_interaction (
  interaction_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_version_id TEXT NOT NULL REFERENCES agent_version(agent_version_id),
  principal_id TEXT REFERENCES party(party_id),
  session_id TEXT NOT NULL,
  tier TEXT NOT NULL CHECK (tier IN ('demo','live')),
  question TEXT NOT NULL,
  question_class TEXT NOT NULL,
  purpose_code TEXT REFERENCES purpose_category(code),
  outcome TEXT NOT NULL CHECK (outcome IN ('answered','out_of_scope','ungrounded','denied','error')),
  grounded BOOLEAN NOT NULL,
  confidence NUMERIC(4,3),
  citations JSONB NOT NULL DEFAULT '[]'::jsonb,
  kpi_definitions TEXT[] NOT NULL DEFAULT '{}',
  tool_calls JSONB NOT NULL DEFAULT '[]'::jsonb,
  rows_scanned BIGINT,
  latency_ms INT NOT NULL,
  tokens_in INT NOT NULL,
  tokens_out INT NOT NULL,
  cost_usd NUMERIC(12,6) NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX interaction_agent_idx ON agent_interaction (agent_version_id, occurred_at DESC);
CREATE INDEX interaction_outcome_idx ON agent_interaction (outcome, occurred_at DESC);
ALTER TABLE agent_interaction ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_interaction FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_interaction_tenant_isolation ON agent_interaction
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON agent_interaction TO app_role;
GRANT UPDATE, DELETE ON agent_interaction TO app_role;

-- answer_feedback: Acceptance or rejection with a reason; rejections become evaluation cases.
CREATE TABLE answer_feedback (
  feedback_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  interaction_id TEXT NOT NULL REFERENCES agent_interaction(interaction_id),
  party_id TEXT NOT NULL REFERENCES party(party_id),
  accepted BOOLEAN NOT NULL,
  reason_code TEXT NOT NULL CHECK (reason_code IN ('correct','useful_partial','wrong_number','wrong_scope','missing_context','stale_data','unclear','other')),
  reason_text TEXT,
  promoted_case_id TEXT REFERENCES evaluation_case(case_id),
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (interaction_id, party_id)
);
ALTER TABLE answer_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE answer_feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY answer_feedback_tenant_isolation ON answer_feedback
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON answer_feedback TO app_role;
GRANT UPDATE, DELETE ON answer_feedback TO app_role;

-- cost_allocation: Attributed cost per asset per day: inference, retrieval, query, platform, stewardship.
CREATE TABLE cost_allocation (
  allocation_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  cost_date DATE NOT NULL,
  inference_usd NUMERIC(14,6) NOT NULL DEFAULT 0,
  retrieval_usd NUMERIC(14,6) NOT NULL DEFAULT 0,
  query_usd NUMERIC(14,6) NOT NULL DEFAULT 0,
  platform_usd NUMERIC(14,6) NOT NULL DEFAULT 0,
  stewardship_usd NUMERIC(14,6) NOT NULL DEFAULT 0,
  tier TEXT NOT NULL CHECK (tier IN ('demo','live')),
  source TEXT NOT NULL,
  UNIQUE (asset_type, asset_id, cost_date, tier)
);
ALTER TABLE cost_allocation ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_allocation FORCE ROW LEVEL SECURITY;
CREATE POLICY cost_allocation_tenant_isolation ON cost_allocation
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON cost_allocation TO app_role;
GRANT UPDATE, DELETE ON cost_allocation TO app_role;
