// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** A governed, contracted, owned dataset published for consumption. */
/* invariants: I5, I7 */
export interface DataProduct {
  productId: string; // DP-<IND>-<NNN>
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  name: string;
  purpose: string;
  industryCode: string;
  domainCode: string;
  archetypeCode: string;
  sensitivityTier: string; // I5: DERIVED from columns by trigger; never written directly.
  certification: 'certified' | 'published' | 'beta' | 'deprecated';
  ownerPartyId: string;
  currentVersion: string;
  grain: string;
  historyMonths: number;
  knownLimitations: string; // I7: a limitation section that says 'none' is not a limitation section.
  tier: 'tier1' | 'tier2' | 'tier3'; // Tier weighting for estate scoring (15.1).
  createdAt: string;
  updatedAt: string;
}

/** A published version of a product. Publication is snapshotted, never mutated. */
export interface DataProductVersion {
  productVersionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  productId: string;
  semver: string;
  status: 'draft' | 'published' | 'deprecated' | 'retired';
  changeSummary: string;
  schemaStability: 'additive_only' | 'breaking_allowed' | 'frozen';
  publishedAt?: string | null;
  publishedBy?: string | null;
  deprecatedAt?: string | null;
}

/** Column-level metadata and classification. Sensitivity derives from here (I5). */
export interface DataProductColumn {
  columnId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  productId: string;
  name: string;
  businessName: string;
  dataType: string;
  nullable: boolean;
  classification: string[]; // pii, phi, pci, identifier, financial, ...
  sensitivityCode: string;
  description: string;
  maskingPolicy?: string | null;
  ordinal: number;
}

/** The enforceable promise a product makes. Conformance is measured against it. */
export interface DataContractVersion {
  contractVersionId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  productId: string;
  semver: string;
  status: 'draft' | 'active' | 'superseded';
  schemaStability: string;
  deprecationNoticeDays: number;
  minimumParallelRunDays: number;
  supportHours: string;
  p1ResponseMinutes: number;
  onCall: string;
  maxSensitivity: string;
  containsPii: boolean;
  residency: string[];
  consumerObligations: string[];
  breachProcess: string;
  effectiveFrom: string;
}

/** One measurable guarantee of a contract: freshness, availability, completeness, accuracy. */
export interface ContractGuarantee {
  guaranteeId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  contractVersionId: string;
  dimension: 'freshness' | 'availability' | 'completeness' | 'accuracy';
  targetText: string;
  targetNumeric?: number | null;
  unit: string;
  measurementWindow: string;
  measuredAtGrain: string;
  referenceSystem?: string | null;
}

/** A consumption surface: SQL, REST, MCP, stream or share. */
export interface Endpoint {
  endpointId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  productId: string;
  surface: 'sql' | 'rest' | 'mcp' | 'stream' | 'share';
  uri: string;
  authMode: string;
  requiredScope: string;
  rowLimit?: number | null;
  documentationRef: string;
}
