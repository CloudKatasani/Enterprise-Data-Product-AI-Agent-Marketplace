// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** The quantified case for an asset, with its baseline and attribution confidence. */
export interface ValueCase {
  valueCaseId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent';
  assetId: string;
  businessOutcome: string;
  baselineMethod: string;
  baselineCaptured: string;
  benefitModel: string;
  attributionConfidence: 'high' | 'medium' | 'low';
  rubricVersionId: string;
  lastReviewed: string;
  reviewerPartyId: string;
  reviewDue: string;
}

/** A named assumption with its value, sample size and date. Displayed beside any figure. */
export interface ValueAssumption {
  assumptionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  valueCaseId: string;
  text: string;
  numericValue: number;
  unit: string;
  sampleSize?: number | null;
  source: string;
  dated: string;
}

/** A realised measurement period: deflected hours, value, cost and the ratio. */
export interface ValueMeasurement {
  measurementId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  valueCaseId: string;
  periodStart: string;
  periodEnd: string;
  answeredQuestions: number;
  acceptanceRate: number;
  deflectedHours: number;
  deflectedValueUsd: number;
  totalCostUsd: number;
  netValueUsd: number;
  valueRatio: number;
  rubricVersionId: string;
  snapshotRef: string; // Board pack and dashboard read the same snapshot so they cannot disagree.
  computedAt: string;
}
