// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** A metadata-level consumption event. No row-level customer data (rule 5). */
export interface UsageEvent {
  eventId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent';
  assetId: string;
  principalId?: string | null;
  surface: string;
  eventName: string; // From the typed event taxonomy; a new name must be added there first.
  purposeCode?: string | null;
  rowsReturned?: number | null;
  columnsReturned?: string[] | null;
  outcome: 'ok' | 'denied' | 'error' | 'throttled';
  occurredAt: string;
}

/** Pre-aggregated adoption. Card counts and ranking read this, not raw events. */
export interface UsageDailyAgg {
  aggId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent';
  assetId: string;
  activityDate: string;
  activeConsumers: number;
  distinctTeams: number;
  queryCount: number;
  deniedCount: number;
  rowsScanned: number;
}

/** One question answered, with its trace. The evidence behind value and FinOps. */
export interface AgentInteraction {
  interactionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentVersionId: string;
  principalId?: string | null;
  sessionId: string;
  tier: 'demo' | 'live';
  question: string;
  questionClass: string;
  purposeCode?: string | null;
  outcome: 'answered' | 'out_of_scope' | 'ungrounded' | 'denied' | 'error';
  grounded: boolean;
  confidence?: number | null;
  citations: unknown;
  kpiDefinitions: string[];
  toolCalls: unknown;
  rowsScanned?: number | null;
  latencyMs: number;
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
  occurredAt: string;
}

/** Acceptance or rejection with a reason; rejections become evaluation cases. */
export interface AnswerFeedback {
  feedbackId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  interactionId: string;
  partyId: string;
  accepted: boolean;
  reasonCode: 'correct' | 'useful_partial' | 'wrong_number' | 'wrong_scope' | 'missing_context' | 'stale_data' | 'unclear' | 'other';
  reasonText?: string | null;
  promotedCaseId?: string | null;
  submittedAt: string;
}

/** Attributed cost per asset per day: inference, retrieval, query, platform, stewardship. */
export interface CostAllocation {
  allocationId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent';
  assetId: string;
  costDate: string;
  inferenceUsd: number;
  retrievalUsd: number;
  queryUsd: number;
  platformUsd: number;
  stewardshipUsd: number;
  tier: 'demo' | 'live';
  source: string;
}
