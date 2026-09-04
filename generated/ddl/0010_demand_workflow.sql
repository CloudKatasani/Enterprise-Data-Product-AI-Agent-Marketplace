-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- requests, approvals, decisions, demand and durable workflow

-- request: One governed request: access, enhancement or new supply.
CREATE TABLE request (
  request_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  request_type TEXT NOT NULL CHECK (request_type IN ('access','enhancement','supply')),
  state TEXT NOT NULL,
  requester_party_id TEXT NOT NULL REFERENCES party(party_id),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  purpose_code TEXT REFERENCES purpose_category(code),
  purpose_text TEXT,
  policy_path TEXT,  -- Approval path resolved before submission: auto, owner, owner_steward, ...
  policy_version_id TEXT REFERENCES policy_version(policy_version_id),
  sla_hours INT,
  sla_due_at TIMESTAMPTZ,
  escalated_at TIMESTAMPTZ,
  submitted_at TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX request_state_idx ON request (request_type, state);
CREATE INDEX request_requester_idx ON request (requester_party_id);
CREATE INDEX request_sla_idx ON request (sla_due_at) WHERE closed_at IS NULL;
ALTER TABLE request ENABLE ROW LEVEL SECURITY;
ALTER TABLE request FORCE ROW LEVEL SECURITY;
CREATE POLICY request_tenant_isolation ON request
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON request TO app_role;
GRANT UPDATE, DELETE ON request TO app_role;

-- request_item: One asset and access level within a request; a request may be partially approved.
CREATE TABLE request_item (
  request_item_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  request_id TEXT NOT NULL REFERENCES request(request_id) ON DELETE CASCADE,
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  access_level TEXT NOT NULL CHECK (access_level IN ('read_metadata','read_data','read_data_pii','agent_invoke','write_back')),
  columns_requested TEXT[] NOT NULL DEFAULT '{}',
  outcome TEXT CHECK (outcome IN ('approved','declined','withdrawn')),
  outcome_reason TEXT,
  UNIQUE (request_id, asset_type, asset_id, access_level)
);
ALTER TABLE request_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_item FORCE ROW LEVEL SECURITY;
CREATE POLICY request_item_tenant_isolation ON request_item
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON request_item TO app_role;
GRANT UPDATE, DELETE ON request_item TO app_role;

-- approval_step: One required approval in the resolved path, with its own SLA clock.
CREATE TABLE approval_step (
  step_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  request_id TEXT NOT NULL REFERENCES request(request_id) ON DELETE CASCADE,
  ordinal INT NOT NULL,
  approver_role TEXT NOT NULL,
  approver_party_id TEXT REFERENCES party(party_id),
  state TEXT NOT NULL CHECK (state IN ('pending','approved','declined','skipped','escalated')),
  due_at TIMESTAMPTZ,
  acted_at TIMESTAMPTZ,
  UNIQUE (request_id, ordinal)
);
ALTER TABLE approval_step ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_step FORCE ROW LEVEL SECURITY;
CREATE POLICY approval_step_tenant_isolation ON approval_step
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON approval_step TO app_role;
GRANT UPDATE, DELETE ON approval_step TO app_role;

-- decision: Actor, timestamp, decision, reason and the policy version in force.
CREATE TABLE decision (
  decision_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  request_id TEXT NOT NULL REFERENCES request(request_id),
  step_id TEXT REFERENCES approval_step(step_id),
  actor_party_id TEXT NOT NULL REFERENCES party(party_id),
  outcome TEXT NOT NULL CHECK (outcome IN ('approve','decline','partial','block','withdraw')),
  reason_code TEXT NOT NULL,
  reason_text TEXT NOT NULL,
  policy_version_id TEXT REFERENCES policy_version(policy_version_id),
  decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX decision_request_idx ON decision (request_id, decided_at);
ALTER TABLE decision ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision FORCE ROW LEVEL SECURITY;
CREATE POLICY decision_tenant_isolation ON decision
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON decision TO app_role;
GRANT UPDATE, DELETE ON decision TO app_role;

-- enhancement: An enhancement to an existing asset. Declines are public and reasoned.
CREATE TABLE enhancement (
  enhancement_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  request_id TEXT NOT NULL REFERENCES request(request_id),
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('submitted','triaged','assessed','accepted','declined','merged','scheduled','in_progress','delivered','verified','auto_closed')),
  decline_reason_code TEXT CHECK (decline_reason_code IN ('out_of_scope','source_unavailable','cost_prohibitive','duplicate','superseded','security_constraint')),
  decline_reason_text TEXT,
  merged_into TEXT REFERENCES enhancement(enhancement_id),
  triage_due_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  verify_due_at TIMESTAMPTZ,
  CHECK (state <> 'declined' OR (decline_reason_code IS NOT NULL AND length(trim(coalesce(decline_reason_text,''))) > 0))
);
ALTER TABLE enhancement ENABLE ROW LEVEL SECURITY;
ALTER TABLE enhancement FORCE ROW LEVEL SECURITY;
CREATE POLICY enhancement_tenant_isolation ON enhancement
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON enhancement TO app_role;
GRANT UPDATE, DELETE ON enhancement TO app_role;

-- demand_theme: A cluster of demand items. Five distinct requesting teams auto-escalates it.
CREATE TABLE demand_theme (
  theme_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  label TEXT NOT NULL,
  summary TEXT NOT NULL,
  distinct_team_count INT NOT NULL DEFAULT 0,
  escalated_at TIMESTAMPTZ,
  confidence NUMERIC(4,3) NOT NULL,
  rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 10)
);
ALTER TABLE demand_theme ENABLE ROW LEVEL SECURITY;
ALTER TABLE demand_theme FORCE ROW LEVEL SECURITY;
CREATE POLICY demand_theme_tenant_isolation ON demand_theme
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON demand_theme TO app_role;
GRANT UPDATE, DELETE ON demand_theme TO app_role;

-- demand_item: A new-supply request on the public board, scored against the demand rubric.
CREATE TABLE demand_item (
  demand_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  request_id TEXT NOT NULL REFERENCES request(request_id),
  theme_id TEXT REFERENCES demand_theme(theme_id),
  state TEXT NOT NULL CHECK (state IN ('submitted','duplicate_review','triaged','scored','roadmapped','in_build','delivered','declined')),
  score NUMERIC(5,2),
  score_breakdown JSONB,
  rubric_version_id TEXT REFERENCES rubric_version(rubric_version_id),
  decline_reason_public TEXT,
  draft_manifest JSONB  -- Generated on acceptance with confidence and rationale per field.
);
ALTER TABLE demand_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE demand_item FORCE ROW LEVEL SECURITY;
CREATE POLICY demand_item_tenant_isolation ON demand_item
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON demand_item TO app_role;
GRANT UPDATE, DELETE ON demand_item TO app_role;

-- duplicate_match: A candidate duplicate found at submission, with its contributing factors.
CREATE TABLE duplicate_match (
  match_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  demand_id TEXT NOT NULL REFERENCES demand_item(demand_id) ON DELETE CASCADE,
  candidate_type TEXT NOT NULL CHECK (candidate_type IN ('data_product','agent','demand')),
  candidate_id TEXT NOT NULL,
  similarity NUMERIC(4,3) NOT NULL,
  contributing_factors JSONB NOT NULL,
  confidence NUMERIC(4,3) NOT NULL,
  rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 10),
  disposition TEXT NOT NULL CHECK (disposition IN ('blocking','advisory','informational','architect_review')),
  reviewed_by TEXT REFERENCES party(party_id),
  UNIQUE (demand_id, candidate_type, candidate_id)
);
ALTER TABLE duplicate_match ENABLE ROW LEVEL SECURITY;
ALTER TABLE duplicate_match FORCE ROW LEVEL SECURITY;
CREATE POLICY duplicate_match_tenant_isolation ON duplicate_match
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON duplicate_match TO app_role;
GRANT UPDATE, DELETE ON duplicate_match TO app_role;

-- demand_vote: A vote. It requires a one-line use case: a vote without context is not counted.
CREATE TABLE demand_vote (
  vote_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  demand_id TEXT NOT NULL REFERENCES demand_item(demand_id) ON DELETE CASCADE,
  voter_party_id TEXT NOT NULL REFERENCES party(party_id),
  use_case TEXT NOT NULL CHECK (length(trim(use_case)) > 10),
  org_unit_id TEXT REFERENCES org_unit(org_unit_id),
  voted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (demand_id, voter_party_id)
);
ALTER TABLE demand_vote ENABLE ROW LEVEL SECURITY;
ALTER TABLE demand_vote FORCE ROW LEVEL SECURITY;
CREATE POLICY demand_vote_tenant_isolation ON demand_vote
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON demand_vote TO app_role;
GRANT UPDATE, DELETE ON demand_vote TO app_role;

-- workflow_instance: Durable workflow state. An approval survives a process restart (D-003).
CREATE TABLE workflow_instance (
  instance_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  workflow_type TEXT NOT NULL CHECK (workflow_type IN ('access','enhancement','demand','provisioning','revocation','canary')),
  subject_id TEXT NOT NULL,
  state TEXT NOT NULL,
  payload JSONB NOT NULL,
  run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX workflow_due_idx ON workflow_instance (run_after) WHERE completed_at IS NULL;
CREATE INDEX workflow_subject_idx ON workflow_instance (workflow_type, subject_id);
ALTER TABLE workflow_instance ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_instance FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_instance_tenant_isolation ON workflow_instance
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON workflow_instance TO app_role;
GRANT UPDATE, DELETE ON workflow_instance TO app_role;

-- workflow_event: Append-only transition log for a workflow instance; replayable.
CREATE TABLE workflow_event (
  event_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  instance_id TEXT NOT NULL REFERENCES workflow_instance(instance_id) ON DELETE CASCADE,
  from_state TEXT,
  to_state TEXT NOT NULL,
  actor TEXT NOT NULL,
  detail JSONB NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX workflow_event_order_idx ON workflow_event (instance_id, occurred_at);
ALTER TABLE workflow_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_event FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_event_tenant_isolation ON workflow_event
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON workflow_event TO app_role;
GRANT UPDATE, DELETE ON workflow_event TO app_role;
