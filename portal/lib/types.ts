/**
 * Shapes the API returns, mirrored for the portal.
 *
 * Row shapes come from `generated/types` (emitted from the canonical model).
 * The types here are the *response* shapes the API assembles on top of those
 * rows — cards, tabs and pages — which belong to the API contract rather than
 * to the model.
 */

export type TabState = 'populated' | 'partial' | 'partial_permission' | 'empty';

export interface Tab<T> {
  state: TabState;
  data: T | null;
  why?: string;
  required_scope?: string;
  request_access_url?: string;
}

export interface QualitySummary {
  composite: number | null;
  band: string | null;
  rubric_version_id: string | null;
  computed_at: string | null;
}

export interface ProductCard {
  product_id: string;
  name: string;
  purpose: string;
  industry: string;
  domain: string;
  archetype: string;
  certification: 'certified' | 'published' | 'beta' | 'deprecated';
  sensitivity: string;
  tier: string;
  grain: string;
  current_version: string;
  quality: QualitySummary;
  freshness: { target: string | null; p95_minutes: number | null };
  owner: { party_id: string; name: string };
  adoption: { active_consumers: number; distinct_teams: number };
  attached_agents: string[];
  certified_kpis: string[];
  endpoints: string[];
  access: { granted: boolean; required_scope: string; request_access_url: string };
  incident: { incident_id: string; severity: string } | null;
}

export interface FacetValue {
  value: string;
  count: number;
  selected: boolean;
}

export interface Facet {
  code: string;
  label: string;
  values: FacetValue[];
}

export interface CatalogPage {
  items: ProductCard[];
  next_cursor: string | null;
  total: number | null;
  facets: Facet[];
  sort: string;
  rubric_version_id: string;
}

export interface SearchExplanation {
  lexical_rank: number | null;
  semantic_rank: number | null;
  exact_name_match: boolean;
  fused_relevance: number;
  signals: Record<string, number>;
  score: number;
}

export interface SearchResult {
  asset_type: string;
  asset_id: string;
  name: string;
  score: number;
  explanation: SearchExplanation;
}

export interface DiscoverResponse {
  query: string;
  rubric_version_id: string;
  results: SearchResult[];
  empty_state?: {
    message: string;
    nearest: SearchResult[];
    related_demand: { demand_id: string; title: string; state: string; votes: number }[];
    file_supply_request_url: string;
  };
}

export interface OverviewData {
  product_id: string;
  name: string;
  purpose: string;
  grain: string;
  history_months: number;
  known_limitations: string;
  certification: string;
  sensitivity: string;
  tier: string;
  current_version: string;
  industry: string;
  domain: string;
  archetype: string;
  owner: { party_id: string; name: string; email: string | null; team: string | null };
  certified_kpis: string[];
  upstream_sources: string[];
  updated_at: string | null;
}

export interface QualityRule {
  rule_id: string;
  dimension: string;
  rule_type: string;
  target_columns: string[];
  threshold_pct: number | null;
  severity: string;
  enabled: boolean;
}

export interface QualityResultRow {
  result_id: string;
  rule_id: string;
  dimension: string;
  rule_type: string;
  severity: string;
  threshold_pct: number | null;
  observed_pct: number | null;
  passed: boolean;
  source: string;
  evaluated_at: string | null;
}

export interface QualitySnapshot {
  snapshot_id: string;
  composite: number | null;
  band: string | null;
  rubric_version_id: string;
  blocker_applied: string | null;
  dimensions: Record<string, number | null>;
  evidence_ref: unknown;
  computed_at: string | null;
}

export interface QualityData {
  current?: QualitySnapshot;
  history?: Omit<QualitySnapshot, 'dimensions' | 'evidence_ref'>[];
  rules: QualityRule[];
  contributing_results: QualityResultRow[];
}

export interface ContractGuarantee {
  dimension: string;
  target_text: string;
  target_numeric: number | null;
  unit: string;
  measurement_window: string;
  measured_at_grain: string;
  reference_system: string | null;
}

export interface ContractData {
  active: {
    contract_version_id: string;
    semver: string;
    schema_stability: string;
    deprecation: { notice_days: number; minimum_parallel_run_days: number };
    support: { hours: string; p1_response_minutes: number; on_call: string };
    classification: { max_sensitivity: string; contains_pii: boolean; residency: string[] };
    consumer_obligations: string[];
    breach_process: string;
    effective_from: string | null;
  };
  guarantees: ContractGuarantee[];
  conformance: { dimension: string; met: number; evaluated: number }[];
  versions: { contract_version_id: string; semver: string; status: string; effective_from: string | null }[];
}

export interface LineageEdgeRow {
  type?: string;
  id?: string;
  neighbour?: string;
  relationship?: string;
  edge_type?: string;
  strength?: number | null;
  confidence: number | null;
  rationale: string;
  harvested_from?: string;
  reviewed_by?: string | null;
}

export interface LineageMeshData {
  upstream: LineageEdgeRow[];
  downstream: LineageEdgeRow[];
  mesh: LineageEdgeRow[];
  held_for_review: number;
}

export interface ConsumptionDay {
  activity_date: string;
  active_consumers: number;
  distinct_teams: number;
  query_count: number;
  denied_count: number;
  rows_scanned: number;
}

export interface ConsumptionData {
  scope: 'estate' | 'caller';
  daily: ConsumptionDay[];
  top_consumers?: { principal_id: string; queries: number }[];
}

export interface ValueAssumptionRow {
  text: string;
  value: number | null;
  unit: string;
  sample_size: number | null;
  source: string;
  dated: string;
}

export interface ValueMeasurementRow {
  period_start: string;
  period_end: string;
  answered_questions: number;
  acceptance_rate: number | null;
  deflected_hours: number | null;
  deflected_value_usd: number | null;
  total_cost_usd: number | null;
  net_value_usd: number | null;
  value_ratio: number | null;
  rubric_version_id: string;
  snapshot_ref: string;
  computed_at: string | null;
}

export interface ValueData {
  case: {
    value_case_id: string;
    business_outcome: string;
    baseline_method: string;
    baseline_captured: string;
    benefit_model: string;
    attribution_confidence: string;
    rubric_version_id: string;
    last_reviewed: string;
    review_due: string;
  };
  assumptions: ValueAssumptionRow[];
  measurements: ValueMeasurementRow[];
}

export interface ProductDetail {
  card: ProductCard;
  tabs: {
    overview: Tab<OverviewData>;
    schema: Tab<{ columns: SchemaColumn[]; column_count: number }>;
    quality: Tab<QualityData>;
    contract: Tab<ContractData>;
    endpoints: Tab<{ endpoints: EndpointRow[] }>;
    lineage_mesh: Tab<LineageMeshData>;
    consumption: Tab<ConsumptionData>;
    value: Tab<ValueData>;
  };
}

export interface SchemaColumn {
  name: string;
  business_name: string;
  data_type: string;
  nullable: boolean;
  classification: string[];
  sensitivity: string;
  description: string;
  masked_for_caller: boolean;
  masking_policy: string | null;
}

export interface EndpointRow {
  surface: string;
  uri: string;
  auth_mode: string;
  required_scope: string;
  row_limit: number | null;
  documentation_ref: string;
  granted: boolean;
}

export interface AgentCard {
  agent_id: string;
  name: string;
  capability_statement: string;
  industry: string;
  domain: string;
  autonomy_level: string;
  certification: string;
  status: string;
  version: string;
  out_of_scope: string[];
  personas: string[];
  owner: { party_id: string; name: string | null; on_call: string | null };
  coverage: { kpis: number; data_products: number };
  demo: { validated_exchanges: number };
  evaluation: {
    pass_rate_pct: number | null;
    groundedness_pct: number | null;
    threshold_pct: number;
    passed: boolean | null;
  };
  budgets: { p95_latency_ms: number; cost_per_answer_usd: number };
  adoption: { answers_30d: number };
  access: { granted: boolean; required_scope: string; request_access_url: string };
}

export interface CoverageRow {
  kpi_id: string;
  kpi_name: string;
  source_product_id: string;
  columns_used: string[];
  supported_grains: string[];
  supported_slices: string[];
  analysis_depth: string;
  eval_accuracy: number | null;
  eval_sample_size: number | null;
}

export interface DemoExchange {
  exchange_id: string;
  ordinal: number;
  question: string;
  kpi_class: string;
  analysis_type: string;
  expected_shape: Record<string, unknown>;
  last_validated: string | null;
}

export interface Citation {
  product_id: string;
  contract_version: string;
  columns: string[];
  as_of: string | null;
}

export interface ToolCallTrace {
  tool: string;
  arguments: Record<string, unknown>;
  rows_returned: number;
  rows_scanned: number;
  duration_ms: number;
  cost_class: string;
}

export interface AnswerBody {
  headline: string;
  narrative: string;
  visual: { type: string; spec: Record<string, unknown> };
  table: { columns: string[]; rows: (string | number | null)[][] };
}

export interface AgentAnswer {
  answer: AnswerBody;
  citations: Citation[];
  kpi_definitions: string[];
  trace: {
    runtime: string;
    tool_calls: ToolCallTrace[];
    rows_scanned: number;
    latency_ms: number;
    tokens: { in: number; out: number };
    cost_usd: number;
    cost_display: string;
  };
  confidence: number;
  confidence_display: string;
  notes: string[];
  interaction_id: string;
  grounded: boolean;
  tier: 'demo' | 'live';
  scope: {
    agent_identity: string | null;
    on_behalf_of: string | null;
    effective_scope: 'intersection' | 'direct';
  };
}

export interface PolicyEvaluation {
  path: 'auto' | 'owner' | 'owner_steward' | 'owner_privacy_security' | 'blocked';
  label: string;
  approvers: string[];
  sla_days: number;
  due_at: string | null;
  policy_version_id: string;
  blocked: boolean;
  automatic: boolean;
  reasons: string[];
  alternatives: { product_id: string; name: string; sensitivity: string; why: string }[];
  facts: {
    asset_type: string;
    asset_id: string;
    sensitivity: string;
    contains_pii: boolean;
    residency: string[];
    has_classified_columns: boolean;
    purpose_code: string;
  };
}

export interface DuplicateMatch {
  candidate_id: string;
  candidate_name: string;
  similarity: number;
  contributing_factors: Record<string, number>;
  confidence: number;
  rationale: string;
}

export interface DuplicateCheck {
  verdict: 'blocking' | 'advisory' | 'clear' | 'architect_review';
  blocking: boolean;
  matches: DuplicateMatch[];
  rubric_version_id: string;
}

export interface Grant {
  grant_id: string;
  principal_id: string;
  display_name: string | null;
  asset_type: string;
  asset_id: string;
  access_level: string;
  purpose_code: string;
  purpose_text: string;
  platform_role: string;
  oauth_scopes: string[];
  granted_at: string;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  columns: string[];
  live: boolean;
}

export interface BacklogItem {
  request_id: string;
  title: string;
  body: string;
  state: string;
  requester_party_id: string;
  submitted_at: string;
  sla_due_at: string | null;
  closed_at: string | null;
  asset_type: string | null;
  asset_id: string | null;
  votes: number;
  decline: { reason_code: string; reason_text: string } | null;
}

export interface DemandItem {
  demand_id: string;
  state: string;
  score: number | null;
  score_breakdown: Record<string, { weight: number; assessment: number; contribution: number }> | null;
  theme_id: string | null;
  decline_reason_public: string | null;
  title: string;
  body: string;
  requester_party_id: string;
  submitted_at: string;
  votes: number;
  teams: number;
}

export interface DemandTheme {
  theme_id: string;
  label: string;
  summary: string;
  distinct_team_count: number;
  escalated_at: string | null;
  confidence: number;
  rationale: string;
}

export interface MeshNode {
  id: string;
  name: string;
  domain: string;
  industry: string;
  sensitivity?: string;
  certification: string;
  tier?: string;
  quality?: number | null;
  band?: string | null;
  autonomy_level?: string;
  status?: string;
}

export interface MeshEdge {
  edge_id: string;
  source: string;
  target: string;
  edge_type: string;
  strength: number;
  confidence: number;
  factors: Record<string, { value: number; evidence: number; detail: string }>;
  rationale: string;
  reviewed_by: string | null;
}

export interface MeshTableRow {
  source: string;
  source_name: string;
  target: string;
  target_name: string;
  edge_type: string;
  strength: number;
  confidence: number;
  rationale: string;
}

export interface MeshGraph {
  mode: string;
  nodes: MeshNode[];
  edges: MeshEdge[];
  layout: Record<string, number>;
  rubric_version_id: string;
  table: MeshTableRow[];
  modes: string[];
}

export interface BlastRadius {
  source_id: string;
  products: { product_id: string; name: string; domain_code: string;
              sensitivity_tier: string; tier: string }[];
  agents: { agent_id: string; name: string; product_id: string }[];
  consumers: { asset_id: string; consumers: number }[];
  consumer_count: number;
}
