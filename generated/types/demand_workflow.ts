// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** One governed request: access, enhancement or new supply. */
export interface Request {
  requestId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  requestType: 'access' | 'enhancement' | 'supply';
  state: string;
  requesterPartyId: string;
  title: string;
  body: string;
  purposeCode?: string | null;
  purposeText?: string | null;
  policyPath?: string | null; // Approval path resolved before submission: auto, owner, owner_steward, ...
  policyVersionId?: string | null;
  slaHours?: number | null;
  slaDueAt?: string | null;
  escalatedAt?: string | null;
  submittedAt?: string | null;
  closedAt?: string | null;
  createdAt: string;
}

/** One asset and access level within a request; a request may be partially approved. */
export interface RequestItem {
  requestItemId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  requestId: string;
  assetType: 'data_product' | 'agent';
  assetId: string;
  accessLevel: 'read_metadata' | 'read_data' | 'read_data_pii' | 'agent_invoke' | 'write_back';
  columnsRequested: string[];
  outcome?: 'approved' | 'declined' | 'withdrawn' | null;
  outcomeReason?: string | null;
}

/** One required approval in the resolved path, with its own SLA clock. */
export interface ApprovalStep {
  stepId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  requestId: string;
  ordinal: number;
  approverRole: string;
  approverPartyId?: string | null;
  state: 'pending' | 'approved' | 'declined' | 'skipped' | 'escalated';
  dueAt?: string | null;
  actedAt?: string | null;
}

/** Actor, timestamp, decision, reason and the policy version in force. */
export interface Decision {
  decisionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  requestId: string;
  stepId?: string | null;
  actorPartyId: string;
  outcome: 'approve' | 'decline' | 'partial' | 'block' | 'withdraw';
  reasonCode: string;
  reasonText: string;
  policyVersionId?: string | null;
  decidedAt: string;
}

/** An enhancement to an existing asset. Declines are public and reasoned. */
export interface Enhancement {
  enhancementId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  requestId: string;
  assetType: 'data_product' | 'agent';
  assetId: string;
  state: 'submitted' | 'triaged' | 'assessed' | 'accepted' | 'declined' | 'merged' | 'scheduled' | 'in_progress' | 'delivered' | 'verified' | 'auto_closed';
  declineReasonCode?: 'out_of_scope' | 'source_unavailable' | 'cost_prohibitive' | 'duplicate' | 'superseded' | 'security_constraint' | null;
  declineReasonText?: string | null;
  mergedInto?: string | null;
  triageDueAt?: string | null;
  deliveredAt?: string | null;
  verifyDueAt?: string | null;
}

/** A cluster of demand items. Five distinct requesting teams auto-escalates it. */
export interface DemandTheme {
  themeId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  label: string;
  summary: string;
  distinctTeamCount: number;
  escalatedAt?: string | null;
  confidence: number;
  rationale: string;
}

/** A new-supply request on the public board, scored against the demand rubric. */
export interface DemandItem {
  demandId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  requestId: string;
  themeId?: string | null;
  state: 'submitted' | 'duplicate_review' | 'triaged' | 'scored' | 'roadmapped' | 'in_build' | 'delivered' | 'declined';
  score?: number | null;
  scoreBreakdown?: unknown | null;
  rubricVersionId?: string | null;
  declineReasonPublic?: string | null;
  draftManifest?: unknown | null; // Generated on acceptance with confidence and rationale per field.
}

/** A candidate duplicate found at submission, with its contributing factors. */
export interface DuplicateMatch {
  matchId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  demandId: string;
  candidateType: 'data_product' | 'agent' | 'demand';
  candidateId: string;
  similarity: number;
  contributingFactors: unknown;
  confidence: number;
  rationale: string;
  disposition: 'blocking' | 'advisory' | 'informational' | 'architect_review';
  reviewedBy?: string | null;
}

/** A vote. It requires a one-line use case: a vote without context is not counted. */
export interface DemandVote {
  voteId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  demandId: string;
  voterPartyId: string;
  useCase: string;
  orgUnitId?: string | null;
  votedAt: string;
}

/** Durable workflow state. An approval survives a process restart (D-003). */
export interface WorkflowInstance {
  instanceId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  workflowType: 'access' | 'enhancement' | 'demand' | 'provisioning' | 'revocation' | 'canary';
  subjectId: string;
  state: string;
  payload: unknown;
  runAfter: string;
  attempts: number;
  lastError?: string | null;
  completedAt?: string | null;
  createdAt: string;
}

/** Append-only transition log for a workflow instance; replayable. */
export interface WorkflowEvent {
  eventId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  instanceId: string;
  fromState?: string | null;
  toState: string;
  actor: string;
  detail: unknown;
  occurredAt: string;
}
