// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** The record of what was granted. Effective permission lives in the platform, not here. */
export interface EntitlementGrant {
  grantId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  requestId: string;
  principalId: string;
  assetType: 'data_product' | 'agent';
  assetId: string;
  accessLevel: 'read_metadata' | 'read_data' | 'read_data_pii' | 'agent_invoke' | 'write_back';
  purposeCode: string;
  purposeText: string;
  platformRole: string; // MKT_<PRODUCT>_<LEVEL>
  oauthScopes: string[];
  grantedAt: string;
  expiresAt: string;
  revokedAt?: string | null;
  revocationReason?: string | null;
  lastUsedAt?: string | null;
  dormantFlaggedAt?: string | null;
  renewalNotifiedAt?: string | null;
}

/** Column-level narrowing of a grant. A grant is never wider than its scope rows. */
export interface GrantScope {
  scopeId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  grantId: string;
  scopeKind: 'columns' | 'rows' | 'tools';
  expression: string;
  appliedInPlatform: boolean;
}

/** The declared purpose attached to a grant and logged with every query under it. */
export interface PurposeBinding {
  bindingId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  grantId: string;
  purposeCode: string;
  purposeText: string;
  boundAt: string;
  boundBy: string;
}

/** Why a grant ended: expiry, self-revoke, admin revoke, dormancy or drift. */
export interface Revocation {
  revocationId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  grantId: string;
  reasonCode: 'expired' | 'self_revoked' | 'admin_revoked' | 'dormant' | 'policy_change' | 'drift_reconciliation' | 'offboarded';
  reasonText: string;
  actorPartyId?: string | null;
  platformConfirmed: boolean;
  revokedAt: string;
}

/** Nightly reconciliation finding: register says one thing, platform says another. */
export interface EntitlementDrift {
  driftId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  platform: string;
  principalRef: string;
  assetRef: string;
  driftType: 'missing_in_platform' | 'extra_in_platform' | 'level_mismatch' | 'expired_but_present';
  registerState: unknown;
  platformState: unknown;
  incidentId?: string | null;
  detectedAt: string;
  resolvedAt?: string | null;
}
