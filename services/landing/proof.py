"""The value-proof tiles (section 6.2 band 9).

Three quantified outcomes, each one a number this system already computes for
its own consoles rather than a figure written for the front page. That is the
point of the band: a marketing claim and an internal metric that disagree is a
marketing claim, and the visitor who later sees the console would find out.

Every tile states its window and its source. A tile with nothing behind it is
omitted rather than shown at zero — an estate that has not yet deflected an
analyst hour should not claim a zero as an achievement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_one
from services.common.rubrics import Rubric
from services.common.timing import HOUR
from services.mesh import data as data_mesh

ZERO = Decimal(0)


@dataclass(frozen=True)
class ProofTile:
    code: str
    label: str
    value: float
    unit: str
    detail: str

    def document(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "detail": self.detail,
        }


def _hours_deflected(connection: psycopg.Connection[Any]) -> ProofTile | None:
    """From the most recent stored value snapshot, never recomputed here.

    The console reads the same snapshot, so the front page and the board pack
    quote one number.
    """
    row = fetch_one(
        connection,
        "SELECT snapshot_ref, sum(deflected_hours) AS hours, "
        "       min(period_start) AS start, max(period_end) AS finish "
        "FROM value_measurement "
        "WHERE snapshot_ref = ("
        "  SELECT snapshot_ref FROM value_measurement ORDER BY computed_at DESC LIMIT 1"
        ") GROUP BY snapshot_ref",
    )
    if row is None or row["hours"] is None or Decimal(str(row["hours"])) <= ZERO:
        return None
    return ProofTile(
        code="hours_deflected",
        label="Analyst hours deflected",
        value=float(Decimal(str(row["hours"]))),
        unit="hours",
        detail=(
            f"Measured over {row['start']} to {row['finish']} from answered questions "
            "and their acceptance rate, not estimated."
        ),
    )


def _duplicates_avoided(
    connection: psycopg.Connection[Any], mesh_rubric: Rubric
) -> ProofTile | None:
    """Pairs the mesh says are the same product built twice.

    Avoided, not merely detected: each pair is a build the estate can decline to
    repeat. The claim is deliberately the count of pairs rather than a money
    figure, because the saving depends on what the second team would have spent
    and this system does not know that.
    """
    pairs = data_mesh.duplication_candidates(connection, mesh_rubric)
    if not pairs:
        return None
    return ProofTile(
        code="duplicates_avoided",
        label="Duplicate builds identified",
        value=float(len(pairs)),
        unit="pairs",
        detail=(
            "Product pairs that share sources, columns and purpose above both mesh "
            "thresholds — each one a build a second team need not repeat."
        ),
    )


def _time_to_access(connection: psycopg.Connection[Any], window_days: int) -> ProofTile | None:
    """Median hours from request submitted to access provisioned."""
    row = fetch_one(
        connection,
        "SELECT percentile_cont(0.5) WITHIN GROUP ("
        "  ORDER BY extract(epoch FROM (closed_at - submitted_at))) AS seconds, "
        "       count(*) AS decided "
        "FROM request "
        "WHERE request_type = 'access' AND state = 'approved' "
        "  AND submitted_at IS NOT NULL AND closed_at IS NOT NULL "
        "  AND closed_at > now() - %s::int * interval '1 day'",
        (window_days,),
    )
    if row is None or row["seconds"] is None or not row["decided"]:
        return None
    hours = timedelta(seconds=float(row["seconds"])) / HOUR
    return ProofTile(
        code="time_to_access",
        label="Median time to access",
        value=round(hours, 1),
        unit="hours",
        detail=(
            f"Across {int(row['decided'])} approved access requests in the window, "
            "measured from submission to the grant being usable."
        ),
    )


def tiles(
    connection: psycopg.Connection[Any], rubric: Rubric, mesh_rubric: Rubric
) -> list[dict[str, Any]]:
    window = int(rubric.number("value_proof.window_days"))
    limit = int(rubric.number("value_proof.tiles"))
    found = [
        _hours_deflected(connection),
        _duplicates_avoided(connection, mesh_rubric),
        _time_to_access(connection, window),
    ]
    return [tile.document() for tile in found if tile is not None][:limit]
