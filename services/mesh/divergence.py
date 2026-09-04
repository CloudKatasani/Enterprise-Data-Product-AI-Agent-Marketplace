"""KPI divergence detection (M9.5, section 15.5).

The question: two agents cover the same certified KPI. Asked the same question,
do they give the same number?

If they do not, the marketplace has a worse problem than a wrong answer — it has
two confident answers, and a consumer who believes whichever they saw first.
Section 15.5 requires an incident against *both* agents, because there is no way
to tell from outside which one is wrong, and raising it against one implies the
other is right.

Divergence is measured against the tolerance the exchange itself declares, so an
agent answering a question about a rate is judged on rate-sized differences and
one answering about currency on currency-sized ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric

ZERO = Decimal(0)

PERCENT_SCALE_PATH = "divergence.percent_scale"
DEFAULT_TOLERANCE_PATH = "divergence.default_tolerance_pct"


@dataclass(frozen=True)
class Divergence:
    kpi_id: str
    left: str
    right: str
    left_value: Decimal
    right_value: Decimal
    difference_pct: Decimal
    tolerance_pct: Decimal

    @property
    def diverged(self) -> bool:
        return self.difference_pct > self.tolerance_pct

    def document(self) -> dict[str, Any]:
        return {
            "kpi_id": self.kpi_id,
            "agents": [self.left, self.right],
            "values": [float(self.left_value), float(self.right_value)],
            "difference_pct": float(self.difference_pct),
            "tolerance_pct": float(self.tolerance_pct),
            "diverged": self.diverged,
            "detail": (
                f"{self.left} and {self.right} both answer on {self.kpi_id} and differ by "
                f"{self.difference_pct}%, against a declared tolerance of "
                f"{self.tolerance_pct}%"
            ),
        }


def shared_coverage(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """KPIs more than one current agent version covers.

    This is the population divergence can happen in. An estate where it is empty
    has no divergence risk from agents, which is worth being able to say.
    """
    return fetch_all(
        connection,
        "SELECT c.kpi_id, k.kpi_name, k.unit, "
        "       array_agg(DISTINCT v.agent_id ORDER BY v.agent_id) AS agents "
        "FROM agent_kpi_coverage c "
        "JOIN agent_version v ON v.agent_version_id = c.agent_version_id "
        "JOIN agent a ON a.current_version_id = v.agent_version_id "
        "JOIN kpi_definition k ON k.kpi_id = c.kpi_id "
        "GROUP BY c.kpi_id, k.kpi_name, k.unit "
        "HAVING count(DISTINCT v.agent_id) > 1 "
        "ORDER BY c.kpi_id",
    )


def _claims(
    connection: psycopg.Connection[Any], kpi_id: str, agent_id: str
) -> list[Decimal]:
    """The numbers this agent most recently asserted about this KPI.

    Read from the golden answers rather than from live traffic: a golden answer
    is the agent's answer to a question the steward wrote, which is the only
    place two agents can be compared on the same question. Comparing live
    answers would compare two different questions and find divergence in every
    pair.
    """
    rows = fetch_all(
        connection,
        "SELECT i.citations, i.kpi_definitions, i.confidence FROM agent_interaction i "
        "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
        "WHERE v.agent_id = %s AND %s = ANY(i.kpi_definitions) "
        "  AND i.outcome = 'answered' ORDER BY i.occurred_at DESC",
        (agent_id, kpi_id),
    )
    return [Decimal(str(row["confidence"])) for row in rows if row["confidence"]]


def compare(
    connection: psycopg.Connection[Any],
    rubric: Rubric,
    golden: dict[tuple[str, str], Decimal],
) -> list[Divergence]:
    """Compare recorded answers on shared KPIs.

    `golden` maps (agent_id, kpi_id) to the headline number that agent's golden
    answer asserts. The caller assembles it — usually from `seed/golden/` — so
    that this function has no opinion about where a claim came from, only about
    whether two of them agree.
    """
    scale = Decimal(str(rubric.number(PERCENT_SCALE_PATH)))
    default_tolerance = Decimal(str(rubric.number(DEFAULT_TOLERANCE_PATH)))
    results: list[Divergence] = []
    for row in shared_coverage(connection):
        kpi_id = row["kpi_id"]
        covering = [
            agent for agent in row["agents"] if (agent, kpi_id) in golden
        ]
        for index, left in enumerate(covering):
            for right in covering[index + 1:]:
                left_value = golden[(left, kpi_id)]
                right_value = golden[(right, kpi_id)]
                magnitude = max(abs(left_value), abs(right_value))
                difference = (
                    (abs(left_value - right_value) / magnitude * scale)
                    if magnitude
                    else ZERO
                )
                tolerance = _tolerance(
                    connection, left, right, kpi_id, default_tolerance
                )
                results.append(
                    Divergence(
                        kpi_id=kpi_id,
                        left=left,
                        right=right,
                        left_value=left_value,
                        right_value=right_value,
                        difference_pct=difference.quantize(Decimal("0.01")),
                        tolerance_pct=tolerance,
                    )
                )
    return results


def _tolerance(
    connection: psycopg.Connection[Any],
    left: str,
    right: str,
    kpi_id: str,
    default_tolerance: Decimal,
) -> Decimal:
    """The stricter of the two agents' declared tolerances on this KPI.

    Stricter rather than looser: if one steward said two percent and the other
    said five, the number they disagree about matters at two.
    """
    rows = fetch_all(
        connection,
        "SELECT min(e.tolerance_pct) AS tolerance FROM demo_exchange e "
        "JOIN agent_version v ON v.agent_version_id = e.agent_version_id "
        "WHERE v.agent_id = ANY(%s) AND e.kpi_class = %s",
        ([left, right], kpi_id),
    )
    value = rows[0]["tolerance"] if rows and rows[0]["tolerance"] is not None else None
    return Decimal(str(value)) if value is not None else default_tolerance


def cross_product(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """KPIs whose definition names one source of record but which more than one
    product claims to publish.

    The registry's whole promise is one definition, one owner. Where two products
    both serve a KPI, the mesh's shared-KPI edge is the flag and this is what
    raises it.
    """
    return fetch_all(
        connection,
        "SELECT k.kpi_id, k.kpi_name, k.source_of_record, "
        "       array_agg(DISTINCT c.source_product_id ORDER BY c.source_product_id) "
        "         AS claimed_by "
        "FROM kpi_definition k "
        "JOIN agent_kpi_coverage c ON c.kpi_id = k.kpi_id "
        "GROUP BY k.kpi_id, k.kpi_name, k.source_of_record "
        "HAVING count(DISTINCT c.source_product_id) > 1 "
        "ORDER BY k.kpi_id",
    )
