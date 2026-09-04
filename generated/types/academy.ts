// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** A learning unit, optionally bound to an asset so it can be offered in context. */
export interface AcademyModule {
  moduleId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  title: string;
  summary: string;
  bodyRef: string;
  estimatedMinutes: number;
  assetType?: 'data_product' | 'agent' | null;
  assetId?: string | null;
  sandboxTier: 'demo' | 'none';
  sortOrder: number;
}

/** An ordered set of modules for a persona, ending in a certification. */
export interface LearningPath {
  pathId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  title: string;
  persona: string;
  summary: string;
  moduleIds: string[];
  certificationCode?: string | null;
}

/** A party's progress through a path. */
export interface Enrollment {
  enrollmentId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  pathId: string;
  partyId: string;
  state: 'enrolled' | 'in_progress' | 'completed' | 'lapsed';
  completedModuleIds: string[];
  enrolledAt: string;
  completedAt?: string | null;
}

/** One assessment attempt. The pass mark is a rubric value, not a constant. */
export interface AssessmentResult {
  resultId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  enrollmentId: string;
  moduleId: string;
  scorePct: number;
  passed: boolean;
  rubricVersionId: string;
  attemptedAt: string;
}

/** A held certification, with expiry so competence claims stay current. */
export interface Certification {
  certificationId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  code: string;
  partyId: string;
  pathId: string;
  issuedAt: string;
  expiresAt: string;
  revokedAt?: string | null;
}
