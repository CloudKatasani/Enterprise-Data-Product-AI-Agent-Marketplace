// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** A named body of versioned configuration: quality, ranking, mesh, demand, value, finops. */
export interface Rubric {
  rubricId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  code: string;
  description: string;
  currentVersionId?: string | null;
}

/** An immutable rubric version. Every score records the id it was computed under. */
export interface RubricVersion {
  rubricVersionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  rubricId: string;
  semver: string;
  sourceHash: string; // sha256 of the YAML that produced this version.
  payload: unknown; // The whole rubric document, so a score can be replayed exactly.
  effectiveFrom: string;
  supersededAt?: string | null;
  createdBy: string;
}

/** One addressable value inside a rubric version: a weight, threshold, band or target. */
export interface RubricCriterion {
  criterionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  rubricVersionId: string;
  path: string; // Dotted path into the rubric document, e.g. dimensions.freshness.weight
  kind: 'weight' | 'threshold' | 'band' | 'multiplier' | 'target' | 'reference' | 'formula' | 'flag' | 'list';
  numericValue?: number | null;
  textValue?: string | null;
  scope?: string | null; // Optional qualifier, e.g. the archetype an override applies to.
}

/** An access, residency, licence or separation-of-duties policy. */
export interface Policy {
  policyId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  code: string;
  category: 'access' | 'residency' | 'licence' | 'sod' | 'retention' | 'purpose';
  description: string;
  currentVersionId?: string | null;
}

/** An immutable policy version. Every decision records the version in force. */
export interface PolicyVersion {
  policyVersionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  policyId: string;
  semver: string;
  rules: unknown;
  effectiveFrom: string;
  supersededAt?: string | null;
}

/** A typed flag. Release and experiment flags carry a max age the lint enforces. */
export interface FeatureFlag {
  flagId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  code: string;
  flagType: 'release' | 'experiment' | 'operational';
  enabled: boolean;
  description: string;
  ownerPartyId: string;
  createdAt: string;
  expiresAt?: string | null;
}
