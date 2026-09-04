// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** A deployment boundary. Every tenant-scoped row names one. */
export interface Tenant {
  tenantId: string;
  name: string;
  deploymentMode: 'multi_tenant' | 'single_tenant';
  residencyRegions: string[];
  createdAt: string;
}

/** Industry taxonomy. Seeded from manifests/taxonomies/industry.yaml. */
export interface Industry {
  code: string;
  label: string;
  description: string;
  sortOrder: number;
}

/** Business domain taxonomy (customer, network, risk, supply chain, ...). */
export interface BusinessDomain {
  code: string;
  label: string;
  description: string;
  sortOrder: number;
}

/** Product archetype; drives the quality rubric's archetype overrides. */
export interface ProductArchetype {
  code: string;
  label: string;
  description: string;
  sortOrder: number;
}

/** Sensitivity ladder. rank_order is what derive_sensitivity maximises (I5). */
export interface SensitivityTier {
  code: string;
  label: string;
  rankOrder: number;
  requiresPurpose: boolean;
  description: string;
}

/** Permitted purposes a grant may be bound to. Purpose is mandatory above Internal. */
export interface PurposeCategory {
  code: string;
  label: string;
  description: string;
  requiresFreeText: boolean;
  sortOrder: number;
}

/** Upstream system of record. Shared sources are what the data mesh links on. */
export interface SourceSystem {
  sourceId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  name: string;
  platform: string;
  ownerTeam: string;
  criticality: 'tier1' | 'tier2' | 'tier3';
  description: string;
}
