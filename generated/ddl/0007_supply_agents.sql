-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- agents, versions, coverage, bindings, demos and evaluation

-- prompt_artifact: Content-addressed prompt. An agent version pins the hash, never the text.
CREATE TABLE prompt_artifact (
  prompt_hash TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_id TEXT NOT NULL,
  label TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE prompt_artifact ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_artifact FORCE ROW LEVEL SECURITY;
CREATE POLICY prompt_artifact_tenant_isolation ON prompt_artifact
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON prompt_artifact TO app_role;
GRANT UPDATE, DELETE ON prompt_artifact TO app_role;

-- agent: A catalogued AI assistant with an owner, coverage map, scope and value case.
CREATE TABLE agent (
  agent_id TEXT PRIMARY KEY,  -- AG-<IND>-<NNN>
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  name TEXT NOT NULL,
  industry_code TEXT NOT NULL REFERENCES industry(code),
  domain_code TEXT NOT NULL REFERENCES business_domain(code),
  owner_party_id TEXT NOT NULL REFERENCES party(party_id),
  machine_identity TEXT NOT NULL UNIQUE,  -- Distinct service principal; effective access is an intersection (I12).
  on_call TEXT NOT NULL,
  escalation_path TEXT NOT NULL,
  certification TEXT NOT NULL CHECK (certification IN ('certified','published','beta','deprecated')),
  current_version_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agent_taxonomy_idx ON agent (industry_code, domain_code);
ALTER TABLE agent ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_tenant_isolation ON agent
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON agent TO app_role;
GRANT UPDATE, DELETE ON agent TO app_role;

-- evaluation_run: One execution of the evaluation suites against an agent bundle.
CREATE TABLE evaluation_run (
  eval_run_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_id TEXT NOT NULL REFERENCES agent(agent_id),
  agent_version_ref TEXT NOT NULL,  -- Set before the version row exists on a first publish; not an FK.
  suite_results JSONB NOT NULL,
  pass_rate_pct NUMERIC(5,2) NOT NULL,
  groundedness_pct NUMERIC(5,2) NOT NULL,
  threshold_pct NUMERIC(5,2) NOT NULL,
  passed BOOLEAN NOT NULL,
  previous_run_id TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX evaluation_run_recent_idx ON evaluation_run (agent_id, finished_at DESC);
ALTER TABLE evaluation_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_run FORCE ROW LEVEL SECURITY;
CREATE POLICY evaluation_run_tenant_isolation ON evaluation_run
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON evaluation_run TO app_role;
GRANT UPDATE, DELETE ON evaluation_run TO app_role;

-- agent_version: An immutable bundle: model, params, prompt hash, tool bindings, eval run.
-- invariants: I7
CREATE TABLE agent_version (
  agent_version_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_id TEXT NOT NULL REFERENCES agent(agent_id),
  semver TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','canary','published','retired')),
  autonomy_level TEXT NOT NULL CHECK (autonomy_level IN ('L0','L1','L2','L3')),
  capability_statement TEXT NOT NULL CHECK (length(capability_statement) BETWEEN 90 AND 140),
  business_value_block TEXT NOT NULL,
  out_of_scope TEXT[] NOT NULL CHECK (array_length(out_of_scope,1) >= 1),  -- I7: an agent that refuses nothing has no boundary.
  personas TEXT[] NOT NULL DEFAULT '{}',
  analyses TEXT[] NOT NULL DEFAULT '{}',
  replaces TEXT NOT NULL,
  model_provider TEXT NOT NULL,
  model_id TEXT NOT NULL,
  model_params JSONB NOT NULL,
  prompt_hash TEXT NOT NULL REFERENCES prompt_artifact(prompt_hash),
  guardrail_config JSONB NOT NULL,
  budget_p95_latency_ms INT NOT NULL,
  budget_cost_per_answer_usd NUMERIC(10,4) NOT NULL,
  eval_run_id TEXT REFERENCES evaluation_run(eval_run_id),
  canary_traffic_pct NUMERIC(5,2),
  published_at TIMESTAMPTZ,
  published_by TEXT REFERENCES party(party_id),
  retired_at TIMESTAMPTZ,
  UNIQUE (agent_id, semver)
);
CREATE INDEX agent_version_status_idx ON agent_version (agent_id, status);
ALTER TABLE agent_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_version FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_version_tenant_isolation ON agent_version
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON agent_version TO app_role;
GRANT UPDATE, DELETE ON agent_version TO app_role;

-- agent_kpi_coverage: The agent's functional contract: which KPI, at which grains and slices, how deep.
-- invariants: I4
CREATE TABLE agent_kpi_coverage (
  coverage_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_version_id TEXT NOT NULL REFERENCES agent_version(agent_version_id) ON DELETE CASCADE,
  kpi_id TEXT NOT NULL REFERENCES kpi_definition(kpi_id),  -- I4: coverage cannot cite a KPI that does not exist.
  source_product_id TEXT NOT NULL REFERENCES data_product(product_id),
  columns_used TEXT[] NOT NULL,
  supported_grains TEXT[] NOT NULL,
  supported_slices TEXT[] NOT NULL,
  analysis_depth TEXT NOT NULL CHECK (analysis_depth IN ('report','compare','explain','rank_drivers','forecast')),
  eval_accuracy NUMERIC(5,2),
  eval_sample_size INT,
  UNIQUE (agent_version_id, kpi_id)
);
ALTER TABLE agent_kpi_coverage ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_kpi_coverage FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_kpi_coverage_tenant_isolation ON agent_kpi_coverage
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON agent_kpi_coverage TO app_role;
GRANT UPDATE, DELETE ON agent_kpi_coverage TO app_role;

-- agent_product_binding: Which product columns an agent version may read. The scope half of I12.
CREATE TABLE agent_product_binding (
  binding_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_version_id TEXT NOT NULL REFERENCES agent_version(agent_version_id) ON DELETE CASCADE,
  product_id TEXT NOT NULL REFERENCES data_product(product_id),
  columns_allowed TEXT[] NOT NULL,
  access_level TEXT NOT NULL CHECK (access_level IN ('read','read_pii')),
  contract_version_pinned TEXT NOT NULL,
  UNIQUE (agent_version_id, product_id)
);
ALTER TABLE agent_product_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_product_binding FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_product_binding_tenant_isolation ON agent_product_binding
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON agent_product_binding TO app_role;
GRANT UPDATE, DELETE ON agent_product_binding TO app_role;

-- agent_tool_binding: A tool the agent may call, with its scope, row limit and cost class.
CREATE TABLE agent_tool_binding (
  tool_binding_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_version_id TEXT NOT NULL REFERENCES agent_version(agent_version_id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL,
  endpoint_uri TEXT NOT NULL,
  required_scope TEXT NOT NULL,
  cost_class TEXT NOT NULL CHECK (cost_class IN ('trivial','small','medium','large')),
  row_limit INT,
  UNIQUE (agent_version_id, tool_name)
);
ALTER TABLE agent_tool_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tool_binding FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_tool_binding_tenant_isolation ON agent_tool_binding
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON agent_tool_binding TO app_role;
GRANT UPDATE, DELETE ON agent_tool_binding TO app_role;

-- demo_exchange: A curated question with a golden answer. Five are required to publish (I3).
-- invariants: I3
CREATE TABLE demo_exchange (
  exchange_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_version_id TEXT NOT NULL REFERENCES agent_version(agent_version_id) ON DELETE CASCADE,
  ordinal INT NOT NULL,
  question TEXT NOT NULL,
  kpi_class TEXT NOT NULL REFERENCES kpi_definition(kpi_id),
  analysis_type TEXT NOT NULL,
  expected_shape JSONB NOT NULL,  -- headline, visual, table_columns, must_cite[]
  data_tier TEXT NOT NULL CHECK (data_tier IN ('demo','live')),
  max_latency_ms INT NOT NULL,
  golden_answer_ref TEXT NOT NULL,
  tolerance_pct NUMERIC(5,2) NOT NULL,
  last_validated TIMESTAMPTZ,
  validation_state TEXT NOT NULL CHECK (validation_state IN ('passing','stale','failing')),
  UNIQUE (agent_version_id, ordinal)
);
ALTER TABLE demo_exchange ENABLE ROW LEVEL SECURITY;
ALTER TABLE demo_exchange FORCE ROW LEVEL SECURITY;
CREATE POLICY demo_exchange_tenant_isolation ON demo_exchange
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON demo_exchange TO app_role;
GRANT UPDATE, DELETE ON demo_exchange TO app_role;

-- evaluation_case: One case in an evaluation suite, including cases harvested from rejections.
CREATE TABLE evaluation_case (
  case_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_id TEXT NOT NULL REFERENCES agent(agent_id),
  suite TEXT NOT NULL CHECK (suite IN ('golden_accuracy','groundedness','boundary_refusal','adversarial','entitlement','compositional_exposure','consistency','cost_latency')),
  question TEXT NOT NULL,
  persona_ref TEXT,
  expected_behaviour TEXT NOT NULL,
  expected_payload JSONB NOT NULL,
  blocking BOOLEAN NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('authored','feedback','incident','regression')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX evaluation_case_suite_idx ON evaluation_case (agent_id, suite);
ALTER TABLE evaluation_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluation_case FORCE ROW LEVEL SECURITY;
CREATE POLICY evaluation_case_tenant_isolation ON evaluation_case
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON evaluation_case TO app_role;
GRANT UPDATE, DELETE ON evaluation_case TO app_role;
