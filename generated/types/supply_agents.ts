// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: ecef402a0bc2a39dabd73ab8610ad9fddd50da8a0fb4b40f95b29de13247e2ef  generated_at: 2026-09-04T04:34:16+00:00

/** Content-addressed prompt. An agent version pins the hash, never the text. */
export interface PromptArtifact {
  promptHash: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentId: string;
  label: string;
  body: string;
  createdAt: string;
}

/** A catalogued AI assistant with an owner, coverage map, scope and value case. */
export interface Agent {
  agentId: string; // AG-<IND>-<NNN>
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  name: string;
  industryCode: string;
  domainCode: string;
  ownerPartyId: string;
  machineIdentity: string; // Distinct service principal; effective access is an intersection (I12).
  onCall: string;
  escalationPath: string;
  certification: 'certified' | 'published' | 'beta' | 'deprecated';
  currentVersionId?: string | null;
  createdAt: string;
}

/** One execution of the evaluation suites against an agent bundle. */
export interface EvaluationRun {
  evalRunId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentId: string;
  agentVersionRef: string; // Set before the version row exists on a first publish; not an FK.
  suiteResults: unknown;
  passRatePct: number;
  groundednessPct: number;
  thresholdPct: number;
  passed: boolean;
  previousRunId?: string | null;
  startedAt: string;
  finishedAt: string;
}

/** An immutable bundle: model, params, prompt hash, tool bindings, eval run. */
/* invariants: I7 */
export interface AgentVersion {
  agentVersionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentId: string;
  semver: string;
  status: 'draft' | 'canary' | 'published' | 'retired';
  autonomyLevel: 'L0' | 'L1' | 'L2' | 'L3';
  capabilityStatement: string;
  businessValueBlock: string;
  outOfScope: string[]; // I7: an agent that refuses nothing has no boundary.
  personas: string[];
  analyses: string[];
  replaces: string;
  modelProvider: string;
  modelId: string;
  modelParams: unknown;
  promptHash: string;
  guardrailConfig: unknown;
  budgetP95LatencyMs: number;
  budgetCostPerAnswerUsd: number;
  evalSuites: string[]; // Suites this version declares it is evaluated by.
  evalThresholdPct: number; // The version's own declared pass threshold; the gate reads it here rather than from a manifest, so a published version carries the bar it was judged against.
  evalRunId?: string | null;
  canaryTrafficPct?: number | null;
  publishedAt?: string | null;
  publishedBy?: string | null;
  retiredAt?: string | null;
}

/** The agent's functional contract: which KPI, at which grains and slices, how deep. */
/* invariants: I4 */
export interface AgentKpiCoverage {
  coverageId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentVersionId: string;
  kpiId: string; // I4: coverage cannot cite a KPI that does not exist.
  sourceProductId: string;
  columnsUsed: string[];
  supportedGrains: string[];
  supportedSlices: string[];
  analysisDepth: 'report' | 'compare' | 'explain' | 'rank_drivers' | 'forecast';
  evalAccuracy?: number | null;
  evalSampleSize?: number | null;
}

/** Which product columns an agent version may read. The scope half of I12. */
export interface AgentProductBinding {
  bindingId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentVersionId: string;
  productId: string;
  columnsAllowed: string[];
  accessLevel: 'read' | 'read_pii';
  contractVersionPinned: string;
}

/** A tool the agent may call, with its scope, row limit and cost class. */
export interface AgentToolBinding {
  toolBindingId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentVersionId: string;
  toolName: string;
  endpointUri: string;
  requiredScope: string;
  costClass: 'trivial' | 'small' | 'medium' | 'large';
  rowLimit?: number | null;
}

/** A curated question with a golden answer. Five are required to publish (I3). */
/* invariants: I3 */
export interface DemoExchange {
  exchangeId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentVersionId: string;
  ordinal: number;
  question: string;
  kpiClass: string;
  analysisType: string;
  expectedShape: unknown; // headline, visual, table_columns, must_cite[]
  dataTier: 'demo' | 'live';
  maxLatencyMs: number;
  goldenAnswerRef: string;
  tolerancePct: number;
  lastValidated?: string | null;
  validationState: 'passing' | 'stale' | 'failing';
}

/** One case in an evaluation suite, including cases harvested from rejections. */
export interface EvaluationCase {
  caseId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentId: string;
  suite: 'golden_accuracy' | 'groundedness' | 'boundary_refusal' | 'adversarial' | 'entitlement' | 'compositional_exposure' | 'consistency' | 'cost_latency';
  question: string;
  personaRef?: string | null;
  expectedBehaviour: string;
  expectedPayload: unknown;
  blocking: boolean;
  origin: 'authored' | 'feedback' | 'incident' | 'regression';
  createdAt: string;
}
