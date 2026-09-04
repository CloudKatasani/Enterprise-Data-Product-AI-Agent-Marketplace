// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** Organisational tree used for approval routing and adoption breadth. */
export interface OrgUnit {
  orgUnitId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  name: string;
  parentOrgUnitId?: string | null;
  costCentre?: string | null;
}

/** A person, team, service principal or agent identity. Agents hold their own. */
export interface Party {
  partyId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  partyType: 'person' | 'team' | 'service' | 'agent';
  displayName: string;
  email?: string | null;
  orgUnitId?: string | null;
  externalSubject?: string | null; // OIDC subject or SCIM external id; never a password.
  mfaEnforced: boolean;
  active: boolean;
  createdAt: string;
}

/** Marketplace role held by a party. MFA is enforced for the privileged four. */
export interface RoleAssignment {
  assignmentId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  partyId: string;
  roleCode: 'consumer' | 'owner' | 'steward' | 'architect' | 'security' | 'privacy' | 'administrator';
  scopeType: 'tenant' | 'domain' | 'product' | 'agent';
  scopeId?: string | null;
  grantedAt: string;
  grantedBy: string;
}
