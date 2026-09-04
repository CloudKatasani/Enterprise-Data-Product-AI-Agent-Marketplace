#!/usr/bin/env python3
"""Recompute both meshes and run divergence detection.

Nightly full recompute (section 15.2). Edges the confidence floor holds back are
reported rather than written: the table will not accept them and the graph must
not draw them, but a steward needs to know they exist, because an edge held for
review is a question the estate has not answered rather than a relationship that
does not exist.

Exit code is non-zero when divergence is found, so a scheduled run fails loudly.
Two agents giving different numbers for the same certified KPI is the failure
this whole registry exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._paths import SEED  # noqa: E402
from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, fetch_all, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402
from services.mesh import agents as agent_mesh  # noqa: E402
from services.mesh import data as data_mesh  # noqa: E402
from services.mesh import divergence  # noqa: E402
from services.search import embedding  # noqa: E402

RUBRIC = "mesh_edges"

# The claim a headline is built on, in the order the composer prefers. A golden
# answer's first present claim is the number the agent is asserting about its
# KPI, and it is what two agents are compared on.
HEADLINE_CLAIMS = ("current", "top", "median", "cohort_high")


def _golden_claims(connection) -> dict[tuple[str, str], Decimal]:
    """(agent, kpi) -> the number that agent's golden answer asserts."""
    claims: dict[tuple[str, str], Decimal] = {}
    rows = fetch_all(
        connection,
        "SELECT v.agent_id, e.kpi_class, e.golden_answer_ref FROM demo_exchange e "
        "JOIN agent_version v ON v.agent_version_id = e.agent_version_id "
        "ORDER BY v.agent_id, e.ordinal",
    )
    for row in rows:
        path = SEED.parent / row["golden_answer_ref"]
        if not path.exists():
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for name in HEADLINE_CLAIMS:
            if name in document.get("claims", {}):
                claims[(row["agent_id"], row["kpi_class"])] = Decimal(
                    document["claims"][name]
                )
                break
    return claims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute the meshes.")
    parser.add_argument("--verbose", action="store_true", help="print every edge")
    arguments = parser.parse_args(argv)

    load_dotenv()
    tenant = tenant_id()

    with connect(tenant) as connection:
        embedding.configure_from_rubric(
            load_current(connection, embedding.RUBRIC_CODE)
        )
        rubric = load_current(connection, RUBRIC)

        data_edges, data_held = data_mesh.compute(connection, rubric)
        data_mesh.persist(connection, tenant, data_edges)
        agent_edges, agent_held = agent_mesh.compute(connection, rubric)
        agent_mesh.persist(connection, tenant, agent_edges)
        connection.commit()

        print(
            f"mesh: data {len(data_edges)} edge(s), {len(data_held)} held for review; "
            f"agent {len(agent_edges)} edge(s), {len(agent_held)} held for review"
        )
        if arguments.verbose:
            for edge in sorted(data_edges, key=lambda item: -item.strength):
                print(f"  data  {edge.strength:.3f} [{edge.edge_type}] {edge.rationale}")
            for edge in sorted(agent_edges, key=lambda item: -item.strength):
                print(f"  agent {edge.strength:.3f} [{edge.edge_type}] {edge.rationale}")

        for edge in [*data_held, *agent_held]:
            print(f"  HELD  confidence {edge.confidence:.2f}: {edge.rationale}")

        duplicates = data_mesh.duplication_candidates(connection, rubric)
        consolidations = agent_mesh.consolidation_candidates(connection, rubric)
        for candidate in duplicates:
            print(
                f"  DUPLICATION  {candidate['product_a']} / {candidate['product_b']}: "
                f"{candidate['why']}"
            )
        for candidate in consolidations:
            print(
                f"  CONSOLIDATION  {candidate['agent_a']} / {candidate['agent_b']}: "
                f"{candidate['why']}"
            )

        shared = divergence.shared_coverage(connection)
        found = [
            item
            for item in divergence.compare(connection, rubric, _golden_claims(connection))
            if item.diverged
        ]
        print(
            f"divergence: {len(shared)} KPI(s) covered by more than one agent, "
            f"{len(found)} diverging"
        )
        for item in found:
            print(f"  DIVERGENCE  {item.document()['detail']}")

        for item in divergence.cross_product(connection):
            print(
                f"  CROSS-PRODUCT  {item['kpi_id']} names {item['source_of_record']} as its "
                f"source of record but is served from {', '.join(item['claimed_by'])}"
            )

    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
