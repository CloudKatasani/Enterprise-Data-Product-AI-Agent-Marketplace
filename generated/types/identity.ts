// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 794b91c55a4fc4ca1b4fa01ed63984ce451806401ca67a7ebf241fdba98389a6  generated_at: 2026-09-04T05:30:32+00:00

/** Organisational tree used for approval routing and adoption breadth. */
export interface OrgUnit {
  orgUnitId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  name: string;
  parentOrgUnitId?: string | null;
  costCentre?: string | null;
  region?: string | null; // Where this unit's people sit. Residency policy compares a requester's region against the product's permitted regions, so a cross-border request is a fact rather than a judgement.
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
