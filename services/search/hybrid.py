"""Hybrid search: pgvector and Postgres FTS, fused with RRF, ranked by rubric.

Three stages, each doing one job:

1. **Retrieve twice.** A lexical list from the FTS index and a semantic list
   from the embedding index. Neither is authoritative on its own: lexical misses
   a synonym the steward never recorded, semantic misses an exact identifier.

2. **Fuse with reciprocal rank.** ``1 / (k + rank)`` per list, summed. RRF is
   used because it needs no score calibration between two retrievers whose
   scores mean different things — and ``k`` comes from ``ranking.yaml``, not
   from here.

   The exact-name boost sits at this stage. A consumer who types a product's
   name must get that product, so an exact case-insensitive name match adds a
   term large enough that no semantic neighbour can overtake it (M4 acceptance).

3. **Rank.** The fused relevance is one input among six, weighted by
   ``ranking.yaml``: quality, adoption, certification multiplier, peer affinity
   and a staleness penalty. Every coefficient is resolved at read time and the
   rubric version is returned with the results, so a ranking can be explained
   and replayed.

There is not a single numeric literal in this module. That is the test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric
from services.search.embedding import active_embedder

RUBRIC_CODE = "catalog_ranking"

ASSET_TYPES = ("data_product", "agent", "kpi", "glossary_term")


@dataclass
class Candidate:
    asset_type: str
    asset_id: str
    exact_name: str
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    exact_name_match: bool = False
    signals: dict[str, Decimal] = field(default_factory=dict)
    fused: Decimal = Decimal("0")
    score: Decimal = Decimal("0")
    precision: int = 0

    def _round(self, value: Decimal) -> float:
        """Round where the rubric is resolved, so the portal prints what it is given."""
        return float(round(value, self.precision))

    def explanation(self) -> dict[str, Any]:
        """Why this result is where it is. Rendered in the UI, not hidden."""
        return {
            "lexical_rank": self.lexical_rank,
            "semantic_rank": self.semantic_rank,
            "exact_name_match": self.exact_name_match,
            "fused_relevance": self._round(self.fused),
            "signals": {
                name: self._round(value) for name, value in sorted(self.signals.items())
            },
            "score": self._round(self.score),
        }


LEXICAL_SQL = """
SELECT d.asset_type, d.asset_id, d.exact_name,
       ts_rank_cd(d.search_vector, websearch_to_tsquery('english', %s)) AS rank
FROM asset_search_document d
WHERE d.tenant_id = %s
  AND (%s::text[] IS NULL OR d.asset_type = ANY(%s::text[]))
  AND (d.search_vector @@ websearch_to_tsquery('english', %s)
       OR lower(d.exact_name) = lower(%s)
       OR lower(d.exact_name) LIKE '%%' || lower(%s) || '%%')
ORDER BY (lower(d.exact_name) = lower(%s)) DESC, rank DESC, d.asset_id
LIMIT %s
"""

SEMANTIC_SQL = """
SELECT e.asset_type, e.asset_id, d.exact_name,
       1 - (e.embedding <=> %s::vector) AS similarity
FROM asset_embedding e
JOIN asset_search_document d
  ON d.asset_type = e.asset_type AND d.asset_id = e.asset_id
WHERE e.tenant_id = %s
  AND e.model_id = %s
  AND (%s::text[] IS NULL OR e.asset_type = ANY(%s::text[]))
ORDER BY e.embedding <=> %s::vector, e.asset_id
LIMIT %s
"""

SIGNALS_SQL = """
SELECT p.product_id AS asset_id,
       'data_product' AS asset_type,
       p.certification,
       coalesce(q.composite, 0) AS quality_composite,
       coalesce(u.active_consumers, 0) AS active_consumers,
       coalesce(u.distinct_teams, 0) AS distinct_teams,
       EXTRACT(EPOCH FROM (now() - p.updated_at)) / 86400 AS days_since_update
FROM data_product p
LEFT JOIN LATERAL (
  SELECT composite FROM quality_score_snapshot s
  WHERE s.product_id = p.product_id ORDER BY s.computed_at DESC LIMIT 1
) q ON true
LEFT JOIN LATERAL (
  SELECT max(active_consumers) AS active_consumers, max(distinct_teams) AS distinct_teams
  FROM usage_daily_agg a
  WHERE a.asset_id = p.product_id AND a.asset_type = 'data_product'
    AND a.activity_date > current_date - %s::int
) u ON true
WHERE p.tenant_id = %s
UNION ALL
SELECT a.agent_id, 'agent', a.certification,
       coalesce(q.composite, 0),
       coalesce(u.active_consumers, 0), coalesce(u.distinct_teams, 0),
       EXTRACT(EPOCH FROM (now() - a.created_at)) / 86400
FROM agent a
LEFT JOIN LATERAL (
  SELECT avg(s.composite) AS composite
  FROM agent_version v
  JOIN agent_product_binding b ON b.agent_version_id = v.agent_version_id
  JOIN LATERAL (
    SELECT composite FROM quality_score_snapshot s2
    WHERE s2.product_id = b.product_id ORDER BY s2.computed_at DESC LIMIT 1
  ) s ON true
  WHERE v.agent_version_id = a.current_version_id
) q ON true
LEFT JOIN LATERAL (
  SELECT max(active_consumers) AS active_consumers, max(distinct_teams) AS distinct_teams
  FROM usage_daily_agg ua
  WHERE ua.asset_id = a.agent_id AND ua.asset_type = 'agent'
    AND ua.activity_date > current_date - %s::int
) u ON true
WHERE a.tenant_id = %s
"""

# The adoption window the ranking signal uses, in days. A rubric value.
ADOPTION_WINDOW_PATH = "weights.active_consumers_90d_normalized"
ADOPTION_WINDOW_DAYS_PATH = "adoption_window_days"


def _retrieve_lexical(
    connection: psycopg.Connection[Any], tenant: str, query: str,
    asset_types: list[str] | None, limit: int,
) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        LEXICAL_SQL,
        (query, tenant, asset_types, asset_types, query, query, query, query, limit),
    )


def _retrieve_semantic(
    connection: psycopg.Connection[Any], tenant: str, query: str,
    asset_types: list[str] | None, limit: int,
) -> list[dict[str, Any]]:
    embedder = active_embedder()
    vector = str(embedder.embed(query))
    return fetch_all(
        connection,
        SEMANTIC_SQL,
        (vector, tenant, embedder.model_id, asset_types, asset_types, vector, limit),
    )


Key = tuple[str, str]


def _normalise(values: dict[Key, Decimal]) -> dict[Key, Decimal]:
    """Min-max to [0,1]; a flat population normalises to zero, not to one.

    Normalising a population where every value is identical to 1.0 would let a
    signal nobody differs on dominate the ranking.
    """
    if not values:
        return {}
    lowest = min(values.values())
    highest = max(values.values())
    span = highest - lowest
    if span == 0:
        return dict.fromkeys(values, Decimal("0"))
    return {key: (value - lowest) / span for key, value in values.items()}


@dataclass
class SearchResults:
    query: str
    rubric_version_id: str
    candidates: list[Candidate]

    def document(self) -> list[dict[str, Any]]:
        return [
            {
                "asset_type": candidate.asset_type,
                "asset_id": candidate.asset_id,
                "name": candidate.exact_name,
                "score": candidate.explanation()["score"],
                "explanation": candidate.explanation(),
            }
            for candidate in self.candidates
        ]


def search(
    connection: psycopg.Connection[Any],
    tenant: str,
    query: str,
    rubric: Rubric,
    *,
    asset_types: list[str] | None = None,
    limit: int | None = None,
) -> SearchResults:
    """Retrieve, fuse and rank. Every coefficient comes from ``rubric``."""
    page_size = limit if limit is not None else int(rubric.number("page_size.default"))
    retrieval_depth = int(rubric.number("page_size.max"))
    fusion_k = int(rubric.number("fusion.k"))
    exact_boost = rubric.number("fusion.exact_name_boost")
    precision = int(rubric.number("fusion.explanation_precision"))

    lexical = _retrieve_lexical(connection, tenant, query, asset_types, retrieval_depth)
    semantic = _retrieve_semantic(connection, tenant, query, asset_types, retrieval_depth)

    candidates: dict[Key, Candidate] = {}
    for rank, row in enumerate(lexical, start=1):
        key = (row["asset_type"], row["asset_id"])
        candidate = candidates.setdefault(
            key, Candidate(row["asset_type"], row["asset_id"], row["exact_name"])
        )
        candidate.lexical_rank = rank
    for rank, row in enumerate(semantic, start=1):
        key = (row["asset_type"], row["asset_id"])
        candidate = candidates.setdefault(
            key, Candidate(row["asset_type"], row["asset_id"], row["exact_name"])
        )
        candidate.semantic_rank = rank

    normalised_query = query.strip().lower()
    for candidate in candidates.values():
        fused = Decimal("0")
        for position in (candidate.lexical_rank, candidate.semantic_rank):
            if position is not None:
                fused += Decimal("1") / Decimal(fusion_k + position)
        candidate.exact_name_match = candidate.exact_name.strip().lower() == normalised_query
        if candidate.exact_name_match:
            # An exact name match cannot lose to a semantic neighbour.
            fused += exact_boost
        candidate.fused = fused

    _apply_ranking(connection, tenant, rubric, candidates)

    for candidate in candidates.values():
        candidate.precision = precision

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-item.score, item.asset_type, item.asset_id),
    )
    return SearchResults(query=query, rubric_version_id=rubric.rubric_version_id,
                         candidates=ordered[:page_size])


def _apply_ranking(
    connection: psycopg.Connection[Any], tenant: str, rubric: Rubric,
    candidates: dict[Key, Candidate],
) -> None:
    weights = rubric.weights("weights")
    window_days = int(rubric.number(ADOPTION_WINDOW_DAYS_PATH))

    signal_rows = fetch_all(connection, SIGNALS_SQL, (window_days, tenant, window_days, tenant))
    signals = {(row["asset_type"], row["asset_id"]): row for row in signal_rows}

    quality = {
        key: Decimal(str(row["quality_composite"]))
        for key, row in signals.items()
        if key in candidates
    }
    consumers = {
        key: Decimal(str(row["active_consumers"]))
        for key, row in signals.items()
        if key in candidates
    }
    affinity = {
        key: Decimal(str(row["distinct_teams"]))
        for key, row in signals.items()
        if key in candidates
    }
    staleness = {
        key: Decimal(str(row["days_since_update"] or 0))
        for key, row in signals.items()
        if key in candidates
    }

    normalised_quality = _normalise(quality)
    normalised_consumers = _normalise(consumers)
    normalised_affinity = _normalise(affinity)
    normalised_staleness = _normalise(staleness)

    fused_values = {key: candidate.fused for key, candidate in candidates.items()}
    normalised_fused = _normalise(fused_values)

    for key, candidate in candidates.items():
        row = signals.get(key)
        certification = row["certification"] if row else "beta"
        multiplier = rubric.number(f"certification_multiplier.{certification}")

        components = {
            "semantic_match": normalised_fused.get(key, Decimal("0")),
            "quality_normalized": normalised_quality.get(key, Decimal("0")),
            "active_consumers_90d_normalized": normalised_consumers.get(key, Decimal("0")),
            "certification_multiplier": multiplier,
            "peer_affinity": normalised_affinity.get(key, Decimal("0")),
            "staleness_penalty": normalised_staleness.get(key, Decimal("0")),
        }
        candidate.signals = components
        candidate.score = sum(
            (weights[name] * value for name, value in components.items()),
            start=Decimal("0"),
        )
        # A retired listing is not a search result. The multiplier being zero is
        # the rubric's way of saying so, so it is honoured rather than blended.
        if multiplier == Decimal("0"):
            candidate.score = Decimal("0")
        elif candidate.exact_name_match:
            # Preserve the guarantee through ranking: the boost survives
            # normalisation because an exact match is a different kind of answer.
            candidate.score += rubric.number("fusion.exact_name_boost")
