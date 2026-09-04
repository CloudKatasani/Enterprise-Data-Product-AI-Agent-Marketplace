"""The agent mesh (M9.2).

Same shape as the data mesh, different question. Where the data mesh asks "are
these two products about the same thing?", this asks "would these two agents
give the same answer, or fight over it?" — which is why shared KPI coverage
carries nearly as much weight as shared data, and why the consolidation check
looks at both together.

    0.35 shared data products
    0.30 KPI coverage overlap
    0.15 semantic similarity of capability statements
    0.10 same domain
    0.10 co-usage — the same people ask both

Two agents covering the same KPI over the same product are a divergence risk
before they are a duplication one: they will be asked the same question and can
answer it differently. Section 15.5's divergence job is what catches that; this
is what makes it visible on a page.
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

TYPE_SHARED_PRODUCT = "shared_data_product"
TYPE_SHARED_KPI = "shared_kpi"
TYPE_SEMANTIC = "semantic"
TYPE_SAME_DOMAIN = "same_domain"
TYPE_CO_USAGE = "co_usage"
TYPE_HANDOFF = "handoff"

EDGE_TYPES = (
    TYPE_SHARED_PRODUCT, TYPE_SHARED_KPI, TYPE_SEMANTIC, TYPE_SAME_DOMAIN,
    TYPE_CO_USAGE, TYPE_HANDOFF,
)

FACTOR_PRODUCT = "shared_data_product"
FACTOR_KPI = "kpi_coverage_overlap"
FACTOR_SEMANTIC = "semantic_similarity"
FACTOR_DOMAIN = "same_domain"
FACTOR_CO_USAGE = "co_usage_lift"

TYPE_FOR_FACTOR = {
    FACTOR_PRODUCT: TYPE_SHARED_PRODUCT,
    FACTOR_KPI: TYPE_SHARED_KPI,
    FACTOR_SEMANTIC: TYPE_SEMANTIC,
    FACTOR_DOMAIN: TYPE_SAME_DOMAIN,
    FACTOR_CO_USAGE: TYPE_CO_USAGE,
}

WEIGHTS_PREFIX = "agent_mesh_weights"
RENDER_THRESHOLD = "render_threshold"
CONFIDENCE_FLOOR = "review_required_below_confidence"
SESSION_MINUTES = "co_consumption_session_minutes"
LISTED_ITEMS = "rationale.listed_items"
PRECISION = "presentation.precision"
CONSOLIDATION_COVERAGE = "consolidation_candidate.coverage_overlap_min"
CONSOLIDATION_PRODUCT = "consolidation_candidate.shared_product_min"

HANDOFF_TOOL_PREFIX = "invoke_agent_"

# Sessions the marketplace runs against itself, excluded from every usage
# signal. See scripts/seeders/agent_usage.py for why.
SYSTEM_SESSION_PREFIX = "SES-SYS-"


@dataclass(frozen=True)
class Edge:
    agent_a: str
    agent_b: str
    edge_type: str
    strength: float
    confidence: float
    factors: dict[str, dict[str, Any]]
    rationale: str

    @property
    def edge_id(self) -> str:
        return f"MEA-{self.agent_a}-{self.agent_b}-{self.edge_type}"

    def document(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source": self.agent_a,
            "target": self.agent_b,
            "edge_type": self.edge_type,
            "strength": self.strength,
            "confidence": self.confidence,
            "factors": self.factors,
            "rationale": self.rationale,
        }


def _agents(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT a.agent_id, a.name, a.domain_code, a.industry_code, "
        "       v.agent_version_id, v.capability_statement, "
        "       coalesce(array_agg(DISTINCT b.product_id) "
        "                FILTER (WHERE b.product_id IS NOT NULL), '{}') AS products, "
        "       coalesce(array_agg(DISTINCT c.kpi_id) FILTER (WHERE c.kpi_id IS NOT NULL), "
        "                '{}') AS kpis, "
        "       coalesce(array_agg(DISTINCT t.tool_name) "
        "                FILTER (WHERE t.tool_name IS NOT NULL), '{}') AS tools "
        "FROM agent a "
        "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "LEFT JOIN agent_product_binding b ON b.agent_version_id = v.agent_version_id "
        "LEFT JOIN agent_kpi_coverage c ON c.agent_version_id = v.agent_version_id "
        "LEFT JOIN agent_tool_binding t ON t.agent_version_id = v.agent_version_id "
        "GROUP BY a.agent_id, a.name, a.domain_code, a.industry_code, v.agent_version_id, "
        "         v.capability_statement ORDER BY a.agent_id",
    )


def _co_usage(
    connection: psycopg.Connection[Any], session_minutes: int
) -> dict[tuple[str, str], float]:
    """The same person asking two agents inside one session window."""
    rows = fetch_all(
        connection,
        "WITH windowed AS ("
        "  SELECT i.principal_id, v.agent_id, "
        "         floor(extract(epoch FROM i.occurred_at) / (%s * 60)) AS bucket "
        "  FROM agent_interaction i "
        "  JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
        "  WHERE i.principal_id IS NOT NULL "
        "    AND i.session_id NOT LIKE %s"
        "), sessions AS (SELECT DISTINCT principal_id, bucket, agent_id FROM windowed), "
        "totals AS (SELECT agent_id, count(*) AS n FROM sessions GROUP BY agent_id) "
        "SELECT a.agent_id AS left_id, b.agent_id AS right_id, count(*) AS together, "
        "       ta.n + tb.n - count(*) AS either_n "
        "FROM sessions a JOIN sessions b "
        "  ON a.principal_id = b.principal_id AND a.bucket = b.bucket "
        " AND a.agent_id < b.agent_id "
        "JOIN totals ta ON ta.agent_id = a.agent_id "
        "JOIN totals tb ON tb.agent_id = b.agent_id "
        "GROUP BY 1, 2, ta.n, tb.n",
        (session_minutes, f"{SYSTEM_SESSION_PREFIX}%"),
    )
    return {
        (row["left_id"], row["right_id"]): (
            float(row["together"]) / float(row["either_n"]) if row["either_n"] else 0.0
        )
        for row in rows
    }


def _handoffs(agents: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Pairs where one agent is bound to invoke the other.

    A handoff is a stronger statement than any similarity: one of them delegates
    to the other, which is a fact about how they run rather than an inference
    about how alike they are.
    """
    known = {agent["agent_id"] for agent in agents}
    pairs: set[tuple[str, str]] = set()
    for agent in agents:
        for tool in agent["tools"]:
            if not tool.startswith(HANDOFF_TOOL_PREFIX):
                continue
            target = tool.removeprefix(HANDOFF_TOOL_PREFIX).upper().replace("_", "-")
            if target in known and target != agent["agent_id"]:
                pairs.add(tuple(sorted((agent["agent_id"], target))))  # type: ignore[arg-type]
    return pairs


def compute(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> tuple[list[Edge], list[Edge]]:
    weights = {
        code: float(rubric.number(f"{WEIGHTS_PREFIX}.{code}"))
        for code in (FACTOR_PRODUCT, FACTOR_KPI, FACTOR_SEMANTIC, FACTOR_DOMAIN,
                     FACTOR_CO_USAGE)
    }
    threshold = float(rubric.number(RENDER_THRESHOLD))
    floor = float(rubric.number(CONFIDENCE_FLOOR))
    listed = int(rubric.number(LISTED_ITEMS))
    precision = int(rubric.number(PRECISION))
    session_minutes = int(rubric.number(SESSION_MINUTES))

    agents = _agents(connection)
    together = _co_usage(connection, session_minutes)
    handoffs = _handoffs(agents)
    embedder = embedding.active_embedder()
    vectors = {
        agent["agent_id"]: embedder.embed(agent["capability_statement"])
        for agent in agents
    }

    renderable: list[Edge] = []
    held: list[Edge] = []

    for index, left in enumerate(agents):
        for right in agents[index + 1:]:
            names = (left["agent_id"], right["agent_id"])
            pair = tuple(sorted(names))
            same_domain = left["domain_code"] == right["domain_code"]

            signals = {
                FACTOR_PRODUCT: factors.overlap_factor(
                    FACTOR_PRODUCT, set(left["products"]), set(right["products"]),
                    noun=factors.Noun("data product", "data products"),
                    names=names, listed_items=listed,
                ),
                FACTOR_KPI: factors.overlap_factor(
                    FACTOR_KPI, set(left["kpis"]), set(right["kpis"]),
                    noun=factors.Noun("covered KPI", "covered KPIs"),
                    names=names, listed_items=listed,
                ),
                FACTOR_SEMANTIC: factors.scalar_factor(
                    FACTOR_SEMANTIC,
                    embedding.cosine(vectors[names[0]], vectors[names[1]]),
                    detail=f"{names[0]} and {names[1]} state similar capabilities",
                ),
                FACTOR_DOMAIN: factors.scalar_factor(
                    FACTOR_DOMAIN,
                    factors.ONE if same_domain else factors.ZERO,
                    detail=(
                        f"both answer in the {left['domain_code']} domain"
                        if same_domain
                        else f"{names[0]} and {names[1]} answer in different domains"
                    ),
                ),
                FACTOR_CO_USAGE: factors.scalar_factor(
                    FACTOR_CO_USAGE,
                    together.get(pair, factors.ZERO),
                    detail=f"the same people ask {names[0]} and {names[1]} in one sitting",
                    evidence=factors.ONE if pair in together else factors.ZERO,
                ),
            }

            edge_strength = factors.strength(signals, weights)
            if edge_strength < threshold:
                continue

            edge_confidence = factors.confidence(signals, weights)
            leading = factors.dominant(signals, weights)
            edge_type = (
                TYPE_HANDOFF if pair in handoffs else TYPE_FOR_FACTOR[leading.code]
            )
            rationale = (
                f"{names[0]} and {names[1]} are bound to invoke one another"
                if edge_type == TYPE_HANDOFF
                else leading.detail
            )

            edge = Edge(
                agent_a=pair[0],
                agent_b=pair[1],
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


def persist(connection: psycopg.Connection[Any], tenant: str, edges: list[Edge]) -> int:
    connection.execute("DELETE FROM mesh_edge_agent WHERE reviewed_by IS NULL")
    for edge in edges:
        connection.execute(
            "INSERT INTO mesh_edge_agent (edge_id, tenant_id, agent_a, agent_b, edge_type, "
            "  strength, factors, confidence, rationale, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (agent_a, agent_b, edge_type) DO UPDATE SET "
            "  strength = EXCLUDED.strength, factors = EXCLUDED.factors, "
            "  confidence = EXCLUDED.confidence, rationale = EXCLUDED.rationale, "
            "  computed_at = now()",
            (edge.edge_id, tenant, edge.agent_a, edge.agent_b, edge.edge_type,
             edge.strength, json.dumps(edge.factors), edge.confidence, edge.rationale),
        )
    return len(edges)


def consolidation_candidates(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> list[dict[str, Any]]:
    """Agents that could be one agent.

    Both thresholds again, and for the same reason as the data mesh: agents in a
    domain naturally share products, and agents with similar remits naturally
    cover overlapping KPIs. Both at once is the case worth a steward's time.
    """
    coverage_min = float(rubric.number(CONSOLIDATION_COVERAGE))
    product_min = float(rubric.number(CONSOLIDATION_PRODUCT))
    return [
        {
            **row,
            "why": (
                f"coverage overlap {row['factors'][FACTOR_KPI]['value']} and shared-product "
                f"overlap {row['factors'][FACTOR_PRODUCT]['value']} both clear the "
                "consolidation thresholds"
            ),
        }
        for row in fetch_all(
            connection,
            "SELECT edge_id, agent_a, agent_b, edge_type, strength, confidence, factors, "
            "       rationale FROM mesh_edge_agent "
            "WHERE (factors -> %s ->> 'value')::numeric >= %s "
            "  AND (factors -> %s ->> 'value')::numeric >= %s "
            "ORDER BY strength DESC",
            (FACTOR_KPI, coverage_min, FACTOR_PRODUCT, product_min),
        )
    ]
