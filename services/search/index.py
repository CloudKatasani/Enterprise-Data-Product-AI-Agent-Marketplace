"""Building the search index.

Two halves, kept in step by the same pass:

* ``asset_search_document`` — the lexical side. The exact name is stored
  separately from the body and weighted 'A' in the tsvector, because a consumer
  who types a product's name must get that product (M4 acceptance).
* ``asset_embedding`` — the semantic side, one vector per asset per model. The
  model id is part of the key, so switching embedders is an additive change and
  the old vectors stay readable until they are dropped.

The indexed text is deliberately the *governed* text: purpose, limitations,
certified KPIs and their synonyms. Marketing copy is not indexed because there
is none, which is why searching here behaves like searching a contract.
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.search.embedding import active_embedder


def _document_for_product(row: dict[str, Any]) -> str:
    parts = [
        row["name"],
        row["purpose"],
        row["known_limitations"],
        row["grain"],
        row["industry_code"].replace("_", " "),
        row["domain_code"].replace("_", " "),
        row["archetype_code"].replace("_", " "),
        " ".join(row["kpi_names"] or []),
        " ".join(row["kpi_synonyms"] or []),
        " ".join(row["entity_columns"] or []),
    ]
    return "\n".join(part for part in parts if part)


PRODUCT_SOURCE = """
SELECT p.product_id, p.name, p.purpose, p.known_limitations, p.grain,
       p.industry_code, p.domain_code, p.archetype_code,
       array_remove(array_agg(DISTINCT k.kpi_name), NULL) AS kpi_names,
       array_remove(array_agg(DISTINCT s.term), NULL) AS kpi_synonyms,
       array_remove(array_agg(DISTINCT c.business_name), NULL) AS entity_columns
FROM data_product p
LEFT JOIN kpi_definition k ON k.source_of_record = p.product_id
LEFT JOIN kpi_synonym s ON s.kpi_id = k.kpi_id
LEFT JOIN data_product_column c ON c.product_id = p.product_id
WHERE p.tenant_id = %s
GROUP BY p.product_id
ORDER BY p.product_id
"""

KPI_SOURCE = """
SELECT k.kpi_id, k.kpi_name, k.business_definition, k.unit, k.domain_code,
       array_remove(array_agg(DISTINCT s.term), NULL) AS synonyms
FROM kpi_definition k
LEFT JOIN kpi_synonym s ON s.kpi_id = k.kpi_id
WHERE k.tenant_id = %s
GROUP BY k.kpi_id
ORDER BY k.kpi_id
"""

AGENT_SOURCE = """
SELECT a.agent_id, a.name, a.industry_code, a.domain_code,
       v.capability_statement, v.business_value_block, v.out_of_scope,
       array_remove(array_agg(DISTINCT k.kpi_name), NULL) AS kpi_names
FROM agent a
JOIN agent_version v ON v.agent_version_id = a.current_version_id
LEFT JOIN agent_kpi_coverage cov ON cov.agent_version_id = v.agent_version_id
LEFT JOIN kpi_definition k ON k.kpi_id = cov.kpi_id
WHERE a.tenant_id = %s
GROUP BY a.agent_id, v.agent_version_id
ORDER BY a.agent_id
"""

UPSERT_DOCUMENT = """
INSERT INTO asset_search_document (
  document_id, tenant_id, asset_type, asset_id, exact_name, body, search_vector
) VALUES (%s, %s, %s, %s, %s, %s, ''::tsvector)
ON CONFLICT (asset_type, asset_id) DO UPDATE SET
  exact_name = EXCLUDED.exact_name, body = EXCLUDED.body
"""

UPSERT_EMBEDDING = """
INSERT INTO asset_embedding (
  embedding_id, tenant_id, asset_type, asset_id, model_id, source_text, embedding
) VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (asset_type, asset_id, model_id) DO UPDATE SET
  source_text = EXCLUDED.source_text, embedding = EXCLUDED.embedding,
  computed_at = now()
"""


def _index_one(
    cursor: psycopg.Cursor[Any], tenant: str, asset_type: str, asset_id: str,
    exact_name: str, body: str,
) -> None:
    embedder = active_embedder()
    cursor.execute(
        UPSERT_DOCUMENT,
        (f"SD-{asset_type}-{asset_id}", tenant, asset_type, asset_id, exact_name, body),
    )
    cursor.execute(
        UPSERT_EMBEDDING,
        (
            f"EMB-{asset_type}-{asset_id}-{embedder.model_id}", tenant, asset_type, asset_id,
            embedder.model_id, body, str(embedder.embed(f"{exact_name}\n{body}")),
        ),
    )


def reindex(connection: psycopg.Connection[Any], tenant: str) -> dict[str, int]:
    """Rebuild the index for every asset. Idempotent."""
    counts = {"data_product": 0, "kpi": 0, "agent": 0}

    with connection.cursor() as cursor:
        cursor.execute(PRODUCT_SOURCE, (tenant,))
        for row in [dict(r) for r in cursor.fetchall()]:
            _index_one(
                cursor, tenant, "data_product", row["product_id"], row["name"],
                _document_for_product(row),
            )
            counts["data_product"] += 1

        cursor.execute(KPI_SOURCE, (tenant,))
        for row in [dict(r) for r in cursor.fetchall()]:
            body = "\n".join(
                [row["business_definition"], row["unit"], row["domain_code"].replace("_", " "),
                 " ".join(row["synonyms"] or [])]
            )
            _index_one(cursor, tenant, "kpi", row["kpi_id"], row["kpi_name"], body)
            counts["kpi"] += 1

        cursor.execute(AGENT_SOURCE, (tenant,))
        for row in [dict(r) for r in cursor.fetchall()]:
            body = "\n".join(
                [row["capability_statement"], row["business_value_block"],
                 " ".join(row["out_of_scope"] or []),
                 " ".join(row["kpi_names"] or []),
                 row["industry_code"].replace("_", " "),
                 row["domain_code"].replace("_", " ")]
            )
            _index_one(cursor, tenant, "agent", row["agent_id"], row["name"], body)
            counts["agent"] += 1

    return counts
