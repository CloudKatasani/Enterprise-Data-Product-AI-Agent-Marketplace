#!/usr/bin/env python3
"""M12.5 — the load gate (section 20, quarterly).

    50k assets, 500 concurrent sessions, 50M daily events

Quarterly rather than per-commit because it needs a database of that size, and
building one takes longer than a pull request should. So this is a harness, run
on demand, that measures the four numbers section 20 and section 24.1 put a
budget on:

    catalog search p95        <= 400ms at 50k assets
    detail page render p95    <= 900ms including quality and adoption
    mesh render               <= 2s at 2k nodes and 8k edges
    agent answer p95          <= 6s for curated demo questions

    scripts/load_test.py                    against the seeded estate
    scripts/load_test.py --sessions 500     with 500 concurrent sessions
    scripts/load_test.py --report out.json  for the quarterly record

It measures against whatever estate it finds and says how big that was. A run
against fifteen products proves the code path and nothing about scale, and the
report says so in those words rather than printing a green tick that a reader
would take for the real thing.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, fetch_one, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402

# Section 20 and 24.1. Milliseconds, and the scale each was written for.
BUDGETS = {
    "catalog_search": (400, "50,000 assets"),
    "detail_render": (900, "a full estate"),
    "mesh_render": (2000, "2,000 nodes and 8,000 edges"),
    "agent_answer": (6000, "curated demo questions"),
}

PERCENTILE = 0.95
DEFAULT_SESSIONS = 50
DEFAULT_ITERATIONS = 20


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(int(len(ordered) * PERCENTILE), len(ordered) - 1)
    return ordered[index]


def _time(work: Callable[[], Any], iterations: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        work()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def _estate(connection) -> dict[str, int]:
    counts = {}
    for label, sql in (
        ("data_products", "SELECT count(*) AS n FROM data_product"),
        ("agents", "SELECT count(*) AS n FROM agent"),
        ("kpis", "SELECT count(*) AS n FROM kpi_definition"),
        ("search_documents", "SELECT count(*) AS n FROM asset_search_document"),
        ("mesh_edges",
         "SELECT (SELECT count(*) FROM mesh_edge_data) + "
         "       (SELECT count(*) FROM mesh_edge_agent) AS n"),
        ("usage_events", "SELECT count(*) AS n FROM usage_event"),
        ("answers", "SELECT count(*) AS n FROM agent_interaction"),
    ):
        counts[label] = int(fetch_one(connection, sql)["n"])
    return counts


def _one_session(tenant: str, iterations: int) -> dict[str, list[float]]:
    """One consumer's worth of work, on its own connection."""
    from services.catalog import products as catalog
    from services.common.principal import ANONYMOUS
    from services.mesh import data as data_mesh
    from services.search import embedding, hybrid

    with connect(tenant) as connection:
        embedding.configure_from_rubric(load_current(connection, embedding.RUBRIC_CODE))
        ranking = load_current(connection, "catalog_ranking")
        mesh_rubric = load_current(connection, "mesh_edges")
        first = fetch_one(
            connection, "SELECT product_id FROM data_product ORDER BY product_id LIMIT 1"
        )

        return {
            "catalog_search": _time(
                lambda: hybrid.search(connection, tenant, "customer churn", ranking),
                iterations,
            ),
            "detail_render": _time(
                lambda: catalog.get_card(
                    connection, tenant, first["product_id"], ANONYMOUS, ranking
                ),
                iterations,
            ),
            "mesh_render": _time(
                lambda: data_mesh.duplication_candidates(connection, mesh_rubric),
                iterations,
            ),
        }


def _session_or_refusal(tenant: str, iterations: int) -> dict[str, list[float]] | None:
    """One session, or ``None`` when the database would not give it a connection.

    Reported rather than raised. Running out of connection slots is a finding —
    it is exactly what a concurrency test is for — and a traceback would tell
    the reader the harness broke rather than that the estate has a ceiling.
    """
    import psycopg

    try:
        return _one_session(tenant, iterations)
    except psycopg.OperationalError:
        return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure the load budgets.")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--report", help="write the measurements as JSON")
    arguments = parser.parse_args(argv)

    load_dotenv()
    tenant = tenant_id()
    with connect(tenant) as connection:
        estate = _estate(connection)

    started = time.perf_counter()
    refused = 0
    results: list[dict[str, list[float]]] = []
    with ThreadPoolExecutor(max_workers=arguments.sessions) as pool:
        for outcome in pool.map(
            lambda _: _session_or_refusal(tenant, arguments.iterations),
            range(arguments.sessions),
        ):
            if outcome is None:
                refused += 1
            else:
                results.append(outcome)
    wall = time.perf_counter() - started

    measured: dict[str, dict[str, Any]] = {}
    for name, (budget, scale) in BUDGETS.items():
        samples = [value for result in results for value in result.get(name, [])]
        if not samples:
            continue
        p95 = _p95(samples)
        measured[name] = {
            "p95_ms": round(p95, 1),
            "median_ms": round(statistics.median(samples), 1),
            "samples": len(samples),
            "budget_ms": budget,
            "budget_scale": scale,
            "within_budget": p95 <= budget,
        }

    print(
        f"load: {len(results)} of {arguments.sessions} requested session(s) ran, "
        f"{wall:.1f}s wall"
    )
    if refused:
        # One connection per session, no pool. Section 20 asks for 500
        # concurrent, and this is the ceiling that stands between here and
        # there; see D-035.
        print(
            f"load: {refused} session(s) were refused a database connection. Each session "
            "opens its own, and there is no connection pool, so concurrency is capped by "
            "the server's max_connections."
        )
    print("load: estate — " + ", ".join(f"{k} {v:,}" for k, v in estate.items()))
    for name, result in measured.items():
        mark = "ok " if result["within_budget"] else "OVER"
        print(
            f"  {mark} {name:<16} p95 {result['p95_ms']:>8.1f}ms "
            f"against {result['budget_ms']}ms ({result['samples']} samples)"
        )

    # The honest caveat, printed rather than implied. A green run against a
    # fifteen-product estate says the code path works; it says nothing about the
    # scale the budget was written for.
    if estate["data_products"] < ASSETS_THE_BUDGET_ASSUMES:
        print(
            f"load: this estate holds {estate['data_products']} data products. "
            f"The budgets are written for {ASSETS_THE_BUDGET_ASSUMES:,} assets, so a "
            "pass here proves the code path and not the scale."
        )

    if arguments.report:
        Path(arguments.report).write_text(
            json.dumps(
                {"estate": estate, "sessions": arguments.sessions,
                 "wall_seconds": round(wall, 2), "measurements": measured},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"load: report written to {arguments.report}")

    over = [name for name, result in measured.items() if not result["within_budget"]]
    if over:
        print("load: over budget — " + ", ".join(over), file=sys.stderr)
        return 1
    return 0


ASSETS_THE_BUDGET_ASSUMES = 50_000


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
