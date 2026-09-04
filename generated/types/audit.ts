// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** Immutable record of anything touching access, publication or scores. 7-year retention. */
export interface AuditEvent {
  auditId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  eventName: string;
  actorPartyId?: string | null;
  onBehalfOf?: string | null; // Delegated identity: both identities are logged (section 19).
  assetType?: string | null;
  assetId?: string | null;
  purposeCode?: string | null;
  outcome: string;
  detail: unknown;
  policyVersionId?: string | null;
  occurredAt: string;
  retainUntil: string;
}

/** The exact bundle that reached the shelf, replayable for rollback and audit. */
export interface PublicationSnapshot {
  snapshotId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent';
  assetId: string;
  versionRef: string;
  gateResults: unknown;
  bundle: unknown; // Pinned model, params, prompt hash, tool bindings, contract and KPI versions.
  publishedBy: string;
  publishedAt: string;
}
