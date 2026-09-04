// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** A business measure with exactly one authoritative definition (I1). */
/* invariants: I1 */
export interface KpiDefinition {
  kpiId: string; // KPI-<DOMAIN>-<NNN>
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  kpiName: string;
  status: 'draft' | 'certified' | 'deprecated' | 'superseded';
  businessDefinition: string;
  numeratorExpr?: string | null;
  denominatorExpr?: string | null;
  expression?: string | null;
  grainsSupported: string[];
  slicesSupported: string[];
  inclusions: string[];
  exclusions: string[];
  unit: string;
  direction?: string | null;
  target?: number | null;
  domainCode: string;
  sourceOfRecord?: string | null;
  stewardPartyId: string;
  forumApprovedAt?: string | null;
  supersededBy?: string | null;
  lastReviewed: string;
  reviewMonths: number;
}

/** Immutable history of a KPI definition; agents pin the version they answered under. */
export interface KpiDefinitionVersion {
  kpiVersionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  kpiId: string;
  semver: string;
  businessDefinition: string;
  expression?: string | null;
  changeReason: string;
  approvedBy: string;
  effectiveFrom: string;
}

/** Alternate names a consumer might search for. Feeds lexical search recall. */
export interface KpiSynonym {
  synonymId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  kpiId: string;
  term: string;
  source: 'steward' | 'glossary' | 'search_log' | 'bi_tool';
}

/** Business vocabulary. Distinct from KPIs: a term need not be measurable. */
export interface GlossaryTerm {
  termId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  term: string;
  definition: string;
  domainCode: string;
  stewardPartyId: string;
  relatedKpiIds: string[];
  status: 'draft' | 'approved' | 'deprecated';
}
