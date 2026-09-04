# BUILD.md — Enterprise Data Product & AI Agent Marketplace

> **Input file for a coding agent (Claude Code, Codex, or equivalent).**
> This document is the single source of truth for the build. It is self-contained: you do not
> need the companion Word specification to execute it. Where this file and any other document
> disagree, **this file wins**.
>
> Product name is deliberately unset. Use the token `PRODUCT_NAME` from theme config.
> Never hardcode a brand string anywhere in application source.

---

## 0. Rules of engagement

Read this section before writing any code. These rules are enforced by CI; violating them
means the build fails, not that a reviewer complains.

1. **Work milestone by milestone** (Section 21). Do not start milestone N+1 until every
   acceptance criterion in milestone N passes. Run `npm run verify` between milestones.
2. **Nothing numeric lives in application source.** Every weight, threshold, grade band, SLA
   target, similarity cutoff and ranking coefficient lives in a rubric table seeded from YAML.
   `npm run lint:no-magic-numbers` scans `services/` and `portal/` and fails on numeric
   literals outside a whitelist (0, 1, -1, array indices, HTTP status codes, CSS in tokens).
3. **Generated files are never hand-edited.** Everything under `generated/` carries an
   auto-generated header. `npm run gen && git diff --exit-code generated/` must be clean.
4. **Every inference carries `confidence` and `rationale`.** Mesh edges, duplicate-supply
   matches, auto-drafted descriptions, value estimates. Below `0.80` confidence the record is
   not displayed until a `reviewed_by` is set.
5. **No row-level customer data in the default build.** Metadata, contracts and aggregate
   telemetry only. The sampling module is a separate optional package.
6. **Immutable by default.** `quality_score_snapshot`, `publication_snapshot`, `audit_event`
   and `entitlement_grant` history are append-only. No code path issues an `UPDATE` against them.
7. **Fail closed.** Missing purpose, missing scope, unresolvable citation, unknown rubric
   version → reject the request. Never degrade to a permissive default.
8. **Ask before inventing.** If a requirement here is ambiguous, implement the narrower
   reading and leave a `// SPEC-QUESTION:` comment. Do not invent business rules.
9. **Commit granularity:** one commit per numbered task in Section 21, message prefixed with
   the task id (e.g. `M3.4: snowflake connector usage harvest`).
10. **Every PR updates `docs/DECISIONS.md`** with any judgement call you made.

---

## 1. Mission and scope

Build an enterprise marketplace where **data products** and the **AI agents that run on them**
are catalogued, governed, requested, observed and demonstrated as one supply chain.

A business user must be able to:

- browse domain data products and AI agents in one catalog;
- see, before clicking anything, each asset's quality score, freshness, owner, adoption and
  the agents attached to it;
- watch an agent answer five curated questions live, with citations, before requesting access;
- request access, an enhancement, or an entirely new product/agent through governed rails;
- see two meshes — data products linked by shared upstream sources, agents linked by shared
  KPIs and products;
- see usage, adoption and a quantified value case for every asset.

**Out of scope:** building pipelines, being an identity provider, being a data catalog of
record, authoring agents (the marketplace catalogues and governs agents authored elsewhere).

---

## 2. Non-negotiable invariants

Implement these as database constraints, publish-gate tests and CI checks — not as documentation.

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Exactly one active `kpi_definition` per (tenant, kpi_name) | Partial unique index + publish gate |
| I2 | A `quality_score_snapshot` without `rubric_version` is invalid | NOT NULL + write-path test |
| I3 | An `agent_version` cannot publish with fewer than 5 `demo_exchange` rows | Publish gate test |
| I4 | Every `agent_kpi_coverage` row cites an existing `kpi_definition` | FK + gate |
| I5 | `data_product.sensitivity_tier` is derived from columns, never written directly | Trigger/derived column + test |
| I6 | Every `mesh_edge_*` row has `confidence` and non-empty `rationale` | NOT NULL + render filter |
| I7 | `known_limitations` and agent `out_of_scope` must be non-empty and not "none" | Gate test |
| I8 | Connectors cannot write to any customer platform | Kill test against sandbox |
| I9 | Regenerating artifacts from manifests produces no diff | CI |
| I10 | No numeric threshold in application source | CI lint |
| I11 | Every agent numeric claim carries a resolvable citation | Groundedness eval, blocking at 100% |
| I12 | Effective agent access = intersection(agent scope, user entitlement) | Security suite |
| I13 | No brand string or raw hex colour outside token files | CI lint |
| I14 | Landing page CLS = 0 and ambient motion holds ≥58fps throttled | Lighthouse + Playwright trace |

---

## 3. Technology stack (pinned)

```
Frontend      Next.js 15 (App Router, React 19, TypeScript strict)
              Tailwind CSS + shadcn/ui, Recharts (charts), d3-force + canvas (mesh)
              Web Animations API for motion (no heavyweight animation library)
API           FastAPI (Python 3.12) + Pydantic v2, OpenAPI 3.1 generated from source
Workers       Python; durable workflows via Temporal (fallback: Postgres-backed job runner)
Datastore     PostgreSQL 16 + pgvector (canonical model, rubrics, workflow, audit, embeddings)
Cache/queue   Redis 7
Search        Hybrid: pgvector (semantic) + Postgres FTS (lexical), fused with RRF
MCP           Python MCP server per data product, generated from manifest
Agent runtime Adapter interface; reference implementation = Snowflake Cortex Agents
Data plane    Snowflake (reference connector); Databricks / Fabric / BigQuery adapters later
Telemetry     OpenTelemetry (traces, metrics, logs)
Auth          OIDC (Auth.js on the portal, JWT validation in API), SCIM for provisioning
Infra         Docker Compose for local; Terraform + Kubernetes for deploy
CI            GitHub Actions
```

Version-pin everything in `package.json` / `pyproject.toml`. No `^` ranges on runtime deps.

---

## 4. Repository layout

```
marketplace/
  manifests/
    products/        DP-*.yaml          # tool-neutral product + contract source of truth
    agents/          AG-*.yaml          # capability, coverage map, scope, demo exchanges
    kpis/            KPI-*.yaml         # exactly one authoritative definition per KPI
    rubrics/         quality.yaml ranking.yaml mesh.yaml demand.yaml value.yaml
                     agent_eval.yaml finops.yaml
    taxonomies/      industry.yaml domain.yaml archetype.yaml purpose.yaml sensitivity.yaml
  generated/         # DO NOT EDIT — every file header-stamped
    ddl/             canonical model migrations
    sql/             semantic views, governed views, DMF attachments
    mcp/             one server definition per product
    openapi/         openapi.json + generated SDKs
    types/           TypeScript types shared with the portal
  services/
    catalog/  search/  mesh/  quality/  workflow/  entitlement/  observability/
    value/  finops/  academy/  agent_registry/  demo_runner/  intake/  kpi_registry/
  connectors/
    snowflake/  databricks/  fabric/  bigquery/  collibra/  purview/  atlan/
    montecarlo/  soda/  okta/  slack/
  portal/            Next.js app
  seed/
    synthetic/       demo-tier data generators per product
    golden/          golden answers for the 70 demo exchanges
  tests/
    unit/ contract/ golden/ publish_gate/ kill/ security/ e2e/ perf/ a11y/
  docs/
    DECISIONS.md  RUNBOOKS/  ADR/
  scripts/
```

---

## 5. Environment and commands

`.env.example` (every variable required; app refuses to boot with a missing one):

```
PRODUCT_NAME=                       # display name, e.g. "Acme Data Exchange"
TENANT_ID=
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
OIDC_ISSUER=  OIDC_CLIENT_ID=  OIDC_CLIENT_SECRET=
SNOWFLAKE_ACCOUNT=  SNOWFLAKE_USER=  SNOWFLAKE_ROLE=MKT_READONLY  SNOWFLAKE_PRIVATE_KEY=
AGENT_RUNTIME=cortex|mock
MODEL_PROVIDER=  MODEL_ID=  MODEL_MAX_TOKENS=
DEMO_TIER_SCHEMA=MARKETPLACE_DEMO
OTEL_EXPORTER_OTLP_ENDPOINT=
FEATURE_FLAG_SOURCE=env|service
```

Required npm scripts (root workspace):

```
npm run dev            # docker compose up + api + portal + worker, seeded
npm run gen            # manifests -> generated/ (ddl, sql, mcp, openapi, types)
npm run migrate        # apply generated/ddl migrations
npm run seed           # load taxonomies, rubrics, KPIs, 15 products, 14 agents, synthetic data
npm run verify         # lint + typecheck + unit + contract + golden + publish_gate + a11y
npm run test:e2e       # signature journey
npm run test:perf      # lighthouse + motion frame-rate trace
npm run test:kill      # connector write-attempt kill test (requires sandbox creds)
npm run lint:no-magic-numbers
npm run lint:no-brand-strings
```

`npm run dev` must produce a fully browsable marketplace with the seed catalog and working
demo console **with zero manual setup steps** beyond `cp .env.example .env`.

---

## 6. Canonical data model

### 6.1 Entity groups

| Group | Entities |
|---|---|
| Reference | `tenant`, `industry`, `business_domain`, `product_archetype`, `sensitivity_tier`, `purpose_category`, `source_system` |
| Identity | `party` (person/team/service/agent), `org_unit`, `role_assignment` |
| Supply — data | `data_product`, `data_product_version`, `data_product_column`, `data_contract_version`, `contract_guarantee`, `endpoint` |
| Semantics | `kpi_definition`, `kpi_definition_version`, `glossary_term`, `kpi_synonym` |
| Supply — agents | `agent`, `agent_version`, `agent_kpi_coverage`, `agent_product_binding`, `agent_tool_binding`, `demo_exchange`, `evaluation_case`, `evaluation_run`, `prompt_artifact` |
| Quality | `quality_rule`, `quality_result`, `quality_score_snapshot`, `incident`, `incident_impact` |
| Lineage & mesh | `lineage_edge`, `mesh_edge_data`, `mesh_edge_agent` |
| Demand & workflow | `request`, `request_item`, `approval_step`, `decision`, `demand_vote`, `demand_theme`, `enhancement` |
| Entitlement | `entitlement_grant`, `grant_scope`, `purpose_binding`, `revocation` |
| Telemetry | `usage_event`, `usage_daily_agg`, `agent_interaction`, `answer_feedback`, `cost_allocation` |
| Value | `value_case`, `value_assumption`, `value_measurement` |
| Config | `rubric`, `rubric_version`, `rubric_criterion`, `policy`, `policy_version`, `feature_flag` |
| Academy | `academy_module`, `learning_path`, `enrollment`, `assessment_result`, `certification` |
| Audit | `audit_event`, `publication_snapshot` |

### 6.2 Key DDL

Full DDL is generated from `manifests/` at build time. These tables are the ones most likely
to be implemented wrong — implement them exactly as written.

```sql
CREATE TABLE data_product (
  product_id        TEXT PRIMARY KEY,            -- DP-<IND>-<NNN>
  tenant_id         TEXT NOT NULL REFERENCES tenant(tenant_id),
  name              TEXT NOT NULL,
  purpose           TEXT NOT NULL CHECK (length(purpose) BETWEEN 20 AND 400),
  industry_code     TEXT NOT NULL REFERENCES industry(code),
  domain_code       TEXT NOT NULL REFERENCES business_domain(code),
  archetype_code    TEXT NOT NULL REFERENCES product_archetype(code),
  sensitivity_tier  TEXT NOT NULL,               -- DERIVED from columns; see trigger below
  certification     TEXT NOT NULL CHECK (certification IN
                      ('certified','published','beta','deprecated')),
  owner_party_id    TEXT NOT NULL REFERENCES party(party_id),
  current_version   TEXT NOT NULL,
  known_limitations TEXT NOT NULL CHECK (
                      length(trim(known_limitations)) > 10
                      AND lower(trim(known_limitations)) NOT IN ('none','n/a','tbd')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- I5: sensitivity is derived, never written directly
CREATE FUNCTION derive_sensitivity(p_product_id TEXT) RETURNS TEXT AS $$
  SELECT COALESCE(MAX(t.rank_order), 1)::TEXT
  FROM data_product_column c JOIN sensitivity_tier t ON t.code = c.sensitivity_code
  WHERE c.product_id = p_product_id;
$$ LANGUAGE sql STABLE;
-- trigger recomputes on column insert/update/delete and on classification change

CREATE TABLE kpi_definition (
  kpi_id            TEXT PRIMARY KEY,            -- KPI-<DOMAIN>-<NNN>
  tenant_id         TEXT NOT NULL,
  kpi_name          TEXT NOT NULL,
  status            TEXT NOT NULL CHECK (status IN
                      ('draft','certified','deprecated','superseded')),
  business_definition TEXT NOT NULL,
  numerator_expr    TEXT, denominator_expr TEXT, expression TEXT,
  grains_supported  TEXT[] NOT NULL,
  slices_supported  TEXT[] NOT NULL,
  inclusions        TEXT[] NOT NULL DEFAULT '{}',
  exclusions        TEXT[] NOT NULL DEFAULT '{}',
  unit              TEXT NOT NULL, direction TEXT, target NUMERIC,
  source_of_record  TEXT REFERENCES data_product(product_id),
  steward_party_id  TEXT NOT NULL REFERENCES party(party_id),
  forum_approved_at DATE,
  superseded_by     TEXT REFERENCES kpi_definition(kpi_id),
  last_reviewed     DATE NOT NULL,
  review_months     INT  NOT NULL
);
-- I1: exactly one ACTIVE definition per name per tenant
CREATE UNIQUE INDEX kpi_one_active
  ON kpi_definition (tenant_id, lower(kpi_name))
  WHERE status IN ('draft','certified');

CREATE TABLE quality_score_snapshot (
  snapshot_id    TEXT PRIMARY KEY,
  product_id     TEXT NOT NULL REFERENCES data_product(product_id),
  rubric_version TEXT NOT NULL REFERENCES rubric_version(rubric_version_id),  -- I2
  composite      NUMERIC(5,2) NOT NULL,
  completeness NUMERIC(5,2), accuracy NUMERIC(5,2), freshness NUMERIC(5,2),
  consistency  NUMERIC(5,2), validity NUMERIC(5,2), uniqueness NUMERIC(5,2),
  band           TEXT NOT NULL,           -- resolved from rubric bands, never from code
  evidence_ref   JSONB NOT NULL,          -- rule_ids + results that produced this score
  computed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE ON quality_score_snapshot FROM app_role;   -- I6 append-only

CREATE TABLE agent_version (
  agent_version_id TEXT PRIMARY KEY,
  agent_id         TEXT NOT NULL REFERENCES agent(agent_id),
  semver           TEXT NOT NULL,
  status           TEXT NOT NULL CHECK (status IN ('draft','canary','published','retired')),
  autonomy_level   TEXT NOT NULL CHECK (autonomy_level IN ('L0','L1','L2','L3')),
  capability_statement TEXT NOT NULL CHECK (length(capability_statement) BETWEEN 90 AND 140),
  business_value_block TEXT NOT NULL,
  out_of_scope     TEXT[] NOT NULL CHECK (array_length(out_of_scope,1) >= 1),   -- I7
  model_provider TEXT NOT NULL, model_id TEXT NOT NULL, model_params JSONB NOT NULL,
  prompt_hash    TEXT NOT NULL REFERENCES prompt_artifact(prompt_hash),
  eval_run_id    TEXT REFERENCES evaluation_run(eval_run_id),
  published_at   TIMESTAMPTZ, published_by TEXT
);

CREATE TABLE agent_kpi_coverage (
  coverage_id       TEXT PRIMARY KEY,
  agent_version_id  TEXT NOT NULL REFERENCES agent_version(agent_version_id),
  kpi_id            TEXT NOT NULL REFERENCES kpi_definition(kpi_id),           -- I4
  source_product_id TEXT NOT NULL REFERENCES data_product(product_id),
  columns_used      TEXT[] NOT NULL,
  supported_grains  TEXT[] NOT NULL,
  supported_slices  TEXT[] NOT NULL,
  analysis_depth    TEXT NOT NULL CHECK (analysis_depth IN
                      ('report','compare','explain','rank_drivers','forecast')),
  eval_accuracy     NUMERIC(5,2), eval_sample_size INT,
  UNIQUE (agent_version_id, kpi_id)
);

CREATE TABLE demo_exchange (
  exchange_id      TEXT PRIMARY KEY,
  agent_version_id TEXT NOT NULL REFERENCES agent_version(agent_version_id),
  ordinal          INT  NOT NULL,
  question         TEXT NOT NULL,
  kpi_class        TEXT NOT NULL REFERENCES kpi_definition(kpi_id),
  analysis_type    TEXT NOT NULL,
  expected_shape   JSONB NOT NULL,        -- headline, visual, table_columns, must_cite[]
  data_tier        TEXT NOT NULL CHECK (data_tier IN ('demo','live')),
  max_latency_ms   INT NOT NULL,
  golden_answer_ref TEXT NOT NULL,
  tolerance_pct    NUMERIC(5,2) NOT NULL,
  last_validated   TIMESTAMPTZ,
  validation_state TEXT NOT NULL CHECK (validation_state IN ('passing','stale','failing')),
  UNIQUE (agent_version_id, ordinal)
);
-- I3 enforced in publish gate: COUNT(*) >= 5 AND all validation_state='passing'
--    AND last_validated > now() - interval '7 days'

CREATE TABLE mesh_edge_data (
  edge_id     TEXT PRIMARY KEY,
  product_a   TEXT NOT NULL REFERENCES data_product(product_id),
  product_b   TEXT NOT NULL REFERENCES data_product(product_id),
  edge_type   TEXT NOT NULL CHECK (edge_type IN ('shared_source','dependency',
                'shared_entity','shared_kpi','semantic','co_consumption')),
  strength    NUMERIC(4,3) NOT NULL CHECK (strength BETWEEN 0 AND 1),
  factors     JSONB NOT NULL,
  confidence  NUMERIC(4,3) NOT NULL,
  rationale   TEXT NOT NULL CHECK (length(trim(rationale)) > 10),               -- I6
  reviewed_by TEXT,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (product_a < product_b),
  CHECK (confidence >= 0.80 OR reviewed_by IS NOT NULL),
  UNIQUE (product_a, product_b, edge_type)
);

CREATE TABLE entitlement_grant (
  grant_id      TEXT PRIMARY KEY,
  request_id    TEXT NOT NULL REFERENCES request(request_id),
  principal_id  TEXT NOT NULL REFERENCES party(party_id),
  asset_type    TEXT NOT NULL CHECK (asset_type IN ('data_product','agent')),
  asset_id      TEXT NOT NULL,
  access_level  TEXT NOT NULL CHECK (access_level IN
                  ('read_metadata','read_data','read_data_pii','agent_invoke','write_back')),
  purpose_code  TEXT NOT NULL REFERENCES purpose_category(code),
  purpose_text  TEXT NOT NULL,
  platform_role TEXT NOT NULL,
  oauth_scopes  TEXT[] NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ, revocation_reason TEXT,
  last_used_at TIMESTAMPTZ
);
CREATE INDEX ON entitlement_grant (principal_id, asset_id) WHERE revoked_at IS NULL;
```

Add `tenant_id` and a row-level-security policy to **every** table. RLS is on by default;
a table without a policy fails the migration lint.

---

## 7. Manifest schemas

Manifests are the source of truth. Everything else is generated from them.

### 7.1 Data product manifest — `manifests/products/DP-TEL-001.yaml`

```yaml
apiVersion: marketplace/v1
kind: DataProduct
metadata:
  id: DP-TEL-001
  name: Subscriber Churn & Retention 360
  industry: telecommunications
  domain: customer
  archetype: consumer_aligned
  owner: { party_id: PTY-0031, team: "Telecom Customer Domain", escalation: "#dp-telecom" }
  certification: certified
spec:
  purpose: >
    Unified view of subscriber state, tenure, plan, usage, service events and churn outcome
    for retention decisioning.
  grain: "one row per subscriber per day"
  history_months: 36
  known_limitations: >
    Prepaid subscribers are excluded. Service events are joined on a 4-hour lag.
    Churn outcome is final only after the 30-day reconnection window closes.
  upstream_sources: [SRC-BILLING, SRC-CRM, SRC-NETWORK-USAGE, SRC-CARE-TICKETS]
  entities: [subscriber, account, plan, site]
  certified_kpis: [KPI-CHURN-001, KPI-RETEN-002, KPI-SAVE-003, KPI-TENURE-004, KPI-PROP-005]
  columns:
    - { name: subscriber_id, type: string, business_name: "Subscriber ID",
        nullable: false, classification: [pii, identifier], description: "..." }
    - { name: churn_flag, type: boolean, business_name: "Churned in period",
        nullable: false, classification: [], description: "..." }
    # ... full column list
  contract:
    version: 3.2.0
    schema_stability: additive_only
    guarantees:
      freshness:    { target: "06:00 local", p95_minutes: 45, measured: per_partition }
      availability: { target_pct: 99.5, window: monthly }
      completeness: { required_fields_pct: 99.9 }
      accuracy:     { reconciliation_variance_pct: 0.5, against: "billing_system_of_record" }
    deprecation_policy: { notice_days: 90, minimum_parallel_run_days: 30 }
    support: { hours: "24x5", p1_response_minutes: 30, on_call: "pagerduty://telecom-dp" }
    classification: { max_sensitivity: confidential, contains_pii: true, residency: [US, EU] }
    consumer_obligations:
      - "No redistribution outside the granted purpose"
      - "Re-derived KPIs must cite the certified definition ID"
    breach_process: "Auto-incident + consumer notification within 30 minutes of detection"
  quality_rules:
    - { id: QR-TEL-001-01, dimension: completeness, column: subscriber_id,
        rule: not_null, threshold_pct: 100, severity: critical }
    - { id: QR-TEL-001-02, dimension: uniqueness, columns: [subscriber_id, activity_date],
        rule: unique_at_grain, threshold_pct: 99.99, severity: critical }
    - { id: QR-TEL-001-03, dimension: freshness, rule: partition_completion_by,
        target: "06:00", tolerance_minutes: 45, severity: high }
    # completeness + freshness + validity are mandatory for every Tier-1 product
  endpoints: [sql, rest, mcp]
  demo_tier: { synthetic: true, rows_target: 250000, preserve: [distribution, seasonality,
               referential_integrity, cardinality] }
  value_case:
    business_outcome: >
      Retention teams target save offers at subscribers genuinely at risk instead of by
      tenure band.
    baseline: { method: "tenure-band targeting", analyst_hours_month: 120, captured: 2026-02 }
    benefit_model: "save_offer_precision_uplift * contribution_margin_per_retained - offer_cost"
    assumptions:
      - { text: "contribution margin per retained subscriber", value: 41.20,
          source: "finance FY26 model", dated: 2026-03-01 }
    attribution_confidence: medium
    review: { last_reviewed: 2026-07-14, reviewer: PTY-0031 }
```

### 7.2 Agent manifest — `manifests/agents/AG-TEL-001.yaml`

```yaml
apiVersion: marketplace/v1
kind: Agent
metadata:
  id: AG-TEL-001
  name: Churn Sentinel
  industry: telecommunications
  domain: customer
  owner: { party_id: PTY-0044, team: "Telecom Analytics", on_call: "pagerduty://tel-agents" }
  autonomy_level: L1
  certification: certified
spec:
  capability_statement: >
    Answers questions about subscriber churn, retention performance and save-offer targeting,
    and explains what is driving churn movement.
  business_value_block:
    analyses: [trend_explanation, variance_decomposition, driver_ranking,
               cohort_comparison, anomaly_triage]
    replaces: >
      Manual pull-and-pivot cycles by the retention analytics team, typically 2-3 days per
      churn review.
    personas: [retention_manager, regional_sales_director, cmo_staff]
  out_of_scope:
    - "Individual subscriber credit decisions"
    - "Pricing approval or plan change execution"
    - "Anything requiring billing write-back"
  runtime:
    provider: cortex
    model: { provider: anthropic, id: "<model-id>", temperature: 0.0, max_tokens: 2000 }
    prompt_ref: prompts/AG-TEL-001/system@v7
  data_products:
    - { product_id: DP-TEL-001, columns: [subscriber_id, segment, region, tenure_days,
        churn_flag, ltv, propensity_decile, contract_end_date], access: read }
    - { product_id: DP-TEL-002, columns: [site_id, region, impacted_subscriber_hours],
        access: read }
  tool_bindings:
    - { tool: query_subscriber_churn, endpoint: "mcp://.../dp/DP-TEL-001",
        scope: "dp:DP-TEL-001:read", cost_class: small, row_limit: 10000 }
    - { tool: get_kpi_definition, scope: "kpi:read", cost_class: trivial }
  kpi_coverage:
    - kpi_id: KPI-CHURN-001
      source_product: DP-TEL-001
      columns_used: [subscriber_id, churn_flag, segment, region, tenure_days]
      grains: [day, week, month, quarter]
      slices: [segment, region, plan_type, tenure_band, channel]
      analysis_depth: rank_drivers
    # ... one row per KPI answered
  guardrails:
    grounding: { require_citation_on_numerics: true, on_failure: return_error }
    injection_defence: v3
    output_filters: [pii_pattern, credential_pattern]
    refusal_policy: "State the boundary, name the covering agent or product, offer handoff."
  budgets: { p95_latency_ms: 6000, cost_per_answer_usd: 0.06 }
  demo_exchanges:
    - id: DEMO-AG-TEL-001-01
      ordinal: 1
      question: "What is our churn rate this quarter and how does it compare to last?"
      kpi_class: KPI-CHURN-001
      analysis_type: period_comparison
      expected_shape:
        headline: "single sentence with current rate, delta vs prior period, and the
                   concentration driving it"
        visual: line_with_delta_callout
        table_columns: [period, churn_rate, delta_pp, contribution_pct]
        must_cite: [DP-TEL-001, KPI-CHURN-001]
      data_tier: demo
      max_latency_ms: 6000
      golden_answer_ref: seed/golden/AG-TEL-001/q1.json
      tolerance_pct: 2.0
    # ... minimum 5, exactly 5 for every seed agent
  evaluation:
    suites: [golden_accuracy, groundedness, boundary_refusal, adversarial,
             entitlement, consistency, cost_latency]
    pass_threshold_pct: 92
    cases_ref: seed/eval/AG-TEL-001/
  value_case:
    benefit_model: "answered_questions * acceptance_rate * avg_manual_minutes / 60 * rate"
    assumptions:
      - { text: "avg manual minutes per churn driver question", value: 55,
          sample_size: 34, source: "analyst time study", dated: 2026-06-01 }
```

### 7.3 KPI manifest — `manifests/kpis/KPI-CHURN-001.yaml`

Structure as in Section 6.2 `kpi_definition`, plus `synonyms: []`. One file per KPI.
A second file with the same `kpi_name` fails `npm run gen` with a diff of the two definitions.

---

## 8. Rubrics as data

Seeded from YAML into `rubric` / `rubric_version` / `rubric_criterion`. **Changing a weight
must never require a code change.** Every consumer of a rubric resolves it by
`rubric_version_id` at read time and records that id with any score it produces.

### 8.1 `manifests/rubrics/quality.yaml`

```yaml
rubric: data_product_quality
version: 1.0.0
dimensions:
  - { code: completeness, weight: 0.20 }
  - { code: accuracy,     weight: 0.20 }
  - { code: freshness,    weight: 0.20 }
  - { code: consistency,  weight: 0.15 }
  - { code: validity,     weight: 0.15 }
  - { code: uniqueness,   weight: 0.10 }
archetype_overrides:
  document_corpus: { consistency: 0.00, uniqueness: 0.05, completeness: 0.30, accuracy: 0.25,
                     freshness: 0.25, validity: 0.15 }
bands:
  - { min: 90, code: exemplary,  label: "Exemplary" }
  - { min: 75, code: healthy,    label: "Healthy" }
  - { min: 60, code: watch,      label: "Watch" }
  - { min: 40, code: at_risk,    label: "At Risk" }
  - { min: 0,  code: unfit,      label: "Not Fit for Consumption" }
hard_blockers:
  - { when: "critical_rule_failed", caps_composite_at: 39 }
  - { when: "classified_column_unprotected", caps_composite_at: 49 }
below_band_actions:
  unfit: { flag_in_catalog: true, banner_on_attached_agents: true }
```

### 8.2 `manifests/rubrics/ranking.yaml`

```yaml
rubric: catalog_ranking
version: 1.0.0
weights:
  semantic_match: 0.35
  quality_normalized: 0.20
  active_consumers_90d_normalized: 0.15
  certification_multiplier: 0.15
  peer_affinity: 0.10
  staleness_penalty: -0.05
certification_multiplier: { certified: 1.0, published: 0.8, beta: 0.5, deprecated: 0.0 }
featured_ranking:
  formula: "adoption_velocity * quality_composite * recency_decay"
  min_cards: 12
  max_cards: 24
fusion: { method: rrf, k: 60 }
```

### 8.3 `manifests/rubrics/mesh.yaml`

```yaml
rubric: mesh_edges
version: 1.0.0
data_mesh_weights:
  source_overlap_jaccard: 0.30
  entity_overlap: 0.25
  kpi_overlap: 0.20
  semantic_similarity: 0.15
  co_consumption_lift: 0.10
render_threshold: 0.25
duplication_alert: { source_overlap_min: 0.80, semantic_similarity_min: 0.80 }
review_required_below_confidence: 0.80
agent_mesh_weights:
  shared_data_product: 0.35
  kpi_coverage_overlap: 0.30
  semantic_similarity: 0.15
  same_domain: 0.10
  co_usage_lift: 0.10
consolidation_candidate: { coverage_overlap_min: 0.70, shared_product_min: 0.70 }
co_consumption_session_minutes: 60
```

### 8.4 `manifests/rubrics/demand.yaml`

```yaml
rubric: demand_scoring
version: 1.0.0
criteria:
  - { code: business_value,     weight: 0.30 }
  - { code: consumer_breadth,   weight: 0.20 }
  - { code: strategic_alignment,weight: 0.15 }
  - { code: feasibility,        weight: 0.15 }
  - { code: reuse_leverage,     weight: 0.10 }
  - { code: risk_urgency,       weight: 0.10 }
duplicate_detection:
  weights: { embedding_match: 0.40, entity_overlap: 0.25,
             source_overlap: 0.20, kpi_overlap: 0.15 }
  blocking_threshold: 0.75
  advisory_threshold: 0.50
  architect_review_below_confidence: 0.80
theme_escalation: { distinct_teams_min: 5 }
```

### 8.5 `manifests/rubrics/value.yaml` and `finops.yaml`

```yaml
# value.yaml
rubric: value_model
version: 1.0.0
deflection:
  formula: "answered_questions * acceptance_rate * avg_manual_minutes / 60 * loaded_rate"
  avg_manual_minutes_by_question_class:      # reference data, resampled quarterly
    period_comparison:      { minutes: 25, sample_size: 41, dated: 2026-06-01 }
    driver_ranking:         { minutes: 55, sample_size: 34, dated: 2026-06-01 }
    cohort_comparison:      { minutes: 90, sample_size: 22, dated: 2026-06-01 }
    risk_cohort_targeting:  { minutes: 75, sample_size: 28, dated: 2026-06-01 }
    root_cause:             { minutes: 110, sample_size: 19, dated: 2026-06-01 }
  loaded_analyst_rate_usd_hour: 96
attribution_confidence: [high, medium, low]
value_case_review_months: 6

# finops.yaml
rubric: finops
version: 1.0.0
targets:
  cost_per_accepted_answer_vs_manual_max_ratio: 0.35
  value_ratio_min_after_4q: 3.0
  demo_tier_share_of_inference_max: 0.05
budgets: { soft_threshold_pct: 80, hard_threshold_pct: 100 }
cost_classes: { trivial: 1, small: 10, medium: 100, large: 1000 }   # relative units
dormant_grant_days: 60
retirement_candidate: { no_queries_days: 90 }
```
---

## 9. Generators

`npm run gen` reads `manifests/` and writes `generated/`. It is deterministic: same inputs,
byte-identical outputs. Every generated file starts with:

```
# AUTO-GENERATED FROM manifests/<path> BY scripts/gen.py — DO NOT EDIT
# generator_version: <semver>  manifest_hash: <sha256>  generated_at: <iso8601>
```

| Generator | Input | Output |
|---|---|---|
| `gen:ddl` | canonical model definition + manifests | `generated/ddl/NNNN_*.sql` migrations |
| `gen:sql` | product manifests | governed views, semantic views, DMF attachments per platform |
| `gen:mcp` | product manifests | `generated/mcp/DP-*.json` server definitions + Python server stubs |
| `gen:openapi` | FastAPI routes | `generated/openapi/openapi.json` + TS client |
| `gen:types` | canonical model | `generated/types/*.ts` shared with the portal |
| `gen:agentcard` | agent manifests | interop descriptor per agent |

CI step: `npm run gen && git diff --exit-code generated/`.

---

## 10. API specification

Base `/api/v1`. OpenAPI 3.1. Cursor pagination. RFC 7807 problem responses.
The portal is a client of this API with **no privileged path**.

### 10.1 Endpoints

```
GET    /products                          search + facets + ranking + cursor
GET    /products/{id}                     full listing (contract, endpoints, quality, adoption, value)
GET    /products/{id}/quality             current + history + contributing rule results
GET    /products/{id}/contract            source + conformance history + version diff
GET    /products/{id}/consumption         usage/adoption analytics within caller scope
GET    /products/{id}/mesh                neighbourhood: edges, strength, confidence, rationale
GET    /products/{id}/lineage             upstream + downstream
POST   /products                          create from manifest -> validation report
POST   /products/{id}/versions            publish new version -> runs publish gate

GET    /agents                            filter by industry, domain, kpi, product, autonomy
GET    /agents/{id}                       coverage map, scope, demo set, telemetry
GET    /agents/{id}/coverage              KPI coverage with eval accuracy + sample size
GET    /agents/{id}/demo                  curated exchanges + validation state
POST   /agents/{id}/ask                   execute question (tier, purpose) -> answer + trace
POST   /agents/{id}/feedback              acceptance/rejection + reason -> eval corpus
GET    /agents/{id}/evaluation            suite results, pass rate, regression history

GET    /kpis                              certified KPI register + synonyms
GET    /kpis/{id}                         definition, versions, consumers (products + agents)
GET    /kpis/{id}/divergence              cross-agent / cross-product reconciliation results

GET    /mesh/data     GET /mesh/agents    graphs with filters, thresholds, layout hints
GET    /mesh/data/blast-radius?source=    downstream products + agents + consumer counts

POST   /requests/access                   -> evaluated approval path + SLA before submission
POST   /requests/enhancement
POST   /requests/supply                   -> duplicate-match candidates with similarity
GET    /requests   GET /requests/{id}
POST   /requests/{id}/decision            approve | decline | partial (+ required reason)

GET    /entitlements                      caller's grants, or full register for security roles
DELETE /entitlements/{id}                 self-revoke or admin revoke

GET    /demand      POST /demand/{id}/vote      (vote requires a use-case line)
GET    /observability/{assetType}/{id}
GET    /value/{assetType}/{id}
GET    /finops/{assetType}/{id}
GET    /academy/paths   POST /academy/enrollments
GET    /admin/rubrics   POST /admin/rubrics/{id}/versions
GET    /events/stream                     SSE: anonymised activity for the front page ticker
```

### 10.2 Agent invocation contract

```jsonc
// POST /api/v1/agents/AG-TEL-001/ask
{ "question": "Which segments drove the churn increase last quarter?",
  "tier": "live",                      // "demo" | "live"
  "purpose": "churn-analysis-emea",
  "session_id": "sess_..." }

// 200
{ "answer": {
    "headline": "...",
    "narrative": "...",
    "visual": { "type": "bar", "spec": { } },
    "table":  { "columns": [], "rows": [] } },
  "citations": [ { "product_id": "DP-TEL-001", "contract_version": "3.2.0",
                   "columns": ["segment","churn_flag"], "as_of": "2026-09-03T06:12:00Z" } ],
  "kpi_definitions": ["KPI-CHURN-001"],
  "trace": { "tool_calls": [ ], "rows_scanned": 184203, "latency_ms": 4120,
             "tokens": { "in": 3820, "out": 640 }, "cost_usd": 0.031 },
  "grounded": true, "confidence": 0.91,
  "scope": { "agent_identity": "svc-agent-tel-001", "on_behalf_of": "u-48231",
             "effective_scope": "intersection" } }

// 422 out of scope — never an ungrounded guess
{ "type": "out_of_scope",
  "detail": "This agent does not cover network fault codes.",
  "suggested_agents": ["AG-TEL-002"], "file_demand_url": "/requests/new/supply?..." }

// 424 ungrounded — the model produced a numeric claim without a resolvable citation
{ "type": "ungrounded_answer", "detail": "Answer withheld: 2 numeric claims lacked citations." }
```

**Hard rule:** grounding is validated in the API layer after the model returns and before the
response is serialised. An ungrounded answer is never sent to a client.

### 10.3 403 contract

Every 403 returns the exact missing scope and a deep link to a pre-filled access request:

```json
{ "type": "entitlement_missing", "required_scope": "dp:DP-TEL-001:read",
  "request_access_url": "/requests/new/access?asset=DP-TEL-001&surface=mcp" }
```

---

## 11. MCP surface

One generated MCP server per data product. Tools are typed and derived from the contract.

```jsonc
{
  "server": "mcp://marketplace.${TENANT}.internal/dp/DP-TEL-001",
  "product": { "id": "DP-TEL-001", "version": "3.2.0",
               "sensitivity": "confidential", "contains_pii": true },
  "auth": { "type": "oauth2", "flow": "client_credentials",
            "scopes": ["dp:DP-TEL-001:read"], "identity": "agent" },
  "tools": [
    { "name": "query_subscriber_churn",
      "description": "Return churn metrics by segment, region and period.",
      "input_schema": { "period": "string", "segment": "string?", "region": "string?",
                        "grain": "enum[day,week,month]" },
      "returns": "rows + certified KPI definition IDs + freshness_as_of",
      "row_limit": 10000, "cost_class": "small" },
    { "name": "describe_schema",    "description": "Columns, types, classifications." },
    { "name": "get_kpi_definition", "description": "Authoritative definition by KPI ID." },
    { "name": "get_freshness",      "description": "Load state vs contract SLA." },
    { "name": "get_quality",        "description": "Current composite and dimension scores." }
  ],
  "policy": { "row_filters_applied": true, "column_masking_applied": true,
              "purpose_required": true, "max_rows_per_call": 10000,
              "audit": "agent_id, user_on_behalf_of, purpose, columns_returned" }
}
```

Implementation rules:

- Policy is enforced **server-side in the data platform**, never by the calling agent.
- Every response carries provenance: product id, contract version, `freshness_as_of`,
  quality composite, KPI definition ids used.
- Purpose is mandatory for Confidential and Restricted products; a missing or unbound purpose
  fails closed at the gateway.
- Delegated identity is preserved and both identities are logged; effective entitlement is the
  **intersection** of agent scope and user entitlement.

---

## 12. Portal routes and surfaces

```
/                            Landing (see Section 13 for motion)
/discover                    Universal search across products, agents, KPIs, glossary
/data-products               Catalog: facet rail, grid/table/compare
/data-products/[id]          8 tabs: Overview | Schema | Quality | Contract |
                             Endpoints | Lineage & Mesh | Consumption | Value
/agents                      Agent catalog: facets incl. "KPI answered"
/agents/[id]                 7 tabs: Overview | Capabilities | Demo | Data Products |
                             Safety & Scope | Observability | Value
/agents/[id]/demo            Full-screen demo console
/mesh/data                   Data product mesh explorer
/mesh/agents                 Agent mesh explorer
/requests                    My requests | Approvals queue | SLA board
/requests/new/access|enhancement|supply
/demand                      Public demand board with voting and clustering
/observability               Health plane for products and agents
/academy                     Learning paths, sandboxes, certification
/console/owner               Adoption, backlog, contract, incidents
/console/steward             Certification + low-confidence review queues
/admin                       Rubrics, taxonomies, connectors, tenancy, flags
```

Component rules:

- Server components by default; client components only where interaction demands it.
- **Every component ships five states**: loading, empty, error, partial-permission, populated.
  Partial-permission is the common case (a consumer sees an asset they cannot yet query).
- Card anatomy is fixed — 12 elements in fixed positions for products, 6 zones for agents.
  Consistency is what makes the grid scannable; no per-card variation.
- Catalog empty state is never a dead end: nearest semantic matches + related demand items +
  a CTA to file a new-supply request pre-filled with the query.

---

## 13. Front page — moving visuals (implementation spec)

This is the highest-visibility surface and the easiest to build badly. Build the **motion
controller first**, then the visuals on top of it.

### 13.1 Motion controller (`portal/lib/motion/controller.ts`)

A single global controller. Components register animations with it; no component starts its
own `requestAnimationFrame` loop.

```ts
type MotionClass = 'ambient' | 'reactive' | 'narrative';

interface MotionRegistration {
  id: string;
  klass: MotionClass;
  el: HTMLElement;
  start(): void; pause(): void; resume(): void; renderStatic(): void;
}

// The controller pauses ALL ambient motion when any of these is true:
//   prefers-reduced-motion  |  document.hidden  |  Save-Data header
//   |  navigator.getBattery().level < 0.20  |  viewport < 640px
//   |  user pressed the global "Reduce motion" control (persisted per user)
// On pause it calls renderStatic() so the frame is composed, not frozen mid-transition.
// Off-screen elements (IntersectionObserver) schedule zero frames.
```

Motion tokens live in `portal/styles/tokens/motion.css`:

```css
--duration-micro: 120ms;  --duration-base: 240ms;  --duration-slow: 480ms;
--ease-standard: cubic-bezier(.2,0,0,1);
--ease-entrance: cubic-bezier(.05,.7,.1,1);
--ease-exit:     cubic-bezier(.3,0,.8,.15);
--ribbon-speed-row1: 32; /* px per second */
--ribbon-speed-row2: 24;
--constellation-drift-alpha: 0.02;
--orbit-deg-per-sec-min: 0.6;  --orbit-deg-per-sec-max: 1.1;
--theatre-type-cps: 45;
```

**Only `transform` and `opacity` may be animated.** `npm run lint:animatable-props` fails the
build on animation of width, height, top, left, box-shadow, filter or background-position.

### 13.2 Living data product ribbon (`components/landing/ProductRibbon.tsx`)

- Two rows of product cards travelling in opposite directions: row 1 right-to-left at
  `--ribbon-speed-row1`, row 2 left-to-right at `--ribbon-speed-row2`. Different speeds so the
  rows do not read as one block.
- Cards are the standard catalog card at 88% scale.
- Content from `GET /products?featured=true`, ordered by `featured_ranking` in the ranking
  rubric. 12–24 cards per row. Re-fetch every 5 minutes and **cross-fade**, never hard-swap.
- Loop: duplicate the track once, animate a single composited layer per row with the Web
  Animations API translating `translate3d(-Xpx,0,0)`, reset at exactly one track width so the
  seam is invisible. **One animation per row, not per card. No scroll-position hacks.**
- Pointer enter or keyboard focus anywhere in a row pauses that row within 120ms and lifts the
  hovered card 4px. Leaving resumes **from the paused position**, not from the start.
- Semantics: `<ul role="list">` with `<li>` cards; tab moves card to card in DOM order and
  pauses motion while focus is inside. A visible Pause/Play control sits top-right of the band
  (WCAG 2.2.2 — required for motion longer than 5s).
- Quality ring sweeps 0 → score over 700ms with the number counting in parallel, **once** on
  first viewport entry. It does not re-animate on each loop pass.
- Reduced motion: static three-across grid of the top six cards + "Browse all products" link.
- API failure: render last cached payload with an as-of stamp; with no cache, collapse the band.
  Never render skeletons on the marketing page.

### 13.3 Agent constellation / hero mesh (`components/landing/Constellation.tsx`)

- Data: `GET /mesh/data?scope=featured` (≤60 product nodes + edges above render threshold) and
  `GET /agents?live=true`. **Real identifiers and real edges** — never a decorative fake graph.
- Layout: run `d3-force` **server-side**, pre-warmed 300 ticks, ship fixed coordinates so the
  client paints the settled layout immediately. Client then runs a damped simulation at
  `alpha = --constellation-drift-alpha` for gentle drift only.
- Agent satellites: each agent glyph orbits the centroid of the products it consumes at
  0.6–1.1 deg/sec with a per-agent phase offset. A two-product agent traces an ellipse between
  them — this makes multi-product agents legible without a legend.
- Answer pulses: on an event from `GET /events/stream` (SSE), animate a pulse along the
  agent→product edge over 900ms. Rate-limit to **6 pulses/sec** so the hero never strobes.
  In demo tier, replay a recorded event stream.
- Encoding (identical to the full mesh explorer, so the vocabulary is learned once):
  radius = log(active consumers) clamped 3–14px; colour = quality band; ring = certification;
  slow amber pulse = open incident.
- Interaction: hover/focus freezes drift, dims non-neighbours to 20%, shows a peek card
  (name, quality, consumers, attached agents). Click navigates. **Never captures scroll.**
- Rendering: SVG below 150 nodes; single `<canvas>` with quadtree hit-testing above that;
  `OffscreenCanvas` + worker where available. WebGL only above 1,500 rendered nodes.
- LOD: <900px viewport → nodes only, no edges. <640px → static gradient + one composed image.
- Text protection: constellation capped at 12% opacity behind copy, plus a navy scrim
  guaranteeing 4.5:1 contrast. **CI asserts the contrast on the rendered hero.**
- Reduced motion: one settled frame, no drift, no orbit, no pulses. Hover highlight remains
  (it is input-driven, not ambient).

### 13.4 Live answer theatre (`components/landing/AnswerTheatre.tsx`)

Choreography, total 14–18s then a 4s hold:

```
type question at --theatre-type-cps with blinking caret (900ms)
  -> 400ms thinking indicator naming the tool being called
  -> headline streams token by token
  -> chart draws over 600ms, bars growing from the axis
  -> table rows fade in, 24ms stagger
  -> citation chips + as-of stamp slide up last
```

- **Provenance is honest.** Unauthenticated visitors see a replay of a *recorded real
  execution trace* — actual tokens, tool calls, latency, cost — stamped `recorded <date>`.
  Traces are re-recorded by the nightly validation job so a stale trace cannot survive a
  regression. Authenticated users get live execution against the demo tier.
  **Fabricated answers are prohibited in both modes.**
- Controls: pause, restart, previous/next exchange, question picker. All keyboard operable.
  The loop stops permanently after 3 cycles without interaction.
- The tool-trace right rail is **visible by default**, not behind a toggle.
- Reduced motion: render the completed answer instantly, chart already drawn, no typing.

### 13.5 Counters and activity ticker

- Counters count up 0 → value over 1,200ms with `--ease-entrance`, once, on viewport entry.
  Values from a cached aggregate refreshed every 30s; changed values tumble digit-by-digit.
- Activity ticker: slow vertical crawl of anonymised events ("a retail data product was
  certified", "an access request was provisioned in 3 hours"). **Never** a person's name, an
  asset above Internal sensitivity, or a customer identifier.
- Suppression rule: no ticker event derived from fewer than 5 underlying occurrences —
  otherwise the ticker becomes a side channel onto one team's activity.
- If the event channel is down, the ticker hides. A frozen stale ticker is worse than none.

### 13.6 Motion budget (CI-enforced)

| Metric | Budget |
|---|---|
| Sustained frame rate | ≥58fps with all ambient motion, 4x CPU throttle |
| Main-thread work per frame | ≤4ms; zero layout/paint in animation frames |
| CLS on landing | 0.00 — ribbon, constellation, theatre reserve exact boxes pre-paint |
| INP with motion running | ≤200ms |
| Off-screen / hidden cost | zero scheduled frames |
| Motion layer bundle | ≤45KB gzipped including the graph renderer |
| Reduced motion | every ambient animation has a static equivalent carrying the same information |

---

## 14. Workflow engine

One engine, three request types. Durable execution — approvals must survive restarts.

### 14.1 Access request

```
Draft -> PolicyEvaluated -> Submitted -> {Approved | PartiallyApproved | Declined | Blocked}
      -> Provisioned -> Active -> {Renewed | Expired | Revoked}
```

Policy evaluation runs **before submission** and shows the consumer exactly what will happen:

| Path | Condition | SLA |
|---|---|---|
| Auto-approve | role in product pre-approved list, sensitivity ≤ Internal, no PII, permitted purpose | immediate |
| Owner | default for Internal and Confidential | 2 business days |
| Owner + steward | Confidential with classified columns | 3 business days |
| Owner + privacy + security | Restricted, cross-border, or any PII grant | 5 business days |
| Blocked | hard policy violation (residency, licence, SoD) | returns the policy + an alternative asset from the mesh where a lower-sensitivity equivalent exists |

Provisioning on approval is mechanical — nobody edits a role by hand:

```
1. resolve platform role            -> MKT_<PRODUCT>_<LEVEL>
2. grant scoped role to principal   -> via connector (Snowflake / UC / IAM)
3. apply masking + row policy       -> inherited from product classification
4. bind purpose + expiry to grant   -> entitlement register
5. issue OAuth scopes               -> dp:<id>:read, agent:<id>:invoke
6. notify consumer                  -> runbook, endpoints, quickstart, academy module
7. write immutable audit record

on_expiry_minus_14d : notify consumer + owner, offer one-click renewal
on_expiry           : revoke automatically, retain audit record
on_no_use_60d       : flag dormant grant to the approver who granted it
```

Escalation: unattended request escalates to the domain steward at 80% of SLA and to the
architect at breach. Partial approval requires a reason returned to the requester.
Every decision records actor, timestamp, decision, reason and policy version in force.

### 14.2 Enhancement request

```
Submitted -> Triaged (SLA 5 business days) -> Assessed
          -> {Accepted | Declined(reason from controlled list) | Merged}
          -> Scheduled -> InProgress -> Delivered -> Verified
```

Declines are public and require a controlled reason (out of scope, source unavailable, cost
prohibitive, duplicate, superseded, security constraint) plus free text. Merge carries all
requesters' votes forward. Unverified items auto-close at 14 days as delivered with a note.

### 14.3 Demand intake

```
Submitted -> DuplicateReview -> Triaged -> Scored -> Roadmapped -> InBuild -> Delivered
          |                                                                 -> Declined(public reason)
```

Duplicate-supply detection at submission (weights from `demand.yaml`):

```
similarity = 0.40*embedding_match(request_text, product.purpose + kpi_definitions)
           + 0.25*entity_overlap + 0.20*source_overlap + 0.15*kpi_overlap

>= 0.75  -> BLOCKING review with the owner; candidate shown side by side
0.50-0.74-> advisory panel; requester may proceed
< 0.50   -> proceed to scoring
Every match stores {candidate_id, similarity, contributing_factors, confidence, rationale}.
Matches below 0.80 confidence go to architect review before being shown as blocking.
```

Votes require a one-line use case (a vote without context is not counted — the use case is
what makes clustering possible). A theme with ≥5 distinct requesting teams auto-escalates.
An accepted demand item generates a **draft** manifest with confidence and rationale on every
inferred field. Never auto-approved.

---

## 15. Engines

### 15.1 Quality scoring

```
criterion_score = normalize(rule_results)                      # 0..100
dimension_score = weighted_sum(criterion_scores)               # weights from rubric
composite       = weighted_sum(dimension_scores)               # archetype override applies
apply hard_blockers (caps)                                     # rubric data
band            = resolve_band(composite)                      # rubric data
write quality_score_snapshot { rubric_version, evidence_ref }  # immutable
```

Tier weighting: Tier-1 assets dominate the denominator so a thousand hygienic sandbox tables
cannot mask ungoverned crown jewels. **Golden test:** pinning an evidence set and a rubric
version must reproduce a prior composite exactly, for at least three historical snapshots.

### 15.2 Mesh computation

Nightly full recompute + incremental on lineage or manifest change.

```
data edge_strength = 0.30*source_overlap_jaccard + 0.25*entity_overlap + 0.20*kpi_overlap
                   + 0.15*semantic_similarity + 0.10*co_consumption_lift
agent edge_strength = 0.35*shared_data_product + 0.30*kpi_coverage_overlap
                    + 0.15*semantic_similarity + 0.10*same_domain + 0.10*co_usage_lift
render if strength >= render_threshold
store {type, strength, factors, confidence, rationale, computed_at}
confidence < 0.80 -> hold for review, do not render
```

Explorer modes to implement: force-directed / domain-clustered / source-anchored layouts;
blast-radius (select a source system, highlight all downstream products and agents with
consumer counts); duplication (high-similarity edges only, with candidate consolidations);
gap (overlay demand themes). **Every mesh view has a keyboard-navigable table equivalent** —
the graph is never the only path to the information.

### 15.3 Agent registry, publish gate, demo runner

Publish gate (all blocking, implemented as executable tests, result rendered on the agent page):

```
[ ] capability_statement 90-140 chars, business_value_block present, out_of_scope non-empty
[ ] coverage map complete: every row cites an existing certified KPI + source product + columns
[ ] >= 5 demo exchanges, each validated against its golden answer within tolerance in <= 7 days
[ ] entitlement scope approved; no reachable column carries a tag the scope does not permit
[ ] compositional exposure check passed where the agent invokes other agents
[ ] evaluation suite present, current run above declared threshold
[ ] groundedness: zero uncited numeric claims across the evaluation corpus
[ ] owner, on-call rotation, escalation path recorded; value case authored with assumptions
```

Demo runner executes the **real** agent against demo-tier synthetic data. A recorded or
hardcoded answer is a build failure. Nightly job re-runs all curated questions against golden
answers; a failure marks the exchange `stale`, removes it from the front-page theatre and
notifies the owner.

### 15.4 AgentOps evaluation harness

Suites (all blocking except `consistency`): `golden_accuracy`, `groundedness` (100% required),
`boundary_refusal`, `adversarial` (injection via retrieved content, tool output and user
input), `entitlement` (run under ≥3 synthetic personas of differing entitlement — the agent
must return strictly less, never more, and must not leak the existence of masked columns),
`compositional_exposure`, `consistency` (advisory, publish variance), `cost_latency`.

Release path: author → evaluate (diff vs previous version attached to the PR) → review
(security review required if scope, tool bindings or model provider changed) → canary at 10%
traffic, minimum 200 answers or 48h → promote or roll back → record to audit + Safety tab.
An agent version is an immutable bundle pinning model, params, prompt hash, tool bindings,
upstream contract versions, KPI definition versions, guardrail config and the eval run.

### 15.5 KPI registry and divergence detection

| Check | Frequency | On failure |
|---|---|---|
| Cross-agent agreement on a shared KPI | daily | incident against **both** agents, banner on both listings |
| Cross-product agreement on a shared KPI | daily | incident against both products, mesh shared-KPI edge flagged |
| Semantic layer conformance | on deploy | block the deploy |
| BI reconciliation | weekly | curation finding, never a silent overwrite |
| Orphan measure detection | weekly | steward triage queue |

### 15.6 Observability and incidents

Product signals: freshness, volume, schema, quality, distribution drift, pipeline, access
(permission-denied rate = leading indicator of entitlement gaps), cost.
Agent signals: answer quality, groundedness, coverage/refusal, performance, cost, upstream
health, eval drift, safety (any scope-violation attempt is a security event).

Incident lifecycle: detect → **compute** severity from blast radius (downstream consumer count
× sensitivity tier × guarantee breached) → notify owner and affected consumers → banner every
affected listing → track to resolution → publish root cause → link permanently to the asset's
quality history. Owners **cannot suppress** consumer notification; they can only add context.

### 15.7 Value and FinOps

```
deflected_hours = answered_questions * acceptance_rate * avg_manual_minutes[class] / 60
deflected_value = deflected_hours * loaded_analyst_rate
net_value       = deflected_value - (inference + platform + stewardship cost)

cost_per_answer          = inference + retrieval + query cost
cost_per_accepted_answer = cost_per_answer / acceptance_rate
value_ratio              = realized_value / total_cost_of_ownership
```

`avg_manual_minutes` is reference data with sample size and date, resampled quarterly, and the
sample size is **displayed next to any figure derived from it**. Never a hardcoded constant.

Portfolio views: value-vs-cost quadrant, adoption cohort curves by publication quarter,
retirement candidates (no queries in 90 days + non-trivial cost, with the saving quantified),
unmet demand value, and a generated board pack (PDF/PPTX) read from the same snapshot as the
dashboard so the two cannot disagree.
---

## 16. Seed catalog — 15 data products

Author one manifest per row in `manifests/products/`. Every one gets a full contract, column
list, quality rules (completeness + freshness + validity minimum), endpoints, adoption profile
and value case. Quality and freshness values below are demo-tier seeds; in a live deployment
they are computed from telemetry.

| ID | Product | Industry / Domain | Grain | Certified KPIs | Freshness | Quality | Sensitivity | Surfaces |
|---|---|---|---|---|---|---|---|---|
| DP-TEL-001 | Subscriber Churn & Retention 360 | Telecom / Customer | subscriber-day, 36m | Churn Rate, Retention Rate, Save Rate, Avg Tenure, Churn Propensity Decile | Daily 06:00 p95 45m | 94 | Confidential (PII) | SQL, REST, MCP |
| DP-TEL-002 | Network Experience & Fault Signal | Telecom / Network & Asset | site-hour, 13m | Network Availability, Dropped Call Rate, Throughput p50/p95, Fault MTTR, Impacted Subscriber Hours | Hourly p95 12m | 88 | Internal | SQL, MCP, Stream |
| DP-TCH-001 | Product Usage & Feature Adoption | Technology / Product | account-feature-day, 24m | DAU/MAU, Feature Adoption Rate, Activation Rate, Time to Value, NRR | Hourly p95 20m | 91 | Internal | SQL, REST, MCP |
| DP-BNK-001 | Customer Financial 360 | Banking / Customer | customer-month, 60m | Primary Bank Share, Products per Customer, CLV, Attrition Risk Score, Deposit Balance Growth | Daily 05:00 p95 60m | 96 | Restricted (PII) | SQL, MCP, Share |
| DP-BNK-002 | Transaction Surveillance & Financial Crime Signal | Banking / Risk & Compliance | alert-disposition, 84m | Alert Volume, False Positive Rate, SAR Conversion Rate, Investigation Cycle Time, Backlog Age | 15 min p95 6m | 93 | Restricted | SQL, MCP |
| DP-INS-001 | Claims Lifecycle & Loss Performance | Insurance / Risk | claim-status-transition, 84m | Loss Ratio, Claims Cycle Time, Average Severity, Leakage Rate, Recovery Rate | Daily 04:00 p95 40m | 90 | Confidential (PII) | SQL, REST, MCP |
| DP-INS-002 | Policy & Underwriting Portfolio | Insurance / Product | policy-month, 84m | Written Premium, Policy Retention, Quote-to-Bind Rate, Rate Adequacy, Exposure Concentration | Daily 04:30 p95 35m | 89 | Confidential | SQL, MCP |
| DP-HLT-001 | Patient Care Journey & Readmission | Healthcare / Clinical | encounter + journey, 60m | 30-Day Readmission Rate, Avg Length of Stay, ED Utilization Rate, Care Gap Closure, Discharge-to-Follow-up Interval | 4 hourly p95 25m | 92 | Restricted (PHI) | SQL, MCP |
| DP-HLT-002 | Pharmacy & Clinical Supply Utilization | Healthcare / Supply Chain | item-location-day, 36m | Formulary Adherence, Stockout Rate, Cost per Patient Day, Waste Rate, Substitution Rate | Daily 03:00 p95 30m | 87 | Confidential | SQL, REST, MCP |
| DP-RTL-001 | Omnichannel Sales & Basket Analytics | Retail / Customer | transaction-line, 36m | Comparable Sales Growth, Average Basket Value, Conversion Rate, Gross Margin Rate, Promotion Lift | Hourly p95 15m | 95 | Internal | SQL, REST, MCP |
| DP-RTL-002 | Inventory Position & Replenishment Signal | Retail / Supply Chain | sku-location-day, 24m | In-Stock Rate, Weeks of Supply, Sell-Through Rate, Forecast Accuracy (MAPE), Lost Sales Estimate | 2 hourly p95 18m | 89 | Internal | SQL, MCP, Stream |
| DP-TRN-001 | Fleet Movement & Delivery Performance | Transportation / Operations | shipment-leg, 36m | On-Time Delivery Rate, Cost per Mile, Dwell Time, Asset Utilization, Exception Rate | 30 min p95 8m | 86 | Internal | SQL, MCP, Stream |
| DP-UTL-001 | Grid Asset Health & Outage | Utilities / Network & Asset | asset-day + outage events, 84m | SAIDI, SAIFI, Asset Health Index, Avg Restoration Time, PM Compliance | 15 min p95 7m | 91 | Internal | SQL, MCP, Stream |
| DP-ENG-001 | Smart Meter Consumption & Load Profile | Utilities & Energy / Customer | meter-interval, 24m | Peak Demand, Load Factor, Consumption per Customer, DR Event Response Rate, Estimated Read Rate | Daily 02:00 p95 50m | 88 | Confidential (PII) | SQL, MCP |
| DP-MFG-001 | Manufacturing Yield & Equipment Effectiveness | Manufacturing / Operations | run-line-shift, 36m | OEE, First Pass Yield, Unplanned Downtime Hours, Scrap Rate, Changeover Time | Per shift close p95 20m | 90 | Internal | SQL, REST, MCP |

---

## 17. Seed catalog — 14 agents

| ID | Agent | Industry | Products | L | Explicitly out of scope |
|---|---|---|---|---|---|
| AG-TEL-001 | Churn Sentinel | Telecom | DP-TEL-001, DP-TEL-002 | L1 | individual credit decisions; pricing approval; billing write-back |
| AG-TEL-002 | Network Quality Advisor | Telecom | DP-TEL-002 | L1 | radio parameter changes; work-order creation; capital planning approval |
| AG-TCH-001 | Product Adoption Analyst | Technology | DP-TCH-001 | L1 | contract or pricing commitments; individual user behaviour without consent basis |
| AG-BNK-001 | Relationship Value Advisor | Banking | DP-BNK-001 | L1 | credit decisions; suitability advice; individual recommendations without banker review |
| AG-BNK-002 | Financial Crime Triage | Banking | DP-BNK-002 | L2 | filing a SAR; closing an alert; naming a customer as suspicious |
| AG-INS-001 | Claims Leakage Investigator | Insurance | DP-INS-001, DP-INS-002 | L1 | coverage determination; settlement authority; adjuster performance ratings |
| AG-INS-002 | Underwriting Portfolio Copilot | Insurance | DP-INS-002 | L1 | binding authority; rate filing; individual risk acceptance |
| AG-HLT-001 | Readmission Risk Navigator | Healthcare | DP-HLT-001 | L1 | any individual clinical recommendation, diagnosis, treatment or patient-level advice |
| AG-HLT-002 | Pharmacy Utilization Agent | Healthcare | DP-HLT-002 | L2 | clinical substitution decisions; ordering without pharmacist approval |
| AG-RTL-001 | Merchandising Performance Agent | Retail | DP-RTL-001, DP-RTL-002 | L1 | price changes; markdown execution; vendor negotiation positions |
| AG-RTL-002 | Inventory Availability Agent | Retail | DP-RTL-002 | L2 | executing transfers or POs without planner approval |
| AG-TRN-001 | Delivery SLA Sentinel | Transportation | DP-TRN-001 | L1 | dispatch changes; carrier contracting; driver performance actions |
| AG-UTL-001 | Outage Impact Analyst | Utilities & Energy | DP-UTL-001, DP-ENG-001 | L1 | switching orders; crew dispatch; regulatory filings |
| AG-MFG-001 | Yield & Downtime Analyst | Manufacturing | DP-MFG-001 | L1 | equipment parameter changes; maintenance scheduling without planner approval |

---

## 18. Demo question bank — 70 exchanges (5 per agent)

Author these into each agent manifest under `demo_exchanges`, and a golden answer per
question under `seed/golden/<AGENT>/qN.json`. `analysis_type` drives `expected_shape.visual`.

```yaml
AG-TEL-001:
  1: { q: "What is our churn rate this quarter and how does it compare to last?",
       analysis: period_comparison,   visual: line_with_delta_callout }
  2: { q: "Which customer segments drove the churn increase last quarter?",
       analysis: driver_ranking,      visual: waterfall }
  3: { q: "Are network issues contributing to churn in the Midwest?",
       analysis: correlation,         visual: scatter_plus_table }
  4: { q: "Which subscribers should we prioritise for a save offer this week?",
       analysis: cohort_targeting,    visual: ranked_table }
  5: { q: "Did the May retention campaign actually work?",
       analysis: cohort_comparison,   visual: dual_line }

AG-TEL-002:
  1: { q: "Which sites had the worst customer impact yesterday?",        analysis: impact_ranking,   visual: bar_plus_map }
  2: { q: "What is driving the throughput drop in the Denver cluster?",  analysis: root_cause,       visual: timeseries_overlay }
  3: { q: "How does availability compare across regions this month?",    analysis: comparison,       visual: small_multiples }
  4: { q: "Which faults are recurring on the same assets?",              analysis: pattern_detection,visual: table }
  5: { q: "What is our MTTR trend and where is it worst?",               analysis: trend_segmented,  visual: line_plus_box }

AG-TCH-001:
  1: { q: "Which features are driving activation this quarter?",             analysis: driver_ranking,    visual: bar_plus_funnel }
  2: { q: "Which accounts show adoption decline ahead of renewal?",          analysis: risk_cohort,       visual: ranked_table }
  3: { q: "How long does a new account take to reach first value?",          analysis: distribution,      visual: histogram_segmented }
  4: { q: "Did the March onboarding change improve activation?",             analysis: cohort_comparison, visual: cohort_curve }
  5: { q: "Which features have high usage but low entitlement coverage?",    analysis: gap_analysis,      visual: matrix }

AG-BNK-001:
  1: { q: "Who are my top 20 households by relationship value in the Southeast?", analysis: ranking,      visual: table_with_sparklines }
  2: { q: "Which high-value customers show attrition risk this month?",           analysis: risk_cohort,  visual: ranked_table }
  3: { q: "What is our primary bank share trend by segment?",                     analysis: trend_segmented, visual: line }
  4: { q: "Which single-product customers show strong balance growth?",           analysis: opportunity_cohort, visual: table }
  5: { q: "How did deposit balances shift after the April rate change?",          analysis: event_impact, visual: before_after_line }

AG-BNK-002:
  1: { q: "What is the alert backlog and its age profile?",                    analysis: backlog_profile,   visual: stacked_age_bars }
  2: { q: "Which typologies have the highest false positive rate?",            analysis: efficiency_ranking,visual: bar }
  3: { q: "Which alerts should be worked first today?",                        analysis: prioritization,    visual: ranked_queue_draft }
  4: { q: "Has SAR conversion changed since the June rule tuning?",            analysis: before_after,      visual: dual_axis }
  5: { q: "Which investigators are carrying aged alerts above SLA?",           analysis: workload,          visual: table }

AG-INS-001:
  1: { q: "Where is leakage highest by coverage line?",                              analysis: ranking,        visual: bar_with_value }
  2: { q: "Which settlement patterns diverge most from peers on like claims?",       analysis: variance,       visual: box_plot }
  3: { q: "What is driving cycle time increase in auto physical damage?",            analysis: decomposition,  visual: waterfall_by_stage }
  4: { q: "How much subrogation recovery are we leaving on the table?",              analysis: gap_quantification, visual: funnel }
  5: { q: "Did the new triage rule reduce severity on low-complexity claims?",       analysis: programme_eval, visual: before_after }

AG-INS-002:
  1: { q: "Where is rate adequacy weakest in the commercial property book?",        analysis: adequacy_ranking, visual: scatter }
  2: { q: "What is our exposure concentration by county for wind peril?",           analysis: concentration,    visual: map_plus_table }
  3: { q: "How has quote-to-bind moved since the July rate change?",                analysis: trend_segmented,  visual: line }
  4: { q: "Which segments are we retaining below plan?",                            analysis: variance_to_plan, visual: bar }
  5: { q: "What would a 5% increase on the worst-performing segment do to retention?", analysis: scenario_framing, visual: elasticity_curve_directional }

AG-HLT-001:
  1: { q: "What is our 30-day readmission rate and how does it compare to last year?", analysis: trend_comparison, visual: line }
  2: { q: "Which conditions and units drive the most readmissions?",                    analysis: contribution_ranking, visual: pareto }
  3: { q: "Which discharge patterns are associated with higher readmission?",           analysis: association,      visual: comparison_bars }
  4: { q: "Are follow-up appointments being scheduled within the target window?",       analysis: compliance,       visual: gauge_segmented }
  5: { q: "Did the transitional care programme reduce readmissions in the pilot units?",analysis: programme_eval,   visual: dual_line }

AG-HLT-002:
  1: { q: "Which items are at risk of stockout this week?",                    analysis: risk_list,      visual: ranked_table }
  2: { q: "Where is formulary adherence lowest?",                              analysis: compliance_ranking, visual: bar }
  3: { q: "What is driving the increase in pharmacy cost per patient day?",    analysis: decomposition,  visual: waterfall }
  4: { q: "How much waste came from short-dated stock last quarter?",          analysis: waste_analysis, visual: pareto }
  5: { q: "Draft a replenishment adjustment for the top 10 at-risk items.",    analysis: action_draft,   visual: approval_card }

AG-RTL-001:
  1: { q: "How are comparable sales trending by category this week?",              analysis: trend_by_category, visual: heatmap }
  2: { q: "Which categories are missing plan and why?",                            analysis: variance_decomposition, visual: waterfall }
  3: { q: "Did the back-to-school promotion deliver incremental margin?",          analysis: promotion_eval,    visual: lift_analysis }
  4: { q: "Which SKUs have high sell-through but poor in-stock?",                  analysis: opportunity_matrix,visual: quadrant }
  5: { q: "Where is basket size declining and what is leaving the basket?",        analysis: basket_composition,visual: affinity_shift }

AG-RTL-002:
  1: { q: "Which stores have the worst in-stock rate this week?",                     analysis: ranking,        visual: table_plus_map }
  2: { q: "What is our forecast accuracy by category?",                               analysis: accuracy_ranking, visual: bar }
  3: { q: "Where do we have excess weeks of supply?",                                 analysis: excess_analysis, visual: pareto }
  4: { q: "What did stockouts cost us last month?",                                   analysis: lost_sales,     visual: quantified_estimate }
  5: { q: "Draft transfer recommendations to fix the top 20 availability gaps.",      analysis: action_draft,   visual: approval_card }

AG-TRN-001:
  1: { q: "What is on-time delivery this week and where is it worst?",             analysis: performance_ranking, visual: bar_plus_map }
  2: { q: "What is driving late deliveries on the Northeast lanes?",               analysis: root_cause,      visual: contribution_analysis }
  3: { q: "Where is dwell time eroding asset utilization?",                        analysis: utilization_impact, visual: quantified }
  4: { q: "How does cost per mile compare across carriers on the same lanes?",     analysis: like_for_like,   visual: scatter }
  5: { q: "Which customers are at risk of SLA penalty this month?",                analysis: risk_forecast,   visual: ranked_table }

AG-UTL-001:
  1: { q: "What is our SAIDI year to date against the regulatory target?",              analysis: regulatory_tracking, visual: line_vs_target }
  2: { q: "Which feeders contribute most to interruption minutes?",                     analysis: contribution_ranking, visual: pareto }
  3: { q: "Which poor-health assets serve the most customers?",                         analysis: risk_prioritization, visual: matrix }
  4: { q: "What was the customer and load impact of last week's storm?",                analysis: event_analysis,  visual: timeline_plus_map }
  5: { q: "Which maintenance deferrals carry the highest customer-minute risk?",        analysis: risk_ranking,    visual: table }

AG-MFG-001:
  1: { q: "What is OEE by line this week and where did we lose the most?",  analysis: performance_ranking, visual: oee_waterfall }
  2: { q: "What are the top downtime reasons on Line 3?",                   analysis: pareto,          visual: reason_code_ranking }
  3: { q: "Which shifts show the biggest first-pass-yield gap?",            analysis: shift_comparison,visual: box_plot }
  4: { q: "Did changeover standardization reduce changeover time?",         analysis: programme_eval,  visual: distribution_shift }
  5: { q: "Where is scrap concentrated by product and root cause?",         analysis: concentration,   visual: treemap_plus_pareto }
```

### 18.1 Synthetic demo-tier data

One generator per product in `seed/synthetic/`. Requirements:

- Preserve distribution, seasonality, referential integrity and cardinality. No real subject data.
- Generated **from the product contract and profile statistics**, and regenerated whenever the
  schema version changes so the demo never drifts from the live shape.
- Stored in a physically separate schema (`DEMO_TIER_SCHEMA`) with **no path to production data**.
- Sized for sub-second query response, so demo latency is dominated by model inference.
- Every answer to a seed question must be non-trivial: the generator must plant the pattern the
  question is meant to discover (e.g. a genuine churn concentration in one tenure band), so the
  golden answer is a real finding rather than noise.

---

## 19. Security implementation

- OIDC SSO; SCIM provisioning; MFA enforced for owner, steward, architect, administrator.
- **The marketplace never stores effective permissions.** It records requests, decisions and
  grants, and provisions into native platform RBAC. A nightly reconciliation job compares the
  entitlement register against actual platform grants and raises drift as an incident.
- Connector service principals are read-only with a published permission manifest.
  `npm run test:kill` attempts a write on every supported platform and must fail on all.
- Row-level and column-level policy enforcement happens **in the data platform**, never in the
  application layer.
- Agents hold distinct machine identities. Effective access = intersection(agent scope, user
  entitlement). An agent can never widen a user's access.
- Prompt-injection defence on every retrieval path: retrieved content, tool results and user
  text are passed as data with provenance framing, never as instructions. A tool-call decision
  derived solely from retrieved content is blocked and logged as a security event.
- Full audit: every view of a Restricted listing, every request, decision, grant, revocation,
  agent question and returned column set, written immutably. Retention 7 years by default.
- Multi-tenancy: `tenant_id` on every table with RLS; optional single-tenant deployment.
- Encryption TLS 1.3 in transit, at rest with optional customer-managed keys; secrets in a
  managed vault with rotation.

---

## 20. Testing and CI gates

| Layer | Must prove | Gate |
|---|---|---|
| Unit | rubric-driven calculations change when the rubric changes (table-driven) | blocking |
| Contract | generated OpenAPI, MCP servers and SDKs match their manifests | blocking |
| Golden | pinned evidence + pinned rubric reproduces a prior composite byte-identically (≥3 snapshots) | blocking |
| Publish gate | agent with 4 exchanges / missing limitation / uncited KPI is rejected with a precise message | blocking |
| Kill | no connector can write to any customer platform (real sandbox, not a mock) | blocking |
| Security | entitlement escalation, purpose bypass, injection, cross-tenant access all fail closed | blocking |
| E2E | signature journey (search → demo → request → approve → provision → first query) < 8 min | blocking |
| Perf | landing budgets, catalog search p95 ≤400ms @50k assets, mesh ≤2s @2k nodes, motion ≥58fps throttled | blocking |
| A11y | zero critical axe violations; scripted keyboard + screen-reader journeys on top 10 surfaces; motion suite runs in both motion modes | blocking |
| Load | 50k assets, 500 concurrent sessions, 50M daily events | quarterly |
| Chaos | data plane down, connector auth expiry, model outage, workflow restart mid-approval | quarterly |

CI pipeline order: `lint → typecheck → gen-diff → unit → contract → golden → publish_gate →
security → a11y → build → e2e → perf`. Any failure blocks merge.

Environments: local (seeded), ephemeral preview per PR, staging (full seed + sandbox platform
account), production per tenant. Feature flags typed as release / experiment / operational with
a max age lint. Migrations forward-only; snapshot and audit tables never migrated destructively.

SLOs with error budgets: catalog availability 99.9%, request-to-provision latency, agent answer
success rate, demo console availability 99.5%. Budget exhaustion freezes feature work.

---

## 21. Milestones

Each milestone ends with `npm run verify` green and the acceptance criteria demonstrably met.
Do not proceed until they are.

### M0 — Scaffold
- [ ] M0.1 Monorepo, Docker Compose (Postgres+pgvector, Redis), env validation on boot
- [ ] M0.2 CI pipeline with all lint rules (`no-magic-numbers`, `no-brand-strings`, `animatable-props`)
- [ ] M0.3 `docs/DECISIONS.md`, ADR template, runbook skeleton
- **Accept:** `npm run dev` boots an empty app; CI green; a deliberate hardcoded `0.75` fails lint.

### M1 — Canonical model, rubrics, manifests
- [ ] M1.1 Full DDL for Section 6 with RLS on every table and append-only grants
- [ ] M1.2 Manifest JSON Schemas + validator with precise error messages and line numbers
- [ ] M1.3 Rubric loader: YAML → `rubric_version` / `rubric_criterion`, resolved at read time
- [ ] M1.4 Taxonomies and KPI registry with invariant I1 as a partial unique index
- **Accept:** a malformed manifest fails with a precise error; changing a weight in
  `quality.yaml` and re-seeding changes composites with **zero code changes**; two KPI files
  with the same name fail generation with a side-by-side diff.

### M2 — Generators
- [ ] M2.1 `gen:ddl`, `gen:sql`, `gen:mcp`, `gen:openapi`, `gen:types`, `gen:agentcard`
- [ ] M2.2 Header stamping + determinism (stable ordering, no timestamps inside hashed content)
- [ ] M2.3 CI gen-diff check
- **Accept:** regeneration produces zero diff; hand-editing a generated file fails the build.

### M3 — Snowflake connector
- [ ] M3.1 Read-only auth, published permission manifest
- [ ] M3.2 Metadata harvest (schemas, columns, comments, tags) → canonical model
- [ ] M3.3 Lineage harvest → `lineage_edge`
- [ ] M3.4 Usage + cost harvest → `usage_event`, `cost_allocation`
- [ ] M3.5 Quality results harvest (DMF / DQ tool) → `quality_result`
- [ ] M3.6 Kill test
- **Accept:** one real product harvested, scored and rendered end to end; kill test proves no
  write path exists.

### M4 — Catalog, search, product detail
- [ ] M4.1 Catalog service + facets + cursor pagination
- [ ] M4.2 Hybrid search: pgvector + FTS fused with RRF, coefficients from `ranking.yaml`
- [ ] M4.3 Product catalog grid, card anatomy, compare mode, non-dead-end empty state
- [ ] M4.4 All 8 product detail tabs rendering from real metadata
- **Accept:** exact-name search never loses to a semantic neighbour (test with adversarial
  near-synonyms); every tab renders with no placeholder content; partial-permission state works.

### M5 — Quality engine
- [ ] M5.1 Rule evaluation → `quality_result`
- [ ] M5.2 Scoring with archetype overrides, hard blockers, tier weighting
- [ ] M5.3 Immutable snapshots with `evidence_ref`
- [ ] M5.4 Golden reproducibility fixtures
- **Accept:** re-scoring against a pinned rubric version reproduces a prior composite exactly;
  a critical rule failure caps the composite at the rubric-defined value.

### M6 — Agent registry, publish gate, demo runner
- [ ] M6.1 Agent + version + coverage map + product/tool bindings
- [ ] M6.2 Publish gate as executable tests (Section 15.3)
- [ ] M6.3 Agent runtime adapter interface + `mock` and `cortex` implementations
- [ ] M6.4 Demo runner against demo-tier synthetic data
- [ ] M6.5 Nightly curated-question validation job with `stale` marking
- **Accept:** an agent with 4 exchanges is rejected with a clear message naming the shortfall;
  all 14 seed agents answer their 5 questions within the latency budget; no mocked answers exist.

### M7 — Demo console and answer grounding
- [ ] M7.1 Streaming answer with headline, visual, table, KPI definition, as-of, citations
- [ ] M7.2 Tool-trace right rail (calls, rows scanned, latency, cost) visible by default
- [ ] M7.3 API-layer grounding validation; 424 on uncited numerics
- [ ] M7.4 Out-of-scope refusal with named boundary + handoff + demand CTA
- [ ] M7.5 Feedback capture into the evaluation corpus
- **Accept:** an answer with a stripped citation is withheld and returns 424; an out-of-scope
  question returns 422 with a suggested agent; every demo answer shows its tier badge.

### M8 — Workflow rails
- [ ] M8.1 Access request + pre-submission policy evaluation + approval chain + SLA clocks
- [ ] M8.2 Mechanical provisioning, purpose binding, expiry, dormant-grant detection
- [ ] M8.3 Enhancement workflow + public backlog with votes
- [ ] M8.4 Demand intake + duplicate detection + demand board + clustering
- [ ] M8.5 Entitlement register + audit export
- **Accept:** an approved request provisions a scoped platform role, binds purpose and expiry,
  and writes an immutable audit record; a new-supply request matching a seed product at ≥0.75
  is blocked pending owner review with the candidate shown side by side.

### M9 — Meshes
- [ ] M9.1 Data mesh computation, all six edge types, weights from `mesh.yaml`
- [ ] M9.2 Agent mesh computation, all six edge types
- [ ] M9.3 Explorer: force / domain / source-anchored layouts, blast-radius, duplication, gap modes
- [ ] M9.4 Accessible table equivalent for every mesh view
- [ ] M9.5 Divergence detection job (Section 15.5)
- **Accept:** every rendered edge has a rationale; edges below 0.80 confidence are held for
  review and do not render; blast-radius on a shared source returns the correct downstream set.

### M10 — Observability, value, FinOps
- [ ] M10.1 Product and agent signals + alerting
- [ ] M10.2 Incident lifecycle with computed severity and un-suppressable consumer notification
- [ ] M10.3 Upstream trust banners propagating to agent listings and cards
- [ ] M10.4 Value module, deflection model, portfolio views, board-pack export
- [ ] M10.5 Cost attribution, unit economics, budgets, retirement candidates
- **Accept:** a simulated freshness breach raises an incident, notifies consumers and banners
  every affected listing within 5 minutes; the exported board pack and the dashboard read from
  the same snapshot and cannot disagree.

### M11 — Landing page and motion
- [ ] M11.1 Motion controller with all pause triggers and static renderers
- [ ] M11.2 Product ribbon (13.2)
- [ ] M11.3 Agent constellation with server-side pre-warmed layout, orbits, SSE pulses (13.3)
- [ ] M11.4 Answer theatre with recorded-trace replay and honest labelling (13.4)
- [ ] M11.5 Counters + activity ticker with suppression rule (13.5)
- [ ] M11.6 Industry selector re-rendering bands 4–6
- **Accept:** every budget in 13.6 passes in CI; reduced-motion mode renders the same
  information statically; hero text contrast ≥4.5:1 asserted against the rendered page;
  keyboard user can pause every moving element.

### M12 — Academy, admin, hardening
- [ ] M12.1 Learning paths, contextual runbooks, sandboxes on demo tier, certification
- [ ] M12.2 Admin: rubric versioning UI, taxonomies, connectors, flags, tenancy
- [ ] M12.3 AgentOps: eval suites, canary release, rollback drill
- [ ] M12.4 i18n, RTL, 35% string-expansion layout pass
- [ ] M12.5 Load, chaos and full a11y pass
- **Accept:** a rubric weight change through the admin UI re-scores the estate and preserves
  prior snapshots; an agent canary rollback restores the previous bundle in one action.

---

## 22. Definition of done (per feature)

- [ ] Behaviour matches this document; deviations recorded in `docs/DECISIONS.md`
- [ ] No numeric threshold, brand string or raw hex outside tokens/rubrics
- [ ] All five component states implemented (loading, empty, error, partial-permission, populated)
- [ ] Tests at every applicable layer in Section 20
- [ ] Telemetry emitted using the shared typed event taxonomy
- [ ] Audit events written for anything touching access, publication or scores
- [ ] Accessible: keyboard path, focus visible, labelled, motion-safe
- [ ] Runbook entry if it can page someone

---

## 23. Coding conventions

**Do**
- Resolve rubric values by `rubric_version_id` at read time and record that id with any output.
- Return the missing scope and a deep link on every 403.
- Store `{confidence, rationale}` with every inferred record.
- Prefer server components and streaming; keep client bundles small.
- Write the failing test first for every invariant in Section 2.

**Do not**
- Do not add an "approve anyway" path to any gate.
- Do not cache effective permissions.
- Do not animate anything except `transform` and `opacity`.
- Do not render a skeleton on the landing page.
- Do not let an agent answer when grounding fails — return the error.
- Do not introduce a new event name without adding it to the typed taxonomy.
- Do not add a dependency that pushes the motion layer over 45KB gzipped.

---

## 24. Glossary

| Term | Meaning here |
|---|---|
| Data product | A governed, contracted, owned dataset published for consumption with declared KPIs, quality rules and endpoints |
| Agent | A catalogued AI assistant with an owner, coverage map, entitlement scope, evaluation suite and value case |
| Certified KPI | A business measure with exactly one authoritative definition in the registry |
| Contract | The enforceable promise a product makes: grain, freshness, availability, completeness, accuracy, deprecation policy |
| Coverage map | The agent's functional contract: which KPIs, at which grains and slices, to which analysis depth |
| Demo tier | Synthetic data in a physically separate schema; same code path as production |
| Mesh edge | A computed relationship between two assets carrying type, strength, factors, confidence and rationale |
| Publish gate | The executable checklist an asset must pass before it reaches the shelf |
| Purpose binding | The declared purpose attached to a grant and logged with every query made under it |
| Rubric | Versioned configuration data holding every weight, threshold and band |
| Snapshot | An immutable, keyed record of a score or publication that can be replayed exactly |
