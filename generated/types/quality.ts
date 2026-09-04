// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** An executable expectation declared by a product manifest. */
export interface QualityRule {
  ruleId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  productId: string;
  dimension: 'completeness' | 'accuracy' | 'freshness' | 'consistency' | 'validity' | 'uniqueness';
  ruleType: string;
  targetColumns: string[];
  thresholdPct?: number | null;
  targetText?: string | null;
  toleranceMinutes?: number | null;
  severity: 'critical' | 'high' | 'medium' | 'low';
  enabled: boolean;
}

/** One evaluation of one rule. The evidence a composite is computed from. */
export interface QualityResult {
  resultId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  ruleId: string;
  productId: string;
  observedPct?: number | null;
  observedText?: string | null;
  passed: boolean;
  rowsEvaluated?: number | null;
  source: 'dmf' | 'soda' | 'montecarlo' | 'internal' | 'manual';
  evaluatedAt: string;
}

/** An immutable composite score, replayable from its evidence and rubric version. */
/* invariants: I2 */
export interface QualityScoreSnapshot {
  snapshotId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  productId: string;
  rubricVersionId: string; // I2: a score without the rubric it was computed under is meaningless.
  composite: number;
  completeness?: number | null;
  accuracy?: number | null;
  freshness?: number | null;
  consistency?: number | null;
  validity?: number | null;
  uniqueness?: number | null;
  band: string; // Resolved from rubric bands, never from code.
  blockerApplied?: string | null; // Which hard blocker capped the composite, if any.
  evidenceRef: unknown; // rule_ids + result_ids that produced this score.
  computedAt: string;
}

/** A detected breach. Severity is computed from blast radius, never chosen. */
export interface Incident {
  incidentId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent' | 'source_system' | 'kpi';
  assetId: string;
  signal: string;
  guaranteeBreached?: string | null;
  severity: 'sev1' | 'sev2' | 'sev3' | 'sev4';
  severityInputs: unknown; // consumer count x sensitivity rank x guarantee, so severity is auditable.
  status: 'open' | 'mitigating' | 'resolved' | 'closed';
  detectedAt: string;
  notifiedAt?: string | null;
  resolvedAt?: string | null;
  rootCause?: string | null;
  ownerContext?: string | null; // Owners may add context; they cannot suppress consumer notification.
}

/** Who an incident reached. Drives banners on every affected listing. */
export interface IncidentImpact {
  impactId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  incidentId: string;
  affectedAssetType: 'data_product' | 'agent';
  affectedAssetId: string;
  consumerCount: number;
  notifiedAt?: string | null;
  bannerActive: boolean;
}
