"""The canonical model — BUILD.md section 6.

Every table in section 6.1, with the DDL of section 6.2 implemented exactly as
written. The invariants I1–I7 are database constraints here, not documentation:

  I1  exactly one active kpi_definition per (tenant, kpi_name)  -> partial unique index
  I2  a quality_score_snapshot without rubric_version is invalid -> NOT NULL + FK
  I3  an agent_version cannot publish with fewer than 5 demo rows -> publish gate (M6)
  I4  every agent_kpi_coverage row cites an existing kpi_definition -> FK
  I5  data_product.sensitivity_tier is derived, never written    -> trigger
  I6  every mesh edge has confidence and non-empty rationale     -> NOT NULL + CHECK
  I7  known_limitations and out_of_scope are non-empty           -> CHECK

Ordering in this file is dependency order and is also emission order: that is
what makes regeneration byte-identical (I9).
"""

from __future__ import annotations

from scripts.generators.model import Column, Index, RawBlock, Table

GENERATOR_VERSION = "1.0.0"

EXTENSIONS = RawBlock(
    name="extensions",
    group="bootstrap",
    purpose="pgvector for semantic search; pg_trgm for lexical near-matching.",
    sql="""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- The application connects as this role. Append-only tables revoke write verbs
-- from it and every row-level policy is written against it.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
    CREATE ROLE app_role NOLOGIN;
  END IF;
END
$$;
""".strip(),
)

# ---------------------------------------------------------------------------
# Reference
# ---------------------------------------------------------------------------

REFERENCE: list[Table] = [
    Table(
        name="tenant",
        group="reference",
        purpose="A deployment boundary. Every tenant-scoped row names one.",
        tenant_scoped=False,
        columns=[
            Column("tenant_id", "TEXT", primary_key=True),
            Column("name", "TEXT", null=False),
            Column("deployment_mode", "TEXT", null=False,
                   check="deployment_mode IN ('multi_tenant','single_tenant')"),
            Column("residency_regions", "TEXT[]", null=False, default="'{}'"),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
    ),
    Table(
        name="industry",
        group="reference",
        purpose="Industry taxonomy. Seeded from manifests/taxonomies/industry.yaml.",
        tenant_scoped=False,
        columns=[
            Column("code", "TEXT", primary_key=True),
            Column("label", "TEXT", null=False),
            Column("description", "TEXT", null=False),
            Column("sort_order", "INT", null=False),
        ],
    ),
    Table(
        name="business_domain",
        group="reference",
        purpose="Business domain taxonomy (customer, network, risk, supply chain, ...).",
        tenant_scoped=False,
        columns=[
            Column("code", "TEXT", primary_key=True),
            Column("label", "TEXT", null=False),
            Column("description", "TEXT", null=False),
            Column("sort_order", "INT", null=False),
        ],
    ),
    Table(
        name="product_archetype",
        group="reference",
        purpose="Product archetype; drives the quality rubric's archetype overrides.",
        tenant_scoped=False,
        columns=[
            Column("code", "TEXT", primary_key=True),
            Column("label", "TEXT", null=False),
            Column("description", "TEXT", null=False),
            Column("sort_order", "INT", null=False),
        ],
    ),
    Table(
        name="sensitivity_tier",
        group="reference",
        purpose="Sensitivity ladder. rank_order is what derive_sensitivity maximises (I5).",
        tenant_scoped=False,
        columns=[
            Column("code", "TEXT", primary_key=True),
            Column("label", "TEXT", null=False),
            Column("rank_order", "INT", null=False, unique=True),
            Column("requires_purpose", "BOOLEAN", null=False),
            Column("description", "TEXT", null=False),
        ],
    ),
    Table(
        name="purpose_category",
        group="reference",
        purpose="Permitted purposes a grant may be bound to. Purpose is mandatory above Internal.",
        tenant_scoped=False,
        columns=[
            Column("code", "TEXT", primary_key=True),
            Column("label", "TEXT", null=False),
            Column("description", "TEXT", null=False),
            Column("requires_free_text", "BOOLEAN", null=False),
            Column("sort_order", "INT", null=False),
        ],
    ),
    Table(
        name="source_system",
        group="reference",
        purpose="Upstream system of record. Shared sources are what the data mesh links on.",
        columns=[
            Column("source_id", "TEXT", primary_key=True),
            Column("name", "TEXT", null=False),
            Column("platform", "TEXT", null=False),
            Column("owner_team", "TEXT", null=False),
            Column("criticality", "TEXT", null=False,
                   check="criticality IN ('tier1','tier2','tier3')"),
            Column("description", "TEXT", null=False),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

IDENTITY: list[Table] = [
    Table(
        name="org_unit",
        group="identity",
        purpose="Organisational tree used for approval routing and adoption breadth.",
        columns=[
            Column("org_unit_id", "TEXT", primary_key=True),
            Column("name", "TEXT", null=False),
            Column("parent_org_unit_id", "TEXT", references="org_unit(org_unit_id)"),
            Column("cost_centre", "TEXT"),
        ],
    ),
    Table(
        name="party",
        group="identity",
        purpose="A person, team, service principal or agent identity. Agents hold their own.",
        columns=[
            Column("party_id", "TEXT", primary_key=True),
            Column("party_type", "TEXT", null=False,
                   check="party_type IN ('person','team','service','agent')"),
            Column("display_name", "TEXT", null=False),
            Column("email", "TEXT"),
            Column("org_unit_id", "TEXT", references="org_unit(org_unit_id)"),
            Column("external_subject", "TEXT",
                   comment="OIDC subject or SCIM external id; never a password."),
            Column("mfa_enforced", "BOOLEAN", null=False, default="false"),
            Column("active", "BOOLEAN", null=False, default="true"),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[Index(columns="external_subject", unique=True, where="external_subject IS NOT NULL",
                       name="party_external_subject_key")],
    ),
    Table(
        name="role_assignment",
        group="identity",
        purpose="Marketplace role held by a party. MFA is enforced for the privileged four.",
        columns=[
            Column("assignment_id", "TEXT", primary_key=True),
            Column("party_id", "TEXT", null=False, references="party(party_id)"),
            Column("role_code", "TEXT", null=False,
                   check="role_code IN ('consumer','owner','steward','architect',"
                         "'security','privacy','administrator')"),
            Column("scope_type", "TEXT", null=False,
                   check="scope_type IN ('tenant','domain','product','agent')"),
            Column("scope_id", "TEXT"),
            Column("granted_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("granted_by", "TEXT", null=False, references="party(party_id)"),
        ],
        unique_together=[("party_id", "role_code", "scope_type", "scope_id")],
    ),
]

# ---------------------------------------------------------------------------
# Supply — data products
# ---------------------------------------------------------------------------

SUPPLY_DATA: list[Table] = [
    Table(
        name="data_product",
        group="supply_data",
        purpose="A governed, contracted, owned dataset published for consumption.",
        invariants=["I5", "I7"],
        columns=[
            Column("product_id", "TEXT", primary_key=True, comment="DP-<IND>-<NNN>"),
            Column("name", "TEXT", null=False),
            Column("purpose", "TEXT", null=False,
                   check="length(purpose) BETWEEN 20 AND 400"),
            Column("industry_code", "TEXT", null=False, references="industry(code)"),
            Column("domain_code", "TEXT", null=False, references="business_domain(code)"),
            Column("archetype_code", "TEXT", null=False, references="product_archetype(code)"),
            Column("sensitivity_tier", "TEXT", null=False,
                   comment="I5: DERIVED from columns by trigger; never written directly."),
            Column("certification", "TEXT", null=False,
                   check="certification IN ('certified','published','beta','deprecated')"),
            Column("owner_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("current_version", "TEXT", null=False),
            Column("grain", "TEXT", null=False),
            Column("history_months", "INT", null=False),
            Column("known_limitations", "TEXT", null=False,
                   check="length(trim(known_limitations)) > 10 "
                         "AND lower(trim(known_limitations)) NOT IN ('none','n/a','tbd')",
                   comment="I7: a limitation section that says 'none' is not a limitation section."),
            Column("tier", "TEXT", null=False, check="tier IN ('tier1','tier2','tier3')",
                   comment="Tier weighting for estate scoring (15.1)."),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("updated_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[
            Index(columns="industry_code, domain_code", name="data_product_taxonomy_idx"),
            Index(columns="certification", name="data_product_certification_idx"),
            Index(columns="owner_party_id", name="data_product_owner_idx"),
        ],
    ),
    Table(
        name="data_product_version",
        group="supply_data",
        purpose="A published version of a product. Publication is snapshotted, never mutated.",
        columns=[
            Column("product_version_id", "TEXT", primary_key=True),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)"),
            Column("semver", "TEXT", null=False),
            Column("status", "TEXT", null=False,
                   check="status IN ('draft','published','deprecated','retired')"),
            Column("change_summary", "TEXT", null=False),
            Column("schema_stability", "TEXT", null=False,
                   check="schema_stability IN ('additive_only','breaking_allowed','frozen')"),
            Column("published_at", "TIMESTAMPTZ"),
            Column("published_by", "TEXT", references="party(party_id)"),
            Column("deprecated_at", "TIMESTAMPTZ"),
        ],
        unique_together=[("product_id", "semver")],
    ),
    Table(
        name="data_product_column",
        group="supply_data",
        purpose="Column-level metadata and classification. Sensitivity derives from here (I5).",
        columns=[
            Column("column_id", "TEXT", primary_key=True),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)",
                   on_delete="CASCADE"),
            Column("name", "TEXT", null=False),
            Column("business_name", "TEXT", null=False),
            Column("data_type", "TEXT", null=False),
            Column("nullable", "BOOLEAN", null=False),
            Column("classification", "TEXT[]", null=False, default="'{}'",
                   comment="pii, phi, pci, identifier, financial, ..."),
            Column("sensitivity_code", "TEXT", null=False, references="sensitivity_tier(code)"),
            Column("description", "TEXT", null=False),
            Column("masking_policy", "TEXT"),
            Column("ordinal", "INT", null=False),
        ],
        unique_together=[("product_id", "name")],
        indexes=[Index(columns="product_id, ordinal", name="data_product_column_order_idx")],
    ),
    Table(
        name="data_contract_version",
        group="supply_data",
        purpose="The enforceable promise a product makes. Conformance is measured against it.",
        columns=[
            Column("contract_version_id", "TEXT", primary_key=True),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)"),
            Column("semver", "TEXT", null=False),
            Column("status", "TEXT", null=False,
                   check="status IN ('draft','active','superseded')"),
            Column("schema_stability", "TEXT", null=False),
            Column("deprecation_notice_days", "INT", null=False),
            Column("minimum_parallel_run_days", "INT", null=False),
            Column("support_hours", "TEXT", null=False),
            Column("p1_response_minutes", "INT", null=False),
            Column("on_call", "TEXT", null=False),
            Column("max_sensitivity", "TEXT", null=False, references="sensitivity_tier(code)"),
            Column("contains_pii", "BOOLEAN", null=False),
            Column("residency", "TEXT[]", null=False, default="'{}'"),
            Column("consumer_obligations", "TEXT[]", null=False, default="'{}'"),
            Column("breach_process", "TEXT", null=False),
            Column("effective_from", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        unique_together=[("product_id", "semver")],
    ),
    Table(
        name="contract_guarantee",
        group="supply_data",
        purpose="One measurable guarantee of a contract: freshness, availability, completeness, accuracy.",
        columns=[
            Column("guarantee_id", "TEXT", primary_key=True),
            Column("contract_version_id", "TEXT", null=False,
                   references="data_contract_version(contract_version_id)", on_delete="CASCADE"),
            Column("dimension", "TEXT", null=False,
                   check="dimension IN ('freshness','availability','completeness','accuracy')"),
            Column("target_text", "TEXT", null=False),
            Column("target_numeric", "NUMERIC(12,4)"),
            Column("unit", "TEXT", null=False),
            Column("measurement_window", "TEXT", null=False),
            Column("measured_at_grain", "TEXT", null=False),
            Column("reference_system", "TEXT"),
        ],
        unique_together=[("contract_version_id", "dimension")],
    ),
    Table(
        name="endpoint",
        group="supply_data",
        purpose="A consumption surface: SQL, REST, MCP, stream or share.",
        columns=[
            Column("endpoint_id", "TEXT", primary_key=True),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)",
                   on_delete="CASCADE"),
            Column("surface", "TEXT", null=False,
                   check="surface IN ('sql','rest','mcp','stream','share')"),
            Column("uri", "TEXT", null=False),
            Column("auth_mode", "TEXT", null=False),
            Column("required_scope", "TEXT", null=False),
            Column("row_limit", "INT"),
            Column("documentation_ref", "TEXT", null=False),
        ],
        unique_together=[("product_id", "surface")],
    ),
]

# ---------------------------------------------------------------------------
# Semantics
# ---------------------------------------------------------------------------

SEMANTICS: list[Table] = [
    Table(
        name="kpi_definition",
        group="semantics",
        purpose="A business measure with exactly one authoritative definition (I1).",
        invariants=["I1"],
        columns=[
            Column("kpi_id", "TEXT", primary_key=True, comment="KPI-<DOMAIN>-<NNN>"),
            Column("kpi_name", "TEXT", null=False),
            Column("status", "TEXT", null=False,
                   check="status IN ('draft','certified','deprecated','superseded')"),
            Column("business_definition", "TEXT", null=False),
            Column("numerator_expr", "TEXT"),
            Column("denominator_expr", "TEXT"),
            Column("expression", "TEXT"),
            Column("grains_supported", "TEXT[]", null=False),
            Column("slices_supported", "TEXT[]", null=False),
            Column("inclusions", "TEXT[]", null=False, default="'{}'"),
            Column("exclusions", "TEXT[]", null=False, default="'{}'"),
            Column("unit", "TEXT", null=False),
            Column("direction", "TEXT"),
            Column("target", "NUMERIC"),
            Column("domain_code", "TEXT", null=False, references="business_domain(code)"),
            Column("source_of_record", "TEXT", references="data_product(product_id)"),
            Column("steward_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("forum_approved_at", "DATE"),
            Column("superseded_by", "TEXT", references="kpi_definition(kpi_id)"),
            Column("last_reviewed", "DATE", null=False),
            Column("review_months", "INT", null=False),
        ],
        indexes=[
            Index(
                columns="tenant_id, lower(kpi_name)",
                unique=True,
                where="status IN ('draft','certified')",
                name="kpi_one_active",
            ),
        ],
    ),
    Table(
        name="kpi_definition_version",
        group="semantics",
        purpose="Immutable history of a KPI definition; agents pin the version they answered under.",
        columns=[
            Column("kpi_version_id", "TEXT", primary_key=True),
            Column("kpi_id", "TEXT", null=False, references="kpi_definition(kpi_id)"),
            Column("semver", "TEXT", null=False),
            Column("business_definition", "TEXT", null=False),
            Column("expression", "TEXT"),
            Column("change_reason", "TEXT", null=False),
            Column("approved_by", "TEXT", null=False, references="party(party_id)"),
            Column("effective_from", "TIMESTAMPTZ", null=False),
        ],
        unique_together=[("kpi_id", "semver")],
    ),
    Table(
        name="kpi_synonym",
        group="semantics",
        purpose="Alternate names a consumer might search for. Feeds lexical search recall.",
        columns=[
            Column("synonym_id", "TEXT", primary_key=True),
            Column("kpi_id", "TEXT", null=False, references="kpi_definition(kpi_id)",
                   on_delete="CASCADE"),
            Column("term", "TEXT", null=False),
            Column("source", "TEXT", null=False,
                   check="source IN ('steward','glossary','search_log','bi_tool')"),
        ],
        unique_together=[("kpi_id", "term")],
    ),
    Table(
        name="glossary_term",
        group="semantics",
        purpose="Business vocabulary. Distinct from KPIs: a term need not be measurable.",
        columns=[
            Column("term_id", "TEXT", primary_key=True),
            Column("term", "TEXT", null=False),
            Column("definition", "TEXT", null=False),
            Column("domain_code", "TEXT", null=False, references="business_domain(code)"),
            Column("steward_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("related_kpi_ids", "TEXT[]", null=False, default="'{}'"),
            Column("status", "TEXT", null=False,
                   check="status IN ('draft','approved','deprecated')"),
        ],
        unique_together=[("tenant_id", "term")],
    ),
]

# ---------------------------------------------------------------------------
# Supply — agents
# ---------------------------------------------------------------------------

SUPPLY_AGENTS: list[Table] = [
    Table(
        name="prompt_artifact",
        group="supply_agents",
        purpose="Content-addressed prompt. An agent version pins the hash, never the text.",
        columns=[
            Column("prompt_hash", "TEXT", primary_key=True),
            Column("agent_id", "TEXT", null=False),
            Column("label", "TEXT", null=False),
            Column("body", "TEXT", null=False),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
    ),
    Table(
        name="agent",
        group="supply_agents",
        purpose="A catalogued AI assistant with an owner, coverage map, scope and value case.",
        columns=[
            Column("agent_id", "TEXT", primary_key=True, comment="AG-<IND>-<NNN>"),
            Column("name", "TEXT", null=False),
            Column("industry_code", "TEXT", null=False, references="industry(code)"),
            Column("domain_code", "TEXT", null=False, references="business_domain(code)"),
            Column("owner_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("machine_identity", "TEXT", null=False, unique=True,
                   comment="Distinct service principal; effective access is an intersection (I12)."),
            Column("on_call", "TEXT", null=False),
            Column("escalation_path", "TEXT", null=False),
            Column("certification", "TEXT", null=False,
                   check="certification IN ('certified','published','beta','deprecated')"),
            Column("current_version_id", "TEXT"),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[Index(columns="industry_code, domain_code", name="agent_taxonomy_idx")],
    ),
    Table(
        name="evaluation_run",
        group="supply_agents",
        purpose="One execution of the evaluation suites against an agent bundle.",
        columns=[
            Column("eval_run_id", "TEXT", primary_key=True),
            Column("agent_id", "TEXT", null=False, references="agent(agent_id)"),
            Column("agent_version_ref", "TEXT", null=False,
                   comment="Set before the version row exists on a first publish; not an FK."),
            Column("suite_results", "JSONB", null=False),
            Column("pass_rate_pct", "NUMERIC(5,2)", null=False),
            Column("groundedness_pct", "NUMERIC(5,2)", null=False),
            Column("threshold_pct", "NUMERIC(5,2)", null=False),
            Column("passed", "BOOLEAN", null=False),
            Column("previous_run_id", "TEXT"),
            Column("started_at", "TIMESTAMPTZ", null=False),
            Column("finished_at", "TIMESTAMPTZ", null=False),
        ],
        indexes=[Index(columns="agent_id, finished_at DESC", name="evaluation_run_recent_idx")],
    ),
    Table(
        name="agent_version",
        group="supply_agents",
        purpose="An immutable bundle: model, params, prompt hash, tool bindings, eval run.",
        invariants=["I7"],
        columns=[
            Column("agent_version_id", "TEXT", primary_key=True),
            Column("agent_id", "TEXT", null=False, references="agent(agent_id)"),
            Column("semver", "TEXT", null=False),
            Column("status", "TEXT", null=False,
                   check="status IN ('draft','canary','published','retired')"),
            Column("autonomy_level", "TEXT", null=False,
                   check="autonomy_level IN ('L0','L1','L2','L3')"),
            Column("capability_statement", "TEXT", null=False,
                   check="length(capability_statement) BETWEEN 90 AND 140"),
            Column("business_value_block", "TEXT", null=False),
            Column("out_of_scope", "TEXT[]", null=False,
                   check="array_length(out_of_scope,1) >= 1",
                   comment="I7: an agent that refuses nothing has no boundary."),
            Column("personas", "TEXT[]", null=False, default="'{}'"),
            Column("analyses", "TEXT[]", null=False, default="'{}'"),
            Column("replaces", "TEXT", null=False),
            Column("model_provider", "TEXT", null=False),
            Column("model_id", "TEXT", null=False),
            Column("model_params", "JSONB", null=False),
            Column("prompt_hash", "TEXT", null=False, references="prompt_artifact(prompt_hash)"),
            Column("guardrail_config", "JSONB", null=False),
            Column("budget_p95_latency_ms", "INT", null=False),
            Column("budget_cost_per_answer_usd", "NUMERIC(10,4)", null=False),
            Column("eval_suites", "TEXT[]", null=False,
                   comment="Suites this version declares it is evaluated by."),
            Column("eval_threshold_pct", "NUMERIC(5,2)", null=False,
                   comment="The version's own declared pass threshold; the gate reads it here "
                           "rather than from a manifest, so a published version carries the "
                           "bar it was judged against."),
            Column("eval_run_id", "TEXT", references="evaluation_run(eval_run_id)"),
            Column("canary_traffic_pct", "NUMERIC(5,2)"),
            Column("published_at", "TIMESTAMPTZ"),
            Column("published_by", "TEXT", references="party(party_id)"),
            Column("retired_at", "TIMESTAMPTZ"),
        ],
        unique_together=[("agent_id", "semver")],
        indexes=[Index(columns="agent_id, status", name="agent_version_status_idx")],
    ),
    Table(
        name="agent_kpi_coverage",
        group="supply_agents",
        purpose="The agent's functional contract: which KPI, at which grains and slices, how deep.",
        invariants=["I4"],
        columns=[
            Column("coverage_id", "TEXT", primary_key=True),
            Column("agent_version_id", "TEXT", null=False,
                   references="agent_version(agent_version_id)", on_delete="CASCADE"),
            Column("kpi_id", "TEXT", null=False, references="kpi_definition(kpi_id)",
                   comment="I4: coverage cannot cite a KPI that does not exist."),
            Column("source_product_id", "TEXT", null=False, references="data_product(product_id)"),
            Column("columns_used", "TEXT[]", null=False),
            Column("supported_grains", "TEXT[]", null=False),
            Column("supported_slices", "TEXT[]", null=False),
            Column("analysis_depth", "TEXT", null=False,
                   check="analysis_depth IN ('report','compare','explain','rank_drivers','forecast')"),
            Column("eval_accuracy", "NUMERIC(5,2)"),
            Column("eval_sample_size", "INT"),
        ],
        unique_together=[("agent_version_id", "kpi_id")],
    ),
    Table(
        name="agent_product_binding",
        group="supply_agents",
        purpose="Which product columns an agent version may read. The scope half of I12.",
        columns=[
            Column("binding_id", "TEXT", primary_key=True),
            Column("agent_version_id", "TEXT", null=False,
                   references="agent_version(agent_version_id)", on_delete="CASCADE"),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)"),
            Column("columns_allowed", "TEXT[]", null=False),
            Column("access_level", "TEXT", null=False,
                   check="access_level IN ('read','read_pii')"),
            Column("contract_version_pinned", "TEXT", null=False),
        ],
        unique_together=[("agent_version_id", "product_id")],
    ),
    Table(
        name="agent_tool_binding",
        group="supply_agents",
        purpose="A tool the agent may call, with its scope, row limit and cost class.",
        columns=[
            Column("tool_binding_id", "TEXT", primary_key=True),
            Column("agent_version_id", "TEXT", null=False,
                   references="agent_version(agent_version_id)", on_delete="CASCADE"),
            Column("tool_name", "TEXT", null=False),
            Column("endpoint_uri", "TEXT", null=False),
            Column("required_scope", "TEXT", null=False),
            Column("cost_class", "TEXT", null=False,
                   check="cost_class IN ('trivial','small','medium','large')"),
            Column("row_limit", "INT"),
        ],
        unique_together=[("agent_version_id", "tool_name")],
    ),
    Table(
        name="demo_exchange",
        group="supply_agents",
        purpose="A curated question with a golden answer. Five are required to publish (I3).",
        invariants=["I3"],
        columns=[
            Column("exchange_id", "TEXT", primary_key=True),
            Column("agent_version_id", "TEXT", null=False,
                   references="agent_version(agent_version_id)", on_delete="CASCADE"),
            Column("ordinal", "INT", null=False),
            Column("question", "TEXT", null=False),
            Column("kpi_class", "TEXT", null=False, references="kpi_definition(kpi_id)"),
            Column("analysis_type", "TEXT", null=False),
            Column("expected_shape", "JSONB", null=False,
                   comment="headline, visual, table_columns, must_cite[]"),
            Column("data_tier", "TEXT", null=False, check="data_tier IN ('demo','live')"),
            Column("max_latency_ms", "INT", null=False),
            Column("golden_answer_ref", "TEXT", null=False),
            Column("tolerance_pct", "NUMERIC(5,2)", null=False),
            Column("last_validated", "TIMESTAMPTZ"),
            Column("validation_state", "TEXT", null=False,
                   check="validation_state IN ('passing','stale','failing')"),
        ],
        unique_together=[("agent_version_id", "ordinal")],
    ),
    Table(
        name="evaluation_case",
        group="supply_agents",
        purpose="One case in an evaluation suite, including cases harvested from rejections.",
        columns=[
            Column("case_id", "TEXT", primary_key=True),
            Column("agent_id", "TEXT", null=False, references="agent(agent_id)"),
            Column("suite", "TEXT", null=False,
                   check="suite IN ('golden_accuracy','groundedness','boundary_refusal',"
                         "'adversarial','entitlement','compositional_exposure','consistency',"
                         "'cost_latency')"),
            Column("question", "TEXT", null=False),
            Column("persona_ref", "TEXT"),
            Column("expected_behaviour", "TEXT", null=False),
            Column("expected_payload", "JSONB", null=False),
            Column("blocking", "BOOLEAN", null=False),
            Column("origin", "TEXT", null=False,
                   check="origin IN ('authored','feedback','incident','regression')"),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[Index(columns="agent_id, suite", name="evaluation_case_suite_idx")],
    ),
]

# ---------------------------------------------------------------------------
# Config — rubrics and policy. Declared before quality because scores cite them.
# ---------------------------------------------------------------------------

CONFIG: list[Table] = [
    Table(
        name="rubric",
        group="config",
        purpose="A named body of versioned configuration: quality, ranking, mesh, demand, value, finops.",
        columns=[
            Column("rubric_id", "TEXT", primary_key=True),
            Column("code", "TEXT", null=False),
            Column("description", "TEXT", null=False),
            Column("current_version_id", "TEXT"),
        ],
        unique_together=[("tenant_id", "code")],
    ),
    Table(
        name="rubric_version",
        group="config",
        purpose="An immutable rubric version. Every score records the id it was computed under.",
        columns=[
            Column("rubric_version_id", "TEXT", primary_key=True),
            Column("rubric_id", "TEXT", null=False, references="rubric(rubric_id)"),
            Column("semver", "TEXT", null=False),
            Column("source_hash", "TEXT", null=False,
                   comment="sha256 of the YAML that produced this version."),
            Column("payload", "JSONB", null=False,
                   comment="The whole rubric document, so a score can be replayed exactly."),
            Column("effective_from", "TIMESTAMPTZ", null=False, default="now()"),
            Column("superseded_at", "TIMESTAMPTZ"),
            Column("created_by", "TEXT", null=False),
        ],
        unique_together=[("rubric_id", "semver")],
    ),
    Table(
        name="rubric_criterion",
        group="config",
        purpose="One addressable value inside a rubric version: a weight, threshold, band or target.",
        columns=[
            Column("criterion_id", "TEXT", primary_key=True),
            Column("rubric_version_id", "TEXT", null=False,
                   references="rubric_version(rubric_version_id)", on_delete="CASCADE"),
            Column("path", "TEXT", null=False,
                   comment="Dotted path into the rubric document, e.g. dimensions.freshness.weight"),
            Column("kind", "TEXT", null=False,
                   check="kind IN ('weight','threshold','band','multiplier','target','reference',"
                         "'formula','flag','list')"),
            Column("numeric_value", "NUMERIC(14,6)"),
            Column("text_value", "TEXT"),
            Column("scope", "TEXT",
                   comment="Optional qualifier, e.g. the archetype an override applies to."),
        ],
        unique_together=[("rubric_version_id", "path", "scope")],
        indexes=[Index(columns="rubric_version_id, path", name="rubric_criterion_lookup_idx")],
    ),
    Table(
        name="policy",
        group="config",
        purpose="An access, residency, licence or separation-of-duties policy.",
        columns=[
            Column("policy_id", "TEXT", primary_key=True),
            Column("code", "TEXT", null=False),
            Column("category", "TEXT", null=False,
                   check="category IN ('access','residency','licence','sod','retention','purpose')"),
            Column("description", "TEXT", null=False),
            Column("current_version_id", "TEXT"),
        ],
        unique_together=[("tenant_id", "code")],
    ),
    Table(
        name="policy_version",
        group="config",
        purpose="An immutable policy version. Every decision records the version in force.",
        columns=[
            Column("policy_version_id", "TEXT", primary_key=True),
            Column("policy_id", "TEXT", null=False, references="policy(policy_id)"),
            Column("semver", "TEXT", null=False),
            Column("rules", "JSONB", null=False),
            Column("effective_from", "TIMESTAMPTZ", null=False, default="now()"),
            Column("superseded_at", "TIMESTAMPTZ"),
        ],
        unique_together=[("policy_id", "semver")],
    ),
    Table(
        name="feature_flag",
        group="config",
        purpose="A typed flag. Release and experiment flags carry a max age the lint enforces.",
        columns=[
            Column("flag_id", "TEXT", primary_key=True),
            Column("code", "TEXT", null=False),
            Column("flag_type", "TEXT", null=False,
                   check="flag_type IN ('release','experiment','operational')"),
            Column("enabled", "BOOLEAN", null=False, default="false"),
            Column("description", "TEXT", null=False),
            Column("owner_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("expires_at", "TIMESTAMPTZ"),
        ],
        unique_together=[("tenant_id", "code")],
    ),
]

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

QUALITY: list[Table] = [
    Table(
        name="quality_rule",
        group="quality",
        purpose="An executable expectation declared by a product manifest.",
        columns=[
            Column("rule_id", "TEXT", primary_key=True),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)",
                   on_delete="CASCADE"),
            Column("dimension", "TEXT", null=False,
                   check="dimension IN ('completeness','accuracy','freshness','consistency',"
                         "'validity','uniqueness')"),
            Column("rule_type", "TEXT", null=False),
            Column("target_columns", "TEXT[]", null=False, default="'{}'"),
            Column("threshold_pct", "NUMERIC(6,3)"),
            Column("target_text", "TEXT"),
            Column("tolerance_minutes", "INT"),
            Column("severity", "TEXT", null=False,
                   check="severity IN ('critical','high','medium','low')"),
            Column("enabled", "BOOLEAN", null=False, default="true"),
        ],
    ),
    Table(
        name="quality_result",
        group="quality",
        purpose="One evaluation of one rule. The evidence a composite is computed from.",
        columns=[
            Column("result_id", "TEXT", primary_key=True),
            Column("rule_id", "TEXT", null=False, references="quality_rule(rule_id)"),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)"),
            Column("observed_pct", "NUMERIC(9,4)",
                   comment="For a rule expressed as a percentage against a threshold."),
            Column("observed_value", "NUMERIC(14,4)",
                   comment="For a rule expressed as a measure against a tolerance, "
                           "such as freshness lag in minutes."),
            Column("observed_unit", "TEXT"),
            Column("observed_text", "TEXT"),
            Column("passed", "BOOLEAN", null=False),
            Column("rows_evaluated", "BIGINT"),
            Column("source", "TEXT", null=False,
                   check="source IN ('dmf','soda','montecarlo','internal','manual')"),
            Column("evaluated_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[Index(columns="product_id, evaluated_at DESC", name="quality_result_recent_idx")],
    ),
    Table(
        name="quality_score_snapshot",
        group="quality",
        purpose="An immutable composite score, replayable from its evidence and rubric version.",
        invariants=["I2"],
        append_only=True,
        columns=[
            Column("snapshot_id", "TEXT", primary_key=True),
            Column("product_id", "TEXT", null=False, references="data_product(product_id)"),
            Column("rubric_version_id", "TEXT", null=False,
                   references="rubric_version(rubric_version_id)",
                   comment="I2: a score without the rubric it was computed under is meaningless."),
            Column("composite", "NUMERIC(5,2)", null=False),
            Column("completeness", "NUMERIC(5,2)"),
            Column("accuracy", "NUMERIC(5,2)"),
            Column("freshness", "NUMERIC(5,2)"),
            Column("consistency", "NUMERIC(5,2)"),
            Column("validity", "NUMERIC(5,2)"),
            Column("uniqueness", "NUMERIC(5,2)"),
            Column("band", "TEXT", null=False,
                   comment="Resolved from rubric bands, never from code."),
            Column("blocker_applied", "TEXT",
                   comment="Which hard blocker capped the composite, if any."),
            Column("evidence_ref", "JSONB", null=False,
                   comment="rule_ids + result_ids that produced this score."),
            Column("computed_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[
            Index(columns="product_id, computed_at DESC", name="quality_snapshot_recent_idx"),
        ],
    ),
    Table(
        name="incident",
        group="quality",
        purpose="A detected breach. Severity is computed from blast radius, never chosen.",
        columns=[
            Column("incident_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent','source_system','kpi')"),
            Column("asset_id", "TEXT", null=False),
            Column("signal", "TEXT", null=False),
            Column("guarantee_breached", "TEXT"),
            Column("severity", "TEXT", null=False,
                   check="severity IN ('sev1','sev2','sev3','sev4')"),
            Column("severity_inputs", "JSONB", null=False,
                   comment="consumer count x sensitivity rank x guarantee, so severity is auditable."),
            Column("status", "TEXT", null=False,
                   check="status IN ('open','mitigating','resolved','closed')"),
            Column("detected_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("notified_at", "TIMESTAMPTZ"),
            Column("resolved_at", "TIMESTAMPTZ"),
            Column("root_cause", "TEXT"),
            Column("owner_context", "TEXT",
                   comment="Owners may add context; they cannot suppress consumer notification."),
        ],
        indexes=[Index(columns="asset_type, asset_id, status", name="incident_asset_idx")],
    ),
    Table(
        name="incident_impact",
        group="quality",
        purpose="Who an incident reached. Drives banners on every affected listing.",
        columns=[
            Column("impact_id", "TEXT", primary_key=True),
            Column("incident_id", "TEXT", null=False, references="incident(incident_id)",
                   on_delete="CASCADE"),
            Column("affected_asset_type", "TEXT", null=False,
                   check="affected_asset_type IN ('data_product','agent')"),
            Column("affected_asset_id", "TEXT", null=False),
            Column("consumer_count", "INT", null=False),
            Column("notified_at", "TIMESTAMPTZ"),
            Column("banner_active", "BOOLEAN", null=False, default="true"),
        ],
        unique_together=[("incident_id", "affected_asset_type", "affected_asset_id")],
    ),
]

# ---------------------------------------------------------------------------
# Lineage and mesh
# ---------------------------------------------------------------------------

LINEAGE_MESH: list[Table] = [
    Table(
        name="lineage_edge",
        group="lineage_mesh",
        purpose="Harvested upstream/downstream relationship. Blast radius walks this.",
        columns=[
            Column("lineage_id", "TEXT", primary_key=True),
            Column("upstream_type", "TEXT", null=False,
                   check="upstream_type IN ('source_system','data_product')"),
            Column("upstream_id", "TEXT", null=False),
            Column("downstream_type", "TEXT", null=False,
                   check="downstream_type IN ('data_product','agent')"),
            Column("downstream_id", "TEXT", null=False),
            Column("relationship", "TEXT", null=False,
                   check="relationship IN ('derives_from','reads','joins','aggregates')"),
            Column("harvested_from", "TEXT", null=False),
            Column("confidence", "NUMERIC(4,3)", null=False),
            Column("rationale", "TEXT", null=False, check="length(trim(rationale)) > 10"),
            Column("harvested_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        unique_together=[
            ("upstream_type", "upstream_id", "downstream_type", "downstream_id", "relationship")
        ],
        indexes=[
            Index(columns="upstream_type, upstream_id", name="lineage_upstream_idx"),
            Index(columns="downstream_type, downstream_id", name="lineage_downstream_idx"),
        ],
    ),
    Table(
        name="mesh_edge_data",
        group="lineage_mesh",
        purpose="A computed relationship between two data products (I6).",
        invariants=["I6"],
        columns=[
            Column("edge_id", "TEXT", primary_key=True),
            Column("product_a", "TEXT", null=False, references="data_product(product_id)"),
            Column("product_b", "TEXT", null=False, references="data_product(product_id)"),
            Column("edge_type", "TEXT", null=False,
                   check="edge_type IN ('shared_source','dependency','shared_entity','shared_kpi',"
                         "'semantic','co_consumption')"),
            Column("strength", "NUMERIC(4,3)", null=False, check="strength BETWEEN 0 AND 1"),
            Column("factors", "JSONB", null=False),
            Column("confidence", "NUMERIC(4,3)", null=False),
            Column("rationale", "TEXT", null=False, check="length(trim(rationale)) > 10",
                   comment="I6: an edge nobody can explain is not rendered."),
            Column("reviewed_by", "TEXT", references="party(party_id)"),
            Column("reviewed_at", "TIMESTAMPTZ"),
            Column("computed_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        table_checks=[
            "product_a < product_b",
            "confidence >= 0.80 OR reviewed_by IS NOT NULL",
        ],
        unique_together=[("product_a", "product_b", "edge_type")],
        indexes=[
            Index(columns="product_a", name="mesh_data_a_idx"),
            Index(columns="product_b", name="mesh_data_b_idx"),
        ],
    ),
    Table(
        name="mesh_edge_agent",
        group="lineage_mesh",
        purpose="A computed relationship between two agents (I6).",
        invariants=["I6"],
        columns=[
            Column("edge_id", "TEXT", primary_key=True),
            Column("agent_a", "TEXT", null=False, references="agent(agent_id)"),
            Column("agent_b", "TEXT", null=False, references="agent(agent_id)"),
            Column("edge_type", "TEXT", null=False,
                   check="edge_type IN ('shared_data_product','shared_kpi','semantic','same_domain',"
                         "'co_usage','handoff')"),
            Column("strength", "NUMERIC(4,3)", null=False, check="strength BETWEEN 0 AND 1"),
            Column("factors", "JSONB", null=False),
            Column("confidence", "NUMERIC(4,3)", null=False),
            Column("rationale", "TEXT", null=False, check="length(trim(rationale)) > 10"),
            Column("reviewed_by", "TEXT", references="party(party_id)"),
            Column("reviewed_at", "TIMESTAMPTZ"),
            Column("computed_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        table_checks=[
            "agent_a < agent_b",
            "confidence >= 0.80 OR reviewed_by IS NOT NULL",
        ],
        unique_together=[("agent_a", "agent_b", "edge_type")],
        indexes=[
            Index(columns="agent_a", name="mesh_agent_a_idx"),
            Index(columns="agent_b", name="mesh_agent_b_idx"),
        ],
    ),
    Table(
        name="asset_embedding",
        group="lineage_mesh",
        purpose="Semantic vector for hybrid search and semantic mesh similarity.",
        columns=[
            Column("embedding_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent','kpi','glossary_term','demand')"),
            Column("asset_id", "TEXT", null=False),
            Column("model_id", "TEXT", null=False),
            Column("source_text", "TEXT", null=False),
            Column("embedding", "vector(384)", null=False),
            Column("computed_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        unique_together=[("asset_type", "asset_id", "model_id")],
        indexes=[
            Index(columns="embedding vector_cosine_ops", using="hnsw",
                  name="asset_embedding_hnsw_idx"),
        ],
    ),
    Table(
        name="asset_search_document",
        group="lineage_mesh",
        purpose="Lexical side of hybrid search: a maintained tsvector plus the exact-name key.",
        columns=[
            Column("document_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent','kpi','glossary_term')"),
            Column("asset_id", "TEXT", null=False),
            Column("exact_name", "TEXT", null=False),
            Column("body", "TEXT", null=False),
            Column("search_vector", "tsvector", null=False),
            Column("updated_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        unique_together=[("asset_type", "asset_id")],
        indexes=[
            Index(columns="search_vector", using="gin", name="asset_search_vector_idx"),
            Index(columns="lower(exact_name) gin_trgm_ops", using="gin",
                  name="asset_search_name_trgm_idx"),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Demand and workflow
# ---------------------------------------------------------------------------

DEMAND_WORKFLOW: list[Table] = [
    Table(
        name="request",
        group="demand_workflow",
        purpose="One governed request: access, enhancement or new supply.",
        columns=[
            Column("request_id", "TEXT", primary_key=True),
            Column("request_type", "TEXT", null=False,
                   check="request_type IN ('access','enhancement','supply')"),
            Column("state", "TEXT", null=False),
            Column("requester_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("title", "TEXT", null=False),
            Column("body", "TEXT", null=False),
            Column("purpose_code", "TEXT", references="purpose_category(code)"),
            Column("purpose_text", "TEXT"),
            Column("policy_path", "TEXT",
                   comment="Approval path resolved before submission: auto, owner, owner_steward, ..."),
            Column("policy_version_id", "TEXT", references="policy_version(policy_version_id)"),
            Column("sla_hours", "INT"),
            Column("sla_due_at", "TIMESTAMPTZ"),
            Column("escalated_at", "TIMESTAMPTZ"),
            Column("submitted_at", "TIMESTAMPTZ"),
            Column("closed_at", "TIMESTAMPTZ"),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[
            Index(columns="request_type, state", name="request_state_idx"),
            Index(columns="requester_party_id", name="request_requester_idx"),
            Index(columns="sla_due_at", where="closed_at IS NULL", name="request_sla_idx"),
        ],
    ),
    Table(
        name="request_item",
        group="demand_workflow",
        purpose="One asset and access level within a request; a request may be partially approved.",
        columns=[
            Column("request_item_id", "TEXT", primary_key=True),
            Column("request_id", "TEXT", null=False, references="request(request_id)",
                   on_delete="CASCADE"),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("access_level", "TEXT", null=False,
                   check="access_level IN ('read_metadata','read_data','read_data_pii',"
                         "'agent_invoke','write_back')"),
            Column("columns_requested", "TEXT[]", null=False, default="'{}'"),
            Column("outcome", "TEXT",
                   check="outcome IN ('approved','declined','withdrawn')"),
            Column("outcome_reason", "TEXT"),
        ],
        unique_together=[("request_id", "asset_type", "asset_id", "access_level")],
    ),
    Table(
        name="approval_step",
        group="demand_workflow",
        purpose="One required approval in the resolved path, with its own SLA clock.",
        columns=[
            Column("step_id", "TEXT", primary_key=True),
            Column("request_id", "TEXT", null=False, references="request(request_id)",
                   on_delete="CASCADE"),
            Column("ordinal", "INT", null=False),
            Column("approver_role", "TEXT", null=False),
            Column("approver_party_id", "TEXT", references="party(party_id)"),
            Column("state", "TEXT", null=False,
                   check="state IN ('pending','approved','declined','skipped','escalated')"),
            Column("due_at", "TIMESTAMPTZ"),
            Column("acted_at", "TIMESTAMPTZ"),
        ],
        unique_together=[("request_id", "ordinal")],
    ),
    Table(
        name="decision",
        group="demand_workflow",
        purpose="Actor, timestamp, decision, reason and the policy version in force.",
        columns=[
            Column("decision_id", "TEXT", primary_key=True),
            Column("request_id", "TEXT", null=False, references="request(request_id)"),
            Column("step_id", "TEXT", references="approval_step(step_id)"),
            Column("actor_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("outcome", "TEXT", null=False,
                   check="outcome IN ('approve','decline','partial','block','withdraw')"),
            Column("reason_code", "TEXT", null=False),
            Column("reason_text", "TEXT", null=False),
            Column("policy_version_id", "TEXT", references="policy_version(policy_version_id)"),
            Column("decided_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[Index(columns="request_id, decided_at", name="decision_request_idx")],
    ),
    Table(
        name="enhancement",
        group="demand_workflow",
        purpose="An enhancement to an existing asset. Declines are public and reasoned.",
        columns=[
            Column("enhancement_id", "TEXT", primary_key=True),
            Column("request_id", "TEXT", null=False, references="request(request_id)"),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("state", "TEXT", null=False,
                   check="state IN ('submitted','triaged','assessed','accepted','declined',"
                         "'merged','scheduled','in_progress','delivered','verified','auto_closed')"),
            Column("decline_reason_code", "TEXT",
                   check="decline_reason_code IN ('out_of_scope','source_unavailable',"
                         "'cost_prohibitive','duplicate','superseded','security_constraint')"),
            Column("decline_reason_text", "TEXT"),
            Column("merged_into", "TEXT", references="enhancement(enhancement_id)"),
            Column("triage_due_at", "TIMESTAMPTZ"),
            Column("delivered_at", "TIMESTAMPTZ"),
            Column("verify_due_at", "TIMESTAMPTZ"),
        ],
        table_checks=[
            "state <> 'declined' OR (decline_reason_code IS NOT NULL "
            "AND length(trim(coalesce(decline_reason_text,''))) > 0)"
        ],
    ),
    Table(
        name="demand_theme",
        group="demand_workflow",
        purpose="A cluster of demand items. Five distinct requesting teams auto-escalates it.",
        columns=[
            Column("theme_id", "TEXT", primary_key=True),
            Column("label", "TEXT", null=False),
            Column("summary", "TEXT", null=False),
            Column("distinct_team_count", "INT", null=False, default="0"),
            Column("escalated_at", "TIMESTAMPTZ"),
            Column("confidence", "NUMERIC(4,3)", null=False),
            Column("rationale", "TEXT", null=False, check="length(trim(rationale)) > 10"),
        ],
    ),
    Table(
        name="demand_item",
        group="demand_workflow",
        purpose="A new-supply request on the public board, scored against the demand rubric.",
        columns=[
            Column("demand_id", "TEXT", primary_key=True),
            Column("request_id", "TEXT", null=False, references="request(request_id)"),
            Column("theme_id", "TEXT", references="demand_theme(theme_id)"),
            Column("state", "TEXT", null=False,
                   check="state IN ('submitted','duplicate_review','triaged','scored',"
                         "'roadmapped','in_build','delivered','declined')"),
            Column("score", "NUMERIC(5,2)"),
            Column("score_breakdown", "JSONB"),
            Column("rubric_version_id", "TEXT", references="rubric_version(rubric_version_id)"),
            Column("decline_reason_public", "TEXT"),
            Column("draft_manifest", "JSONB",
                   comment="Generated on acceptance with confidence and rationale per field."),
        ],
    ),
    Table(
        name="duplicate_match",
        group="demand_workflow",
        purpose="A candidate duplicate found at submission, with its contributing factors.",
        columns=[
            Column("match_id", "TEXT", primary_key=True),
            Column("demand_id", "TEXT", null=False, references="demand_item(demand_id)",
                   on_delete="CASCADE"),
            Column("candidate_type", "TEXT", null=False,
                   check="candidate_type IN ('data_product','agent','demand')"),
            Column("candidate_id", "TEXT", null=False),
            Column("similarity", "NUMERIC(4,3)", null=False),
            Column("contributing_factors", "JSONB", null=False),
            Column("confidence", "NUMERIC(4,3)", null=False),
            Column("rationale", "TEXT", null=False, check="length(trim(rationale)) > 10"),
            Column("disposition", "TEXT", null=False,
                   check="disposition IN ('blocking','advisory','informational','architect_review')"),
            Column("reviewed_by", "TEXT", references="party(party_id)"),
        ],
        unique_together=[("demand_id", "candidate_type", "candidate_id")],
    ),
    Table(
        name="demand_vote",
        group="demand_workflow",
        purpose="A vote. It requires a one-line use case: a vote without context is not counted.",
        columns=[
            Column("vote_id", "TEXT", primary_key=True),
            Column("demand_id", "TEXT", null=False, references="demand_item(demand_id)",
                   on_delete="CASCADE"),
            Column("voter_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("use_case", "TEXT", null=False, check="length(trim(use_case)) > 10"),
            Column("org_unit_id", "TEXT", references="org_unit(org_unit_id)"),
            Column("voted_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        unique_together=[("demand_id", "voter_party_id")],
    ),
    Table(
        name="workflow_instance",
        group="demand_workflow",
        purpose="Durable workflow state. An approval survives a process restart (D-003).",
        columns=[
            Column("instance_id", "TEXT", primary_key=True),
            Column("workflow_type", "TEXT", null=False,
                   check="workflow_type IN ('access','enhancement','demand','provisioning',"
                         "'revocation','canary')"),
            Column("subject_id", "TEXT", null=False),
            Column("state", "TEXT", null=False),
            Column("payload", "JSONB", null=False),
            Column("run_after", "TIMESTAMPTZ", null=False, default="now()"),
            Column("attempts", "INT", null=False, default="0"),
            Column("last_error", "TEXT"),
            Column("completed_at", "TIMESTAMPTZ"),
            Column("created_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[
            Index(columns="run_after", where="completed_at IS NULL", name="workflow_due_idx"),
            Index(columns="workflow_type, subject_id", name="workflow_subject_idx"),
        ],
    ),
    Table(
        name="workflow_event",
        group="demand_workflow",
        purpose="Append-only transition log for a workflow instance; replayable.",
        columns=[
            Column("event_id", "TEXT", primary_key=True),
            Column("instance_id", "TEXT", null=False,
                   references="workflow_instance(instance_id)", on_delete="CASCADE"),
            Column("from_state", "TEXT"),
            Column("to_state", "TEXT", null=False),
            Column("actor", "TEXT", null=False),
            Column("detail", "JSONB", null=False),
            Column("occurred_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[Index(columns="instance_id, occurred_at", name="workflow_event_order_idx")],
    ),
]

# ---------------------------------------------------------------------------
# Entitlement
# ---------------------------------------------------------------------------

ENTITLEMENT: list[Table] = [
    Table(
        name="entitlement_grant",
        group="entitlement",
        purpose="The record of what was granted. Effective permission lives in the platform, not here.",
        append_only=True,
        columns=[
            Column("grant_id", "TEXT", primary_key=True),
            Column("request_id", "TEXT", null=False, references="request(request_id)"),
            Column("principal_id", "TEXT", null=False, references="party(party_id)"),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("access_level", "TEXT", null=False,
                   check="access_level IN ('read_metadata','read_data','read_data_pii',"
                         "'agent_invoke','write_back')"),
            Column("purpose_code", "TEXT", null=False, references="purpose_category(code)"),
            Column("purpose_text", "TEXT", null=False),
            Column("platform_role", "TEXT", null=False, comment="MKT_<PRODUCT>_<LEVEL>"),
            Column("oauth_scopes", "TEXT[]", null=False),
            Column("granted_at", "TIMESTAMPTZ", null=False),
            Column("expires_at", "TIMESTAMPTZ", null=False),
            Column("revoked_at", "TIMESTAMPTZ"),
            Column("revocation_reason", "TEXT"),
            Column("last_used_at", "TIMESTAMPTZ"),
            Column("dormant_flagged_at", "TIMESTAMPTZ"),
            Column("renewal_notified_at", "TIMESTAMPTZ"),
        ],
        indexes=[
            Index(columns="principal_id, asset_id", where="revoked_at IS NULL",
                  name="entitlement_active_idx"),
            Index(columns="expires_at", where="revoked_at IS NULL",
                  name="entitlement_expiry_idx"),
        ],
    ),
    Table(
        name="grant_scope",
        group="entitlement",
        purpose="Column-level narrowing of a grant. A grant is never wider than its scope rows.",
        columns=[
            Column("scope_id", "TEXT", primary_key=True),
            Column("grant_id", "TEXT", null=False, references="entitlement_grant(grant_id)"),
            Column("scope_kind", "TEXT", null=False,
                   check="scope_kind IN ('columns','rows','tools')"),
            Column("expression", "TEXT", null=False),
            Column("applied_in_platform", "BOOLEAN", null=False, default="false"),
        ],
    ),
    Table(
        name="purpose_binding",
        group="entitlement",
        purpose="The declared purpose attached to a grant and logged with every query under it.",
        columns=[
            Column("binding_id", "TEXT", primary_key=True),
            Column("grant_id", "TEXT", null=False, references="entitlement_grant(grant_id)"),
            Column("purpose_code", "TEXT", null=False, references="purpose_category(code)"),
            Column("purpose_text", "TEXT", null=False, check="length(trim(purpose_text)) > 5"),
            Column("bound_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("bound_by", "TEXT", null=False, references="party(party_id)"),
        ],
        unique_together=[("grant_id", "purpose_code")],
    ),
    Table(
        name="revocation",
        group="entitlement",
        purpose="Why a grant ended: expiry, self-revoke, admin revoke, dormancy or drift.",
        columns=[
            Column("revocation_id", "TEXT", primary_key=True),
            Column("grant_id", "TEXT", null=False, references="entitlement_grant(grant_id)"),
            Column("reason_code", "TEXT", null=False,
                   check="reason_code IN ('expired','self_revoked','admin_revoked','dormant',"
                         "'policy_change','drift_reconciliation','offboarded')"),
            Column("reason_text", "TEXT", null=False),
            Column("actor_party_id", "TEXT", references="party(party_id)"),
            Column("platform_confirmed", "BOOLEAN", null=False, default="false"),
            Column("revoked_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
    ),
    Table(
        name="entitlement_drift",
        group="entitlement",
        purpose="Nightly reconciliation finding: register says one thing, platform says another.",
        columns=[
            Column("drift_id", "TEXT", primary_key=True),
            Column("platform", "TEXT", null=False),
            Column("principal_ref", "TEXT", null=False),
            Column("asset_ref", "TEXT", null=False),
            Column("drift_type", "TEXT", null=False,
                   check="drift_type IN ('missing_in_platform','extra_in_platform',"
                         "'level_mismatch','expired_but_present')"),
            Column("register_state", "JSONB", null=False),
            Column("platform_state", "JSONB", null=False),
            Column("incident_id", "TEXT", references="incident(incident_id)"),
            Column("detected_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("resolved_at", "TIMESTAMPTZ"),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------

TELEMETRY: list[Table] = [
    Table(
        name="usage_event",
        group="telemetry",
        purpose="A metadata-level consumption event. No row-level customer data (rule 5).",
        columns=[
            Column("event_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("principal_id", "TEXT", references="party(party_id)"),
            Column("surface", "TEXT", null=False),
            Column("event_name", "TEXT", null=False,
                   comment="From the typed event taxonomy; a new name must be added there first."),
            Column("purpose_code", "TEXT", references="purpose_category(code)"),
            Column("rows_returned", "BIGINT"),
            Column("columns_returned", "TEXT[]"),
            Column("outcome", "TEXT", null=False,
                   check="outcome IN ('ok','denied','error','throttled')"),
            Column("occurred_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[
            Index(columns="asset_type, asset_id, occurred_at DESC", name="usage_asset_idx"),
            Index(columns="outcome, occurred_at DESC", where="outcome = 'denied'",
                  name="usage_denied_idx"),
        ],
    ),
    Table(
        name="usage_daily_agg",
        group="telemetry",
        purpose="Pre-aggregated adoption. Card counts and ranking read this, not raw events.",
        columns=[
            Column("agg_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("activity_date", "DATE", null=False),
            Column("active_consumers", "INT", null=False),
            Column("distinct_teams", "INT", null=False),
            Column("query_count", "BIGINT", null=False),
            Column("denied_count", "BIGINT", null=False),
            Column("rows_scanned", "BIGINT", null=False),
        ],
        unique_together=[("asset_type", "asset_id", "activity_date")],
        indexes=[Index(columns="asset_id, activity_date DESC", name="usage_agg_recent_idx")],
    ),
    Table(
        name="agent_interaction",
        group="telemetry",
        purpose="One question answered, with its trace. The evidence behind value and FinOps.",
        columns=[
            Column("interaction_id", "TEXT", primary_key=True),
            Column("agent_version_id", "TEXT", null=False,
                   references="agent_version(agent_version_id)"),
            Column("principal_id", "TEXT", references="party(party_id)"),
            Column("session_id", "TEXT", null=False),
            Column("tier", "TEXT", null=False, check="tier IN ('demo','live')"),
            Column("question", "TEXT", null=False),
            Column("question_class", "TEXT", null=False),
            Column("purpose_code", "TEXT", references="purpose_category(code)"),
            Column("outcome", "TEXT", null=False,
                   check="outcome IN ('answered','out_of_scope','ungrounded','denied','error')"),
            Column("grounded", "BOOLEAN", null=False),
            Column("confidence", "NUMERIC(4,3)"),
            Column("citations", "JSONB", null=False, default="'[]'::jsonb"),
            Column("kpi_definitions", "TEXT[]", null=False, default="'{}'"),
            Column("tool_calls", "JSONB", null=False, default="'[]'::jsonb"),
            Column("rows_scanned", "BIGINT"),
            Column("latency_ms", "INT", null=False),
            Column("tokens_in", "INT", null=False),
            Column("tokens_out", "INT", null=False),
            Column("cost_usd", "NUMERIC(12,6)", null=False),
            Column("occurred_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[
            Index(columns="agent_version_id, occurred_at DESC", name="interaction_agent_idx"),
            Index(columns="outcome, occurred_at DESC", name="interaction_outcome_idx"),
        ],
    ),
    Table(
        name="answer_feedback",
        group="telemetry",
        purpose="Acceptance or rejection with a reason; rejections become evaluation cases.",
        columns=[
            Column("feedback_id", "TEXT", primary_key=True),
            Column("interaction_id", "TEXT", null=False,
                   references="agent_interaction(interaction_id)"),
            Column("party_id", "TEXT", null=False, references="party(party_id)"),
            Column("accepted", "BOOLEAN", null=False),
            Column("reason_code", "TEXT", null=False,
                   check="reason_code IN ('correct','useful_partial','wrong_number','wrong_scope',"
                         "'missing_context','stale_data','unclear','other')"),
            Column("reason_text", "TEXT"),
            Column("promoted_case_id", "TEXT", references="evaluation_case(case_id)"),
            Column("submitted_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        unique_together=[("interaction_id", "party_id")],
    ),
    Table(
        name="cost_allocation",
        group="telemetry",
        purpose="Attributed cost per asset per day: inference, retrieval, query, platform, stewardship.",
        columns=[
            Column("allocation_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("cost_date", "DATE", null=False),
            Column("inference_usd", "NUMERIC(14,6)", null=False, default="0"),
            Column("retrieval_usd", "NUMERIC(14,6)", null=False, default="0"),
            Column("query_usd", "NUMERIC(14,6)", null=False, default="0"),
            Column("platform_usd", "NUMERIC(14,6)", null=False, default="0"),
            Column("stewardship_usd", "NUMERIC(14,6)", null=False, default="0"),
            Column("tier", "TEXT", null=False, check="tier IN ('demo','live')"),
            Column("source", "TEXT", null=False),
        ],
        unique_together=[("asset_type", "asset_id", "cost_date", "tier")],
    ),
]

# ---------------------------------------------------------------------------
# Value
# ---------------------------------------------------------------------------

VALUE: list[Table] = [
    Table(
        name="value_case",
        group="value",
        purpose="The quantified case for an asset, with its baseline and attribution confidence.",
        columns=[
            Column("value_case_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("business_outcome", "TEXT", null=False),
            Column("baseline_method", "TEXT", null=False),
            Column("baseline_captured", "DATE", null=False),
            Column("benefit_model", "TEXT", null=False),
            Column("attribution_confidence", "TEXT", null=False,
                   check="attribution_confidence IN ('high','medium','low')"),
            Column("rubric_version_id", "TEXT", null=False,
                   references="rubric_version(rubric_version_id)"),
            Column("last_reviewed", "DATE", null=False),
            Column("reviewer_party_id", "TEXT", null=False, references="party(party_id)"),
            Column("review_due", "DATE", null=False),
        ],
        unique_together=[("asset_type", "asset_id")],
    ),
    Table(
        name="value_assumption",
        group="value",
        purpose="A named assumption with its value, sample size and date. Displayed beside any figure.",
        columns=[
            Column("assumption_id", "TEXT", primary_key=True),
            Column("value_case_id", "TEXT", null=False, references="value_case(value_case_id)",
                   on_delete="CASCADE"),
            Column("text", "TEXT", null=False),
            Column("numeric_value", "NUMERIC(14,4)", null=False),
            Column("unit", "TEXT", null=False),
            Column("sample_size", "INT"),
            Column("source", "TEXT", null=False),
            Column("dated", "DATE", null=False),
        ],
    ),
    Table(
        name="value_measurement",
        group="value",
        purpose="A realised measurement period: deflected hours, value, cost and the ratio.",
        columns=[
            Column("measurement_id", "TEXT", primary_key=True),
            Column("value_case_id", "TEXT", null=False, references="value_case(value_case_id)"),
            Column("period_start", "DATE", null=False),
            Column("period_end", "DATE", null=False),
            Column("answered_questions", "BIGINT", null=False),
            Column("acceptance_rate", "NUMERIC(5,4)", null=False),
            Column("deflected_hours", "NUMERIC(14,4)", null=False),
            Column("deflected_value_usd", "NUMERIC(16,4)", null=False),
            Column("total_cost_usd", "NUMERIC(16,4)", null=False),
            Column("net_value_usd", "NUMERIC(16,4)", null=False),
            Column("value_ratio", "NUMERIC(10,4)", null=False),
            Column("rubric_version_id", "TEXT", null=False,
                   references="rubric_version(rubric_version_id)"),
            Column("snapshot_ref", "TEXT", null=False,
                   comment="Board pack and dashboard read the same snapshot so they cannot disagree."),
            Column("computed_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        unique_together=[("value_case_id", "period_start", "period_end")],
    ),
]

# ---------------------------------------------------------------------------
# Academy
# ---------------------------------------------------------------------------

ACADEMY: list[Table] = [
    Table(
        name="academy_module",
        group="academy",
        purpose="A learning unit, optionally bound to an asset so it can be offered in context.",
        columns=[
            Column("module_id", "TEXT", primary_key=True),
            Column("title", "TEXT", null=False),
            Column("summary", "TEXT", null=False),
            Column("body_ref", "TEXT", null=False),
            Column("estimated_minutes", "INT", null=False),
            Column("asset_type", "TEXT", check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT"),
            Column("sandbox_tier", "TEXT", null=False, default="'demo'",
                   check="sandbox_tier IN ('demo','none')"),
            Column("sort_order", "INT", null=False),
        ],
    ),
    Table(
        name="learning_path",
        group="academy",
        purpose="An ordered set of modules for a persona, ending in a certification.",
        columns=[
            Column("path_id", "TEXT", primary_key=True),
            Column("title", "TEXT", null=False),
            Column("persona", "TEXT", null=False),
            Column("summary", "TEXT", null=False),
            Column("module_ids", "TEXT[]", null=False),
            Column("certification_code", "TEXT"),
        ],
    ),
    Table(
        name="enrollment",
        group="academy",
        purpose="A party's progress through a path.",
        columns=[
            Column("enrollment_id", "TEXT", primary_key=True),
            Column("path_id", "TEXT", null=False, references="learning_path(path_id)"),
            Column("party_id", "TEXT", null=False, references="party(party_id)"),
            Column("state", "TEXT", null=False,
                   check="state IN ('enrolled','in_progress','completed','lapsed')"),
            Column("completed_module_ids", "TEXT[]", null=False, default="'{}'"),
            Column("enrolled_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("completed_at", "TIMESTAMPTZ"),
        ],
        unique_together=[("path_id", "party_id")],
    ),
    Table(
        name="assessment_result",
        group="academy",
        purpose="One assessment attempt. The pass mark is a rubric value, not a constant.",
        columns=[
            Column("result_id", "TEXT", primary_key=True),
            Column("enrollment_id", "TEXT", null=False, references="enrollment(enrollment_id)"),
            Column("module_id", "TEXT", null=False, references="academy_module(module_id)"),
            Column("score_pct", "NUMERIC(5,2)", null=False),
            Column("passed", "BOOLEAN", null=False),
            Column("rubric_version_id", "TEXT", null=False,
                   references="rubric_version(rubric_version_id)"),
            Column("attempted_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
    ),
    Table(
        name="certification",
        group="academy",
        purpose="A held certification, with expiry so competence claims stay current.",
        columns=[
            Column("certification_id", "TEXT", primary_key=True),
            Column("code", "TEXT", null=False),
            Column("party_id", "TEXT", null=False, references="party(party_id)"),
            Column("path_id", "TEXT", null=False, references="learning_path(path_id)"),
            Column("issued_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("expires_at", "TIMESTAMPTZ", null=False),
            Column("revoked_at", "TIMESTAMPTZ"),
        ],
        unique_together=[("code", "party_id")],
    ),
]

# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

AUDIT: list[Table] = [
    Table(
        name="audit_event",
        group="audit",
        purpose="Immutable record of anything touching access, publication or scores. 7-year retention.",
        append_only=True,
        columns=[
            Column("audit_id", "TEXT", primary_key=True),
            Column("event_name", "TEXT", null=False),
            Column("actor_party_id", "TEXT", references="party(party_id)"),
            Column("on_behalf_of", "TEXT", references="party(party_id)",
                   comment="Delegated identity: both identities are logged (section 19)."),
            Column("asset_type", "TEXT"),
            Column("asset_id", "TEXT"),
            Column("purpose_code", "TEXT", references="purpose_category(code)"),
            Column("outcome", "TEXT", null=False),
            Column("detail", "JSONB", null=False),
            Column("policy_version_id", "TEXT", references="policy_version(policy_version_id)"),
            Column("occurred_at", "TIMESTAMPTZ", null=False, default="now()"),
            Column("retain_until", "TIMESTAMPTZ", null=False),
        ],
        indexes=[
            Index(columns="asset_type, asset_id, occurred_at DESC", name="audit_asset_idx"),
            Index(columns="actor_party_id, occurred_at DESC", name="audit_actor_idx"),
            Index(columns="event_name, occurred_at DESC", name="audit_event_name_idx"),
        ],
    ),
    Table(
        name="publication_snapshot",
        group="audit",
        purpose="The exact bundle that reached the shelf, replayable for rollback and audit.",
        append_only=True,
        columns=[
            Column("snapshot_id", "TEXT", primary_key=True),
            Column("asset_type", "TEXT", null=False,
                   check="asset_type IN ('data_product','agent')"),
            Column("asset_id", "TEXT", null=False),
            Column("version_ref", "TEXT", null=False),
            Column("gate_results", "JSONB", null=False),
            Column("bundle", "JSONB", null=False,
                   comment="Pinned model, params, prompt hash, tool bindings, contract and KPI versions."),
            Column("published_by", "TEXT", null=False, references="party(party_id)"),
            Column("published_at", "TIMESTAMPTZ", null=False, default="now()"),
        ],
        indexes=[
            Index(columns="asset_type, asset_id, published_at DESC",
                  name="publication_asset_idx"),
        ],
    ),
]

ALL_TABLES: list[Table] = [
    *REFERENCE,
    *IDENTITY,
    *SUPPLY_DATA,
    *SEMANTICS,
    *CONFIG,
    *SUPPLY_AGENTS,
    *QUALITY,
    *LINEAGE_MESH,
    *DEMAND_WORKFLOW,
    *ENTITLEMENT,
    *TELEMETRY,
    *VALUE,
    *ACADEMY,
    *AUDIT,
]


# ---------------------------------------------------------------------------
# Functions, triggers and views
# ---------------------------------------------------------------------------

SENSITIVITY_DERIVATION = RawBlock(
    name="sensitivity_derivation",
    group="constraints",
    purpose="I5 — data_product.sensitivity_tier is derived from columns, never written.",
    invariants=["I5"],
    sql="""
-- SPEC-QUESTION: BUILD.md 6.2 writes derive_sensitivity as
--   SELECT COALESCE(MAX(t.rank_order), 1)::TEXT ...
-- which yields the rank number ('3'), while data_product.sensitivity_tier is
-- consumed everywhere else as a sensitivity_tier.code ('confidential') — for
-- example data_contract_version.max_sensitivity REFERENCES sensitivity_tier(code).
-- The narrower reading that keeps the value usable is implemented: the function
-- selects the code of the highest-ranked column classification, using exactly the
-- MAX(rank_order) selection rule written in the specification.
CREATE OR REPLACE FUNCTION derive_sensitivity(p_product_id TEXT) RETURNS TEXT AS $$
  SELECT t.code
  FROM data_product_column c
  JOIN sensitivity_tier t ON t.code = c.sensitivity_code
  WHERE c.product_id = p_product_id
  ORDER BY t.rank_order DESC
  LIMIT 1;
$$ LANGUAGE sql STABLE;

-- The lowest tier is the floor for a product that has no classified column yet.
CREATE OR REPLACE FUNCTION lowest_sensitivity_code() RETURNS TEXT AS $$
  SELECT code FROM sensitivity_tier ORDER BY rank_order ASC LIMIT 1;
$$ LANGUAGE sql STABLE;

-- Any value supplied by a writer is discarded and replaced with the derived one,
-- so there is no code path that can set sensitivity directly.
CREATE OR REPLACE FUNCTION data_product_derive_sensitivity() RETURNS TRIGGER AS $$
BEGIN
  NEW.sensitivity_tier :=
    COALESCE(derive_sensitivity(NEW.product_id), lowest_sensitivity_code());
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_product_sensitivity_derived
  BEFORE INSERT OR UPDATE ON data_product
  FOR EACH ROW EXECUTE FUNCTION data_product_derive_sensitivity();

-- Recompute whenever the column set or a classification changes.
CREATE OR REPLACE FUNCTION data_product_column_resensitise() RETURNS TRIGGER AS $$
DECLARE
  affected TEXT := COALESCE(NEW.product_id, OLD.product_id);
BEGIN
  UPDATE data_product
     SET sensitivity_tier = COALESCE(derive_sensitivity(affected), lowest_sensitivity_code())
   WHERE product_id = affected;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_product_column_resensitise
  AFTER INSERT OR UPDATE OR DELETE ON data_product_column
  FOR EACH ROW EXECUTE FUNCTION data_product_column_resensitise();
""".strip(),
)

SEARCH_DOCUMENT_MAINTENANCE = RawBlock(
    name="search_document_maintenance",
    group="constraints",
    purpose="Keep the lexical half of hybrid search in step with its source text.",
    sql="""
CREATE OR REPLACE FUNCTION asset_search_document_vector() RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
      setweight(to_tsvector('english', coalesce(NEW.exact_name, '')), 'A')
   || setweight(to_tsvector('english', coalesce(NEW.body, '')), 'B');
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER asset_search_document_vector
  BEFORE INSERT OR UPDATE ON asset_search_document
  FOR EACH ROW EXECUTE FUNCTION asset_search_document_vector();
""".strip(),
)

APPEND_ONLY_ENFORCEMENT = RawBlock(
    name="append_only_enforcement",
    group="constraints",
    purpose="Rule 6 — no code path issues an UPDATE or DELETE against a snapshot table.",
    sql="""
-- The REVOKE grants stop a least-privileged application role. The trigger stops
-- everything else, including a superuser session and a migration written in a
-- hurry, so immutability does not depend on which role happens to be connected.
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION
    'table % is append-only; % is not permitted (BUILD.md rule 6)',
    TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER quality_score_snapshot_append_only
  BEFORE UPDATE OR DELETE ON quality_score_snapshot
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE TRIGGER publication_snapshot_append_only
  BEFORE UPDATE OR DELETE ON publication_snapshot
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE TRIGGER audit_event_append_only
  BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- entitlement_grant is history: a grant is ended by writing a revocation row and
-- stamping revoked_at / last_used_at / the two notification columns. Every other
-- column is frozen once written, and the row can never be deleted.
CREATE OR REPLACE FUNCTION entitlement_grant_history_only() RETURNS TRIGGER AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'entitlement_grant is append-only; DELETE is not permitted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF ROW(NEW.grant_id, NEW.request_id, NEW.principal_id, NEW.asset_type, NEW.asset_id,
         NEW.access_level, NEW.purpose_code, NEW.purpose_text, NEW.platform_role,
         NEW.oauth_scopes, NEW.granted_at, NEW.expires_at)
     IS DISTINCT FROM
     ROW(OLD.grant_id, OLD.request_id, OLD.principal_id, OLD.asset_type, OLD.asset_id,
         OLD.access_level, OLD.purpose_code, OLD.purpose_text, OLD.platform_role,
         OLD.oauth_scopes, OLD.granted_at, OLD.expires_at)
  THEN
    RAISE EXCEPTION
      'entitlement_grant terms are immutable; revoke the grant and issue a new one'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
    RAISE EXCEPTION 'entitlement_grant revocation is final' USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER entitlement_grant_history_only
  BEFORE UPDATE OR DELETE ON entitlement_grant
  FOR EACH ROW EXECUTE FUNCTION entitlement_grant_history_only();
""".strip(),
)

RAW_BLOCKS: list[RawBlock] = [
    SENSITIVITY_DERIVATION,
    SEARCH_DOCUMENT_MAINTENANCE,
    APPEND_ONLY_ENFORCEMENT,
]
