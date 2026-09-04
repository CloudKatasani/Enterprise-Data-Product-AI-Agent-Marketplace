"""The data-product mesh (M9.1).

Five weighted signals produce an edge's strength; the edge is then filed under
whichever of six types the dominant signal names. That split matters: the
strength answers "how related?", the type answers "related how?", and a graph
that renders the first without the second is a picture nobody can act on.

    0.30 shared upstream source systems
    0.25 shared entities (the columns both products key on)
    0.20 shared certified KPIs
    0.15 semantic similarity of stated purpose
    0.10 co-consumption lift — the same people query both

A direct lineage edge overrides the classification: where one product is built
from another, "dependency" is the true relationship whatever else they have in
common, and calling it "shared_source" would hide the thing a reader most needs
to know before changing either one.

Edges below the rubric's confidence floor are returned as held rather than
written. The table will not accept them — `confidence >= 0.80 OR reviewed_by IS
NOT NULL` — and that is the right place for the rule, because a mesh that
renders guesses is worse than a sparser one that does not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric
from services.mesh import factors
from services.search import embedding

TYPE_SHARED_SOURCE = "shared_source"
TYPE_DEPENDENCY = "dependency"
TYPE_SHARED_ENTITY = "shared_entity"
TYPE_SHARED_KPI = "shared_kpi"
TYPE_SEMANTIC = "semantic"
TYPE_CO_CONSUMPTION = "co_consumption"

EDGE_TYPES = (
    TYPE_SHARED_SOURCE, TYPE_DEPENDENCY, TYPE_SHARED_ENTITY, TYPE_SHARED_KPI,
    TYPE_SEMANTIC, TYPE_CO_CONSUMPTION,
)

FACTOR_SOURCE = "source_overlap_jaccard"
FACTOR_ENTITY = "entity_overlap"
FACTOR_KPI = "kpi_overlap"
FACTOR_SEMANTIC = "semantic_similarity"
FACTOR_CO_CONSUMPTION = "co_consumption_lift"

TYPE_FOR_FACTOR = {
    FACTOR_SOURCE: TYPE_SHARED_SOURCE,
    FACTOR_ENTITY: TYPE_SHARED_ENTITY,
    FACTOR_KPI: TYPE_SHARED_KPI,
    FACTOR_SEMANTIC: TYPE_SEMANTIC,
    FACTOR_CO_CONSUMPTION: TYPE_CO_CONSUMPTION,
}

WEIGHTS_PREFIX = "data_mesh_weights"
RENDER_THRESHOLD = "render_threshold"
CONFIDENCE_FLOOR = "review_required_below_confidence"
SESSION_MINUTES = "co_consumption_session_minutes"
LISTED_ITEMS = "rationale.listed_items"
PRECISION = "presentation.precision"
DUPLICATION_SOURCE = "duplication_alert.source_overlap_min"
DUPLICATION_SEMANTIC = "duplication_alert.semantic_similarity_min"

# Columns that identify a thing rather than measure one. Entity overlap is about
# what two products are *about*, and a shared "amount" column says nothing while
# a shared "subscriber_id" says a great deal.
ENTITY_SUFFIXES = ("_id", "_key", "_code", "_number", "_mrn")


@dataclass(frozen=True)
class Edge:
    product_a: str
    product_b: str
    edge_type: str
    strength: float
    confidence: float
    factors: dict[str, dict[str, Any]]
    rationale: str

    @property
    def edge_id(self) -> str:
        return f"MED-{self.product_a}-{self.product_b}-{self.edge_type}"

    def document(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source": self.product_a,
            "target": self.product_b,
            "edge_type": self.edge_type,
            "strength": self.strength,
            "confidence": self.confidence,
            "factors": self.factors,
            "rationale": self.rationale,
        }


def _products(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT p.product_id, p.name, p.purpose, p.domain_code, p.industry_code, "
        "       coalesce(array_agg(DISTINCT e.upstream_id) "
        "                FILTER (WHERE e.upstream_id IS NOT NULL), '{}') AS sources, "
        "       coalesce(array_agg(DISTINCT k.kpi_id) FILTER (WHERE k.kpi_id IS NOT NULL), "
        "                '{}') AS kpis, "
        "       coalesce(array_agg(DISTINCT col.name) FILTER (WHERE col.name IS NOT NULL), "
        "                '{}') AS columns "
        "FROM data_product p "
        "LEFT JOIN lineage_edge e ON e.downstream_id = p.product_id "
        "  AND e.downstream_type = 'data_product' AND e.upstream_type = 'source_system' "
        "LEFT JOIN kpi_definition k ON k.source_of_record = p.product_id "
        "LEFT JOIN data_product_column col ON col.product_id = p.product_id "
        "GROUP BY p.product_id, p.name, p.purpose, p.domain_code, p.industry_code "
        "ORDER BY p.product_id",
    )


def _dependencies(connection: psycopg.Connection[Any]) -> set[tuple[str, str]]:
    """Direct product-to-product lineage, as unordered pairs."""
    return {
        tuple(sorted((row["upstream_id"], row["downstream_id"])))  # type: ignore[misc]
        for row in fetch_all(
            connection,
            "SELECT upstream_id, downstream_id FROM lineage_edge "
            "WHERE upstream_type = 'data_product' AND downstream_type = 'data_product'",
        )
    }


def _co_consumption(
    connection: psycopg.Connection[Any], session_minutes: int
) -> dict[tuple[str, str], float]:
    """How often the same person queried both inside one session window.

    Jaccard over the session sets, not the share of the rarer product's
    sessions. The share measure saturates: a product queried in twenty sessions
    that all happen to include a product queried in two thousand scores 1.0, and
    the mesh then draws its strongest co-consumption edge between two things
    nobody uses together in any meaningful sense. Jaccard charges for the
    sessions that touched only one of them, which is exactly the evidence
    against the edge.
    """
    rows = fetch_all(
        connection,
        "WITH windowed AS ("
        "  SELECT principal_id, asset_id, "
        "         floor(extract(epoch FROM occurred_at) / (%s * 60)) AS bucket "
        "  FROM usage_event WHERE asset_type = 'data_product' AND principal_id IS NOT NULL"
        "), sessions AS (SELECT DISTINCT principal_id, bucket, asset_id FROM windowed), "
        "totals AS (SELECT asset_id, count(*) AS n FROM sessions GROUP BY asset_id) "
        "SELECT a.asset_id AS left_id, b.asset_id AS right_id, count(*) AS together, "
        "       ta.n + tb.n - count(*) AS either_n "
        "FROM sessions a JOIN sessions b "
        "  ON a.principal_id = b.principal_id AND a.bucket = b.bucket "
        " AND a.asset_id < b.asset_id "
        "JOIN totals ta ON ta.asset_id = a.asset_id "
        "JOIN totals tb ON tb.asset_id = b.asset_id "
        "GROUP BY 1, 2, ta.n, tb.n",
        (session_minutes,),
    )
    return {
        (row["left_id"], row["right_id"]): (
            float(row["together"]) / float(row["either_n"]) if row["either_n"] else 0.0
        )
        for row in rows
    }


def _entities(columns: list[str]) -> set[str]:
    return {name.lower() for name in columns if name.lower().endswith(ENTITY_SUFFIXES)}


def compute(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> tuple[list[Edge], list[Edge]]:
    """Every product pair, scored. Returns (renderable, held-for-review)."""
    weights = {
        code: float(rubric.number(f"{WEIGHTS_PREFIX}.{code}"))
        for code in (FACTOR_SOURCE, FACTOR_ENTITY, FACTOR_KPI, FACTOR_SEMANTIC,
                     FACTOR_CO_CONSUMPTION)
    }
    threshold = float(rubric.number(RENDER_THRESHOLD))
    floor = float(rubric.number(CONFIDENCE_FLOOR))
    listed = int(rubric.number(LISTED_ITEMS))
    session_minutes = int(rubric.number(SESSION_MINUTES))
    precision = int(rubric.number(PRECISION))

    products = _products(connection)
    dependencies = _dependencies(connection)
    together = _co_consumption(connection, session_minutes)
    embedder = embedding.active_embedder()
    vectors = {
        product["product_id"]: embedder.embed(f"{product['purpose']} {product['name']}")
        for product in products
    }

    renderable: list[Edge] = []
    held: list[Edge] = []

    # Unordered pairs, written out rather than via combinations(products, 2):
    # the pair size is structural, and the rule against numeric literals does
    # not distinguish a structural 2 from a tunable one.
    for index, left in enumerate(products):
        for right in products[index + 1:]:
            names = (left["product_id"], right["product_id"])
            pair = tuple(sorted(names))

            signals = {
                FACTOR_SOURCE: factors.overlap_factor(
                    FACTOR_SOURCE, set(left["sources"]), set(right["sources"]),
                    noun=factors.Noun("upstream source system", "upstream source systems"), names=names, listed_items=listed,
                ),
                FACTOR_ENTITY: factors.overlap_factor(
                    FACTOR_ENTITY, _entities(left["columns"]), _entities(right["columns"]),
                    noun=factors.Noun("entity key", "entity keys"), names=names, listed_items=listed,
                ),
                FACTOR_KPI: factors.overlap_factor(
                    FACTOR_KPI, set(left["kpis"]), set(right["kpis"]),
                    noun=factors.Noun("certified KPI", "certified KPIs"), names=names, listed_items=listed,
                ),
                FACTOR_SEMANTIC: factors.scalar_factor(
                    FACTOR_SEMANTIC,
                    embedding.cosine(vectors[names[0]], vectors[names[1]]),
                    detail=f"{names[0]} and {names[1]} describe their purpose in similar terms",
                ),
                FACTOR_CO_CONSUMPTION: factors.scalar_factor(
                    FACTOR_CO_CONSUMPTION,
                    together.get(pair, 0.0),
                    detail=f"the same people query {names[0]} and {names[1]} in one sitting",
                    evidence=factors.ONE if pair in together else factors.ZERO,
                ),
            }

            edge_strength = factors.strength(signals, weights)
            if edge_strength < threshold:
                continue

            edge_confidence = factors.confidence(signals, weights)
            leading = factors.dominant(signals, weights)
            edge_type = (
                TYPE_DEPENDENCY if pair in dependencies else TYPE_FOR_FACTOR[leading.code]
            )
            rationale = (
                f"{names[0]} is built from {names[1]}, or the reverse"
                if edge_type == TYPE_DEPENDENCY
                else leading.detail
            )

            edge = Edge(
                product_a=pair[0],
                product_b=pair[1],
                edge_type=edge_type,
                strength=round(edge_strength, precision),
                confidence=round(edge_confidence, precision),
                factors={
                    code: {"value": round(signal.value, precision),
                           "evidence": signal.evidence, "detail": signal.detail}
                    for code, signal in signals.items()
                },
                rationale=rationale,
            )
            (renderable if edge_confidence >= floor else held).append(edge)

    return renderable, held


def persist(
    connection: psycopg.Connection[Any], tenant: str, edges: list[Edge]
) -> int:
    """Write the renderable edges, replacing what was there.

    A full replace rather than an upsert: an edge that no longer computes has to
    disappear, and a mesh that only ever gains edges slowly becomes a picture of
    every relationship that ever held. Reviewed edges survive the delete —
    somebody looked at those and said keep them.
    """
    connection.execute("DELETE FROM mesh_edge_data WHERE reviewed_by IS NULL")
    for edge in edges:
        connection.execute(
            "INSERT INTO mesh_edge_data (edge_id, tenant_id, product_a, product_b, "
            "  edge_type, strength, factors, confidence, rationale, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (product_a, product_b, edge_type) DO UPDATE SET "
            "  strength = EXCLUDED.strength, factors = EXCLUDED.factors, "
            "  confidence = EXCLUDED.confidence, rationale = EXCLUDED.rationale, "
            "  computed_at = now()",
            (edge.edge_id, tenant, edge.product_a, edge.product_b, edge.edge_type,
             edge.strength, json.dumps(edge.factors), edge.confidence, edge.rationale),
        )
    return len(edges)


def duplication_candidates(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> list[dict[str, Any]]:
    """Pairs that look like the same product built twice.

    Both thresholds must be met. Either one alone is common and unremarkable —
    products in a domain share sources, and products with similar purposes are
    what a coherent estate looks like. Both together is the signal.
    """
    source_min = float(rubric.number(DUPLICATION_SOURCE))
    semantic_min = float(rubric.number(DUPLICATION_SEMANTIC))
    return [
        {
            **row,
            "why": (
                f"source overlap {row['factors'][FACTOR_SOURCE]['value']} and semantic "
                f"similarity {row['factors'][FACTOR_SEMANTIC]['value']} both clear the "
                "duplication thresholds"
            ),
        }
        for row in fetch_all(
            connection,
            "SELECT edge_id, product_a, product_b, edge_type, strength, confidence, "
            "       factors, rationale FROM mesh_edge_data "
            "WHERE (factors -> %s ->> 'value')::numeric >= %s "
            "  AND (factors -> %s ->> 'value')::numeric >= %s "
            "ORDER BY strength DESC",
            (FACTOR_SOURCE, source_min, FACTOR_SEMANTIC, semantic_min),
        )
    ]


def blast_radius(
    connection: psycopg.Connection[Any], source_id: str
) -> dict[str, Any]:
    """Everything downstream of one source system, with who depends on it.

    The question this answers is "if this source goes down, or its schema
    changes, who finds out the hard way?". So it walks past the products to the
    agents bound to them and the people holding live grants, because those are
    the ones who will notice.
    """
    # DISTINCT: the harvest records more than one relationship between a source
    # and a product — it derives from it and it reads it — and a blast radius
    # that lists the same product once per relationship overstates the reach in
    # exactly the situation where the count matters.
    products = fetch_all(
        connection,
        "SELECT DISTINCT p.product_id, p.name, p.domain_code, p.sensitivity_tier, p.tier "
        "FROM lineage_edge e JOIN data_product p ON p.product_id = e.downstream_id "
        "WHERE e.upstream_type = 'source_system' AND e.upstream_id = %s "
        "  AND e.downstream_type = 'data_product' ORDER BY p.product_id",
        (source_id,),
    )
    product_ids = [row["product_id"] for row in products]
    if not product_ids:
        return {
            "source_id": source_id, "products": [], "agents": [], "consumers": [],
            "consumer_count": 0,
        }

    agents = fetch_all(
        connection,
        "SELECT DISTINCT a.agent_id, a.name, b.product_id "
        "FROM agent_product_binding b "
        "JOIN agent_version v ON v.agent_version_id = b.agent_version_id "
        "JOIN agent a ON a.current_version_id = v.agent_version_id "
        "WHERE b.product_id = ANY(%s) ORDER BY a.agent_id",
        (product_ids,),
    )
    consumers = fetch_all(
        connection,
        "SELECT g.asset_id, count(DISTINCT g.principal_id) AS consumers "
        "FROM entitlement_grant g "
        "WHERE g.asset_id = ANY(%s) AND g.revoked_at IS NULL AND g.expires_at > now() "
        "GROUP BY g.asset_id ORDER BY g.asset_id",
        (product_ids,),
    )
    return {
        "source_id": source_id,
        "products": products,
        "agents": agents,
        "consumers": consumers,
        "consumer_count": sum(int(row["consumers"]) for row in consumers),
    }
