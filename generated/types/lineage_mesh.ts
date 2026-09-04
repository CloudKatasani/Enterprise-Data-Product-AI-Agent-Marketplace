// AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 685ed1356f294c76a54e17687ddc51aa3cbf75c96874661d5a7a9e137f14e039  generated_at: 2026-09-04T02:51:42+00:00

/** Harvested upstream/downstream relationship. Blast radius walks this. */
export interface LineageEdge {
  lineageId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  upstreamType: 'source_system' | 'data_product';
  upstreamId: string;
  downstreamType: 'data_product' | 'agent';
  downstreamId: string;
  relationship: 'derives_from' | 'reads' | 'joins' | 'aggregates';
  harvestedFrom: string;
  confidence: number;
  rationale: string;
  harvestedAt: string;
}

/** A computed relationship between two data products (I6). */
/* invariants: I6 */
export interface MeshEdgeData {
  edgeId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  productA: string;
  productB: string;
  edgeType: 'shared_source' | 'dependency' | 'shared_entity' | 'shared_kpi' | 'semantic' | 'co_consumption';
  strength: number;
  factors: unknown;
  confidence: number;
  rationale: string; // I6: an edge nobody can explain is not rendered.
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  computedAt: string;
}

/** A computed relationship between two agents (I6). */
/* invariants: I6 */
export interface MeshEdgeAgent {
  edgeId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  agentA: string;
  agentB: string;
  edgeType: 'shared_data_product' | 'shared_kpi' | 'semantic' | 'same_domain' | 'co_usage' | 'handoff';
  strength: number;
  factors: unknown;
  confidence: number;
  rationale: string;
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  computedAt: string;
}

/** Semantic vector for hybrid search and semantic mesh similarity. */
export interface AssetEmbedding {
  embeddingId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent' | 'kpi' | 'glossary_term' | 'demand';
  assetId: string;
  modelId: string;
  sourceText: string;
  embedding: number[];
  computedAt: string;
}

/** Lexical side of hybrid search: a maintained tsvector plus the exact-name key. */
export interface AssetSearchDocument {
  documentId: string;
  tenantId: string; // Tenant that owns this row; carried into every RLS policy.
  assetType: 'data_product' | 'agent' | 'kpi' | 'glossary_term';
  assetId: string;
  exactName: string;
  body: string;
  searchVector: string;
  updatedAt: string;
}
