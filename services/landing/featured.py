"""What the front page promotes, and why (M11.2, M11.6; section 6.2 bands 3-5).

The ranking is adoption velocity x quality x recency, with the weights held in
the landing rubric. Two rules sit above the score:

* A product below the rubric's quality floor is never promoted, whatever it
  scores. Featuring an at-risk asset on a marketing surface is a governance
  failure, not a ranking one.
* Every card states the reason it is here. A front page that ranks without
  saying why is a recommendation nobody can argue with, and the rest of this
  system is built on being arguable.

The industry selector re-renders the featured bands for one vertical. It is a
filter over the same ranking, not a second ordering: a walkthrough tailored in
one click should show the client the same judgement the estate makes anyway.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric
from services.common.timing import seconds_in

WEIGHT_PATHS = {
    "adoption_velocity": "featured.ranking.adoption_velocity",
    "quality": "featured.ranking.quality",
    "recency": "featured.ranking.recency",
}

ZERO = 0.0
UNIT = 1.0

# The quality rubric states the scale its composite is expressed on, so the
# normalisation here follows a change of scale rather than assuming one.
QUALITY_CEILING = "scale.maximum"


@dataclass(frozen=True)
class FeaturedProduct:
    product_id: str
    name: str
    domain: str
    industry: str
    purpose: str
    certification: str
    sensitivity: str
    quality: float | None
    band: str | None
    freshness_state: str | None
    consumers: int
    kpis: tuple[str, ...]
    agents: tuple[str, ...]
    score: float
    why: str

    def document(self, precision: int) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "purpose": self.purpose,
            "certification": self.certification,
            "sensitivity": self.sensitivity,
            "quality": self.quality,
            "band": self.band,
            "freshness_state": self.freshness_state,
            "consumers": self.consumers,
            "kpis": list(self.kpis),
            "agents": list(self.agents),
            "score": round(self.score, precision),
            # Section 6.3: no unexplained recommendations. The caption is not
            # decoration; it is the only thing that makes the ranking checkable.
            "why": self.why,
        }


ROWS = """
WITH window_use AS (
  SELECT asset_id,
         max(active_consumers) AS consumers,
         sum(query_count) FILTER (WHERE activity_date > current_date - %(recent)s::int)
           AS recent_queries,
         sum(query_count) AS window_queries
  FROM usage_daily_agg
  WHERE asset_type = 'data_product'
    AND activity_date > current_date - %(window)s::int
  GROUP BY asset_id
), latest_score AS (
  SELECT DISTINCT ON (product_id) product_id, composite, band, computed_at
  FROM quality_score_snapshot ORDER BY product_id, computed_at DESC
), freshness AS (
  SELECT DISTINCT ON (q.product_id) q.product_id,
         CASE WHEN r.observed_value IS NULL THEN NULL
              WHEN r.observed_value <= q.tolerance_minutes THEN 'on_time'
              ELSE 'late' END AS state
  FROM quality_rule q
  JOIN quality_result r ON r.rule_id = q.rule_id
  WHERE q.dimension = 'freshness' AND q.enabled
  ORDER BY q.product_id, r.evaluated_at DESC
)
SELECT p.product_id, p.name, p.domain_code AS domain, p.industry_code AS industry,
       p.purpose, p.certification, p.sensitivity_tier AS sensitivity,
       s.composite AS quality, s.band,
       extract(epoch FROM (now() - s.computed_at)) AS score_age_seconds,
       f.state AS freshness_state,
       coalesce(u.consumers, 0) AS consumers,
       coalesce(u.recent_queries, 0) AS recent_queries,
       coalesce(u.window_queries, 0) AS window_queries,
       (SELECT array_agg(k.kpi_name ORDER BY k.kpi_name)
          FROM kpi_definition k
         WHERE k.source_of_record = p.product_id AND k.status = 'certified') AS kpis,
       (SELECT array_agg(DISTINCT a.agent_id ORDER BY a.agent_id)
          FROM agent_product_binding b
          JOIN agent_version v ON v.agent_version_id = b.agent_version_id
          JOIN agent a ON a.current_version_id = v.agent_version_id
         WHERE b.product_id = p.product_id) AS agents
FROM data_product p
LEFT JOIN latest_score s ON s.product_id = p.product_id
LEFT JOIN freshness f ON f.product_id = p.product_id
LEFT JOIN window_use u ON u.asset_id = p.product_id
WHERE p.certification <> 'deprecated'
ORDER BY p.product_id
"""


def _velocity(recent: float, recent_days: float, window: float, window_days: float) -> float:
    """The recent query rate against the product's own rate over the window.

    A product used steadily scores a half; one being picked up now scores above
    it, one being abandoned below. Judging a product against its own past is
    what makes velocity comparable across products of wildly different sizes,
    and the saturating form keeps a single busy week from dominating the page.
    """
    if window <= ZERO or window_days <= ZERO or recent_days <= ZERO:
        return ZERO
    ratio = (recent / recent_days) / (window / window_days)
    return ratio / (UNIT + ratio)


def _recency(age_seconds: float | None, half_life_seconds: float) -> float:
    """Exponential decay on the age of the quality snapshot.

    A score computed months ago is a stale claim however good it is, and a
    marketing surface that promotes one is quoting an old number.
    """
    if age_seconds is None:
        return ZERO
    return math.exp(-age_seconds / half_life_seconds * math.log(UNIT + UNIT))


def rank(
    connection: psycopg.Connection[Any],
    rubric: Rubric,
    quality_rubric: Rubric,
    *,
    industry: str | None = None,
    window_days: int,
) -> list[FeaturedProduct]:
    weights = {key: float(rubric.number(path)) for key, path in WEIGHT_PATHS.items()}
    floor = float(rubric.number("featured.min_quality_composite"))
    half_life_days = float(rubric.number("featured.recency_half_life_days"))
    ceiling = float(quality_rubric.number(QUALITY_CEILING))

    half_life_seconds = seconds_in(half_life_days)
    recent_days = int(rubric.number("featured.velocity_window_days"))

    rows = fetch_all(connection, ROWS, {"window": window_days, "recent": recent_days})
    featured: list[FeaturedProduct] = []

    for row in rows:
        quality = None if row["quality"] is None else float(row["quality"])
        if quality is None or quality < floor:
            continue

        velocity = _velocity(
            float(row["recent_queries"]), recent_days,
            float(row["window_queries"]), window_days,
        )
        normalised_quality = quality / ceiling
        recency = _recency(
            None if row["score_age_seconds"] is None else float(row["score_age_seconds"]),
            half_life_seconds,
        )
        contributions = {
            "adoption_velocity": weights["adoption_velocity"] * velocity,
            "quality": weights["quality"] * normalised_quality,
            "recency": weights["recency"] * recency,
        }
        score = sum(contributions.values())

        featured.append(
            FeaturedProduct(
                product_id=row["product_id"],
                name=row["name"],
                domain=row["domain"],
                industry=row["industry"],
                purpose=row["purpose"],
                certification=row["certification"],
                sensitivity=row["sensitivity"],
                quality=quality,
                band=row["band"],
                freshness_state=row["freshness_state"],
                consumers=int(row["consumers"]),
                kpis=tuple(row["kpis"] or ()),
                agents=tuple(row["agents"] or ()),
                score=score,
                why=_why(row, contributions, quality),
            )
        )

    featured.sort(key=lambda item: (-item.score, item.product_id))
    if industry:
        featured = [item for item in featured if item.industry == industry]
    return featured


def _why(
    row: dict[str, Any], contributions: dict[str, float], quality: float
) -> str:
    """The single strongest reason this card is on the front page.

    One reason, not three: the factor that contributed most of the score, in
    the words a reader would use. A caption listing every factor is a
    scorecard, and a visitor reads a scorecard as noise.
    """
    dominant = max(contributions, key=lambda key: contributions[key])
    consumers = int(row["consumers"])
    if dominant == "adoption_velocity":
        return f"Being picked up now — {consumers} teams active and querying more"
    if dominant == "quality":
        band = row["band"] or "scored"
        return f"Quality {band} at {quality:g} against its own contract"
    return f"Scored this week, with {consumers} teams currently reading it"


def industries(
    connection: psycopg.Connection[Any], rubric: Rubric
) -> list[dict[str, Any]]:
    """Tiles for the industry selector, with the counts behind each one.

    A tile with nothing behind it is a dead end, so an industry appears only
    when it has products to show.
    """
    minimum = int(rubric.number("industries.min_products"))
    tiles = int(rubric.number("industries.tiles"))
    rows = fetch_all(
        connection,
        "SELECT i.code, i.label, "
        "       count(DISTINCT p.product_id) AS products, "
        "       count(DISTINCT a.agent_id) AS agents "
        "FROM industry i "
        "LEFT JOIN data_product p ON p.industry_code = i.code "
        "     AND p.certification <> 'deprecated' "
        "LEFT JOIN agent a ON a.industry_code = i.code "
        "GROUP BY i.code, i.label "
        "HAVING count(DISTINCT p.product_id) >= %s "
        "ORDER BY count(DISTINCT p.product_id) DESC, i.code",
        (minimum,),
    )
    return [
        {
            "code": row["code"],
            "label": row["label"],
            "products": int(row["products"]),
            "agents": int(row["agents"]),
        }
        for row in rows[:tiles]
    ]
