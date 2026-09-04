"""Estate-level quality (BUILD.md 15.1, tier weighting).

"Tier-1 assets dominate the denominator so a thousand hygienic sandbox tables
cannot mask ungoverned crown jewels."

The estate score is therefore not a mean of composites. Each product's
contribution is weighted by its tier, with the weights coming from the rubric,
and the result carries the breakdown so a number that moved can be explained by
which tier moved it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric
from services.quality.engine import QUANTUM, ZERO

LATEST_SNAPSHOT_SQL = """
SELECT DISTINCT ON (s.product_id)
       s.product_id, s.composite, s.band, p.tier, p.certification, p.name
FROM quality_score_snapshot s
JOIN data_product p ON p.product_id = s.product_id
WHERE s.tenant_id = %s
ORDER BY s.product_id, s.computed_at DESC
"""


@dataclass
class EstateScore:
    weighted_composite: Decimal
    unweighted_mean: Decimal
    scored_products: int
    unscored_products: int
    by_tier: dict[str, dict[str, Any]]
    by_band: dict[str, int]
    rubric_version_id: str

    def document(self) -> dict[str, Any]:
        return {
            "weighted_composite": float(self.weighted_composite),
            "unweighted_mean": float(self.unweighted_mean),
            "scored_products": self.scored_products,
            "unscored_products": self.unscored_products,
            "by_tier": {
                tier: {
                    "products": entry["products"],
                    "mean_composite": float(entry["mean_composite"]),
                    "weight": float(entry["weight"]),
                    "share_of_denominator": float(entry["share"]),
                }
                for tier, entry in sorted(self.by_tier.items())
            },
            "by_band": dict(sorted(self.by_band.items())),
            "rubric_version_id": self.rubric_version_id,
        }


def score_estate(
    connection: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> EstateScore:
    rows = fetch_all(connection, LATEST_SNAPSHOT_SQL, (tenant,))
    total = fetch_all(
        connection,
        "SELECT count(*) AS total FROM data_product WHERE tenant_id = %s",
        (tenant,),
    )
    product_count = int(total[0]["total"]) if total else 0

    numerator = ZERO
    denominator = ZERO
    plain_sum = ZERO
    by_tier: dict[str, dict[str, Any]] = {}
    by_band: dict[str, int] = {}

    for row in rows:
        composite = Decimal(str(row["composite"]))
        weight = rubric.number(f"tier_weights.{row['tier']}")
        numerator += composite * weight
        denominator += weight
        plain_sum += composite

        tier = by_tier.setdefault(
            row["tier"], {"products": 0, "sum": ZERO, "weight": weight, "share": ZERO}
        )
        tier["products"] += 1
        tier["sum"] += composite
        by_band[row["band"]] = by_band.get(row["band"], 0) + 1

    for tier in by_tier.values():
        tier["mean_composite"] = (
            (tier["sum"] / tier["products"]).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
            if tier["products"]
            else ZERO
        )
        tier["share"] = (
            ((tier["weight"] * tier["products"]) / denominator) if denominator else ZERO
        )
        del tier["sum"]

    scored = len(rows)
    return EstateScore(
        weighted_composite=(numerator / denominator).quantize(
            QUANTUM, rounding=ROUND_HALF_EVEN
        )
        if denominator
        else ZERO,
        unweighted_mean=(plain_sum / scored).quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
        if scored
        else ZERO,
        scored_products=scored,
        unscored_products=product_count - scored,
        by_tier=by_tier,
        by_band=by_band,
        rubric_version_id=rubric.rubric_version_id,
    )
