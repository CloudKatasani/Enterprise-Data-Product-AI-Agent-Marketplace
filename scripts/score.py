#!/usr/bin/env python3
"""Score the estate.

    python3 scripts/score.py                # every product
    python3 scripts/score.py DP-TEL-001     # one product

Writes an immutable snapshot per product and prints the composite, the band and
the rubric version it was computed under.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.common.db import connect, fetch_all, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402
from services.quality import engine  # noqa: E402
from services.quality.estate import score_estate  # noqa: E402


def main(argv: list[str]) -> int:
    tenant = tenant_id()
    with connect(tenant) as connection:
        rubric = load_current(connection, engine.RUBRIC_CODE)
        print(f"score: rubric {rubric.code}@{rubric.semver} ({rubric.rubric_version_id})")

        if argv:
            product_ids = argv
        else:
            product_ids = [
                row["product_id"]
                for row in fetch_all(
                    connection,
                    "SELECT product_id FROM data_product WHERE tenant_id = %s "
                    "ORDER BY product_id",
                    (tenant,),
                )
            ]

        scored = 0
        for product_id in product_ids:
            try:
                score = engine.score_product(connection, product_id, rubric)
            except engine.ScoringError as error:
                print(f"score: {product_id} skipped — {error}")
                continue
            snapshot_id = engine.write_snapshot(connection, tenant, score)
            blocker = f"  [capped by {score.blocker_applied}]" if score.blocker_applied else ""
            print(
                f"score: {product_id}  {score.composite}  {score.band}{blocker}  {snapshot_id}"
            )
            scored += 1

        estate = score_estate(connection, tenant, rubric)
        print(
            f"score: estate weighted {estate.weighted_composite} "
            f"(unweighted {estate.unweighted_mean}) across {estate.scored_products} scored, "
            f"{estate.unscored_products} unscored"
        )
    return 0 if scored else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
