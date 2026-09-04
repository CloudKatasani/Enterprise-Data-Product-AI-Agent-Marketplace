-- AUTO-GENERATED FROM scripts/generators/canonical_model.py BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: fbb3ffd6721e1ee7d8fd5fb08735ed416f5d4af8855002b3a319a5670d827d46  generated_at: 2026-09-04T02:21:56+00:00

-- lineage, both meshes and the search indexes

-- lineage_edge: Harvested upstream/downstream relationship. Blast radius walks this.
CREATE TABLE lineage_edge (
  lineage_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  upstream_type TEXT NOT NULL CHECK (upstream_type IN ('source_system','data_product')),
  upstream_id TEXT NOT NULL,
  downstream_type TEXT NOT NULL CHECK (downstream_type IN ('data_product','agent')),
  downstream_id TEXT NOT NULL,
  relationship TEXT NOT NULL CHECK (relationship IN ('derives_from','reads','joins','aggregates')),
  harvested_from TEXT NOT NULL,
  confidence NUMERIC(4,3) NOT NULL,
  rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 10),
  harvested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (upstream_type, upstream_id, downstream_type, downstream_id, relationship)
);
CREATE INDEX lineage_upstream_idx ON lineage_edge (upstream_type, upstream_id);
CREATE INDEX lineage_downstream_idx ON lineage_edge (downstream_type, downstream_id);
ALTER TABLE lineage_edge ENABLE ROW LEVEL SECURITY;
ALTER TABLE lineage_edge FORCE ROW LEVEL SECURITY;
CREATE POLICY lineage_edge_tenant_isolation ON lineage_edge
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON lineage_edge TO app_role;
GRANT UPDATE, DELETE ON lineage_edge TO app_role;

-- mesh_edge_data: A computed relationship between two data products (I6).
-- invariants: I6
CREATE TABLE mesh_edge_data (
  edge_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  product_a TEXT NOT NULL REFERENCES data_product(product_id),
  product_b TEXT NOT NULL REFERENCES data_product(product_id),
  edge_type TEXT NOT NULL CHECK (edge_type IN ('shared_source','dependency','shared_entity','shared_kpi','semantic','co_consumption')),
  strength NUMERIC(4,3) NOT NULL CHECK (strength BETWEEN 0 AND 1),
  factors JSONB NOT NULL,
  confidence NUMERIC(4,3) NOT NULL,
  rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 10),  -- I6: an edge nobody can explain is not rendered.
  reviewed_by TEXT REFERENCES party(party_id),
  reviewed_at TIMESTAMPTZ,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (product_a < product_b),
  CHECK (confidence >= 0.80 OR reviewed_by IS NOT NULL),
  UNIQUE (product_a, product_b, edge_type)
);
CREATE INDEX mesh_data_a_idx ON mesh_edge_data (product_a);
CREATE INDEX mesh_data_b_idx ON mesh_edge_data (product_b);
ALTER TABLE mesh_edge_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE mesh_edge_data FORCE ROW LEVEL SECURITY;
CREATE POLICY mesh_edge_data_tenant_isolation ON mesh_edge_data
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON mesh_edge_data TO app_role;
GRANT UPDATE, DELETE ON mesh_edge_data TO app_role;

-- mesh_edge_agent: A computed relationship between two agents (I6).
-- invariants: I6
CREATE TABLE mesh_edge_agent (
  edge_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  agent_a TEXT NOT NULL REFERENCES agent(agent_id),
  agent_b TEXT NOT NULL REFERENCES agent(agent_id),
  edge_type TEXT NOT NULL CHECK (edge_type IN ('shared_data_product','shared_kpi','semantic','same_domain','co_usage','handoff')),
  strength NUMERIC(4,3) NOT NULL CHECK (strength BETWEEN 0 AND 1),
  factors JSONB NOT NULL,
  confidence NUMERIC(4,3) NOT NULL,
  rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 10),
  reviewed_by TEXT REFERENCES party(party_id),
  reviewed_at TIMESTAMPTZ,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (agent_a < agent_b),
  CHECK (confidence >= 0.80 OR reviewed_by IS NOT NULL),
  UNIQUE (agent_a, agent_b, edge_type)
);
CREATE INDEX mesh_agent_a_idx ON mesh_edge_agent (agent_a);
CREATE INDEX mesh_agent_b_idx ON mesh_edge_agent (agent_b);
ALTER TABLE mesh_edge_agent ENABLE ROW LEVEL SECURITY;
ALTER TABLE mesh_edge_agent FORCE ROW LEVEL SECURITY;
CREATE POLICY mesh_edge_agent_tenant_isolation ON mesh_edge_agent
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON mesh_edge_agent TO app_role;
GRANT UPDATE, DELETE ON mesh_edge_agent TO app_role;

-- asset_embedding: Semantic vector for hybrid search and semantic mesh similarity.
CREATE TABLE asset_embedding (
  embedding_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent','kpi','glossary_term','demand')),
  asset_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  source_text TEXT NOT NULL,
  embedding vector(384) NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (asset_type, asset_id, model_id)
);
CREATE INDEX asset_embedding_hnsw_idx ON asset_embedding USING hnsw (embedding vector_cosine_ops);
ALTER TABLE asset_embedding ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_embedding FORCE ROW LEVEL SECURITY;
CREATE POLICY asset_embedding_tenant_isolation ON asset_embedding
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON asset_embedding TO app_role;
GRANT UPDATE, DELETE ON asset_embedding TO app_role;

-- asset_search_document: Lexical side of hybrid search: a maintained tsvector plus the exact-name key.
CREATE TABLE asset_search_document (
  document_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenant(tenant_id),  -- Tenant that owns this row; carried into every RLS policy.
  asset_type TEXT NOT NULL CHECK (asset_type IN ('data_product','agent','kpi','glossary_term')),
  asset_id TEXT NOT NULL,
  exact_name TEXT NOT NULL,
  body TEXT NOT NULL,
  search_vector tsvector NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (asset_type, asset_id)
);
CREATE INDEX asset_search_vector_idx ON asset_search_document USING gin (search_vector);
CREATE INDEX asset_search_name_trgm_idx ON asset_search_document USING gin (lower(exact_name) gin_trgm_ops);
ALTER TABLE asset_search_document ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_search_document FORCE ROW LEVEL SECURITY;
CREATE POLICY asset_search_document_tenant_isolation ON asset_search_document
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT ON asset_search_document TO app_role;
GRANT UPDATE, DELETE ON asset_search_document TO app_role;
