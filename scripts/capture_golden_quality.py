#!/usr/bin/env python3
"""Capture golden quality fixtures (M5.4).

A fixture pins everything a composite was computed from: the rule results, the
unprotected columns, the archetype, and the complete rubric version — every
criterion row, not a reference to one. That is what makes the golden test a real
regression check: it replays without a database, so the rubric cannot have moved
underneath it, and a change in the scoring engine shows up as a changed
composite rather than as a changed rubric.

    python3 scripts/capture_golden_quality.py DP-TEL-001 DP-HLT-002 DP-ENG-001
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._paths import SEED  # noqa: E402
from services.common.db import connect, fetch_all, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402
from services.quality import engine  # noqa: E402

GOLDEN_DIR = SEED / "golden" / "quality"


def capture(connection, tenant: str, product_id: str) -> dict:
    rubric = load_current(connection, engine.RUBRIC_CODE)
    product = fetch_all(
        connection,
        "SELECT archetype_code, name FROM data_product WHERE product_id = %s",
        (product_id,),
    )[0]
    results, unprotected = engine.load_evidence(connection, product_id)
    score = engine.score_from_evidence(
        product_id=product_id,
        archetype=product["archetype_code"],
        results=results,
        unprotected_columns=unprotected,
        rubric=rubric,
    )
    criteria = fetch_all(
        connection,
        "SELECT path, kind, numeric_value, text_value, scope FROM rubric_criterion "
        "WHERE rubric_version_id = %s ORDER BY path, scope NULLS FIRST",
        (rubric.rubric_version_id,),
    )
    del tenant

    return {
        "product_id": product_id,
        "product_name": product["name"],
        "archetype": product["archetype_code"],
        "rubric": {
            "rubric_version_id": rubric.rubric_version_id,
            "code": rubric.code,
            "semver": rubric.semver,
            "source_hash": rubric.source_hash,
            "criteria": [
                {
                    "path": row["path"],
                    "kind": row["kind"],
                    "numeric_value": str(row["numeric_value"])
                    if row["numeric_value"] is not None
                    else None,
                    "text_value": row["text_value"],
                    "scope": row["scope"],
                }
                for row in criteria
            ],
        },
        "results": [
            {
                "rule_id": result.rule_id,
                "result_id": result.result_id,
                "dimension": result.dimension,
                "severity": result.severity,
                "threshold_pct": str(result.threshold_pct)
                if result.threshold_pct is not None
                else None,
                "tolerance": str(result.tolerance) if result.tolerance is not None else None,
                "observed_pct": str(result.observed_pct)
                if result.observed_pct is not None
                else None,
                "observed_value": str(result.observed_value)
                if result.observed_value is not None
                else None,
                "passed": result.passed,
            }
            for result in sorted(results, key=lambda r: r.rule_id)
        ],
        "unprotected_columns": sorted(unprotected),
        "expected": {
            "composite": str(score.composite),
            "band": score.band,
            "blocker_applied": score.blocker_applied,
            "dimensions": {
                name: str(entry.score)
                for name, entry in sorted(score.dimensions.items())
                if entry.measured
            },
        },
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: capture_golden_quality.py <product_id> [...]", file=sys.stderr)
        return 1

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    tenant = tenant_id()
    with connect(tenant) as connection:
        for product_id in argv:
            fixture = capture(connection, tenant, product_id)
            path = GOLDEN_DIR / f"{product_id}.json"
            path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", "utf-8")
            print(
                f"captured {path.relative_to(SEED.parent)}: "
                f"{fixture['expected']['composite']} {fixture['expected']['band']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
