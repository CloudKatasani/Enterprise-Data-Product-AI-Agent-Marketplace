#!/usr/bin/env python3
"""Run the AgentOps evaluation suites and record the run.

Every agent version, or one named with --agent. Results land in
``evaluation_run`` (one row per version, with the per-suite breakdown) and
``evaluation_case`` (the corpus that was executed, so a later reader can see
what "passed" meant), and the version points at its run.

Exit code is the answer to "would this publish?": zero when every blocking suite
cleared its threshold for every version evaluated.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent_runtime import registry  # noqa: E402
from services.agents import evaluation  # noqa: E402
from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, fetch_all, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402

RUBRIC = "agent_evaluation"


def _record(connection, tenant: str, result: evaluation.RunResult) -> str:
    run_id = f"EVL-{result.agent_version_id}-{datetime.now(UTC):%Y%m%d%H%M%S}"
    connection.execute(
        "INSERT INTO evaluation_run (eval_run_id, tenant_id, agent_id, agent_version_ref, "
        "  suite_results, pass_rate_pct, groundedness_pct, threshold_pct, passed, "
        "  started_at, finished_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())",
        (
            run_id, tenant, result.agent_id, result.agent_version_id,
            json.dumps(result.document()), result.pass_rate_pct, result.groundedness_pct,
            result.threshold_pct, result.passed,
        ),
    )
    for suite in result.suites:
        for case in suite.cases:
            connection.execute(
                "INSERT INTO evaluation_case (case_id, tenant_id, agent_id, suite, question, "
                "  expected_behaviour, expected_payload, blocking, origin) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (case_id) DO UPDATE SET expected_behaviour = "
                "  EXCLUDED.expected_behaviour, expected_payload = EXCLUDED.expected_payload",
                (
                    case.case_id, tenant, result.agent_id, suite.suite, case.question,
                    case.detail, json.dumps({"passed": case.passed}), case.blocking,
                    case.origin,
                ),
            )
    connection.execute(
        "UPDATE agent_version SET eval_run_id = %s WHERE agent_version_id = %s",
        (run_id, result.agent_version_id),
    )
    return run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the agent evaluation suites.")
    parser.add_argument("--agent", help="limit to one agent id")
    parser.add_argument("--verbose", action="store_true", help="print every failing case")
    arguments = parser.parse_args(argv)

    load_dotenv()
    tenant = tenant_id()

    with connect(tenant) as connection:
        runtime = registry.build(connection)
        rubric = load_current(connection, RUBRIC)

        where = "WHERE a.agent_id = %s" if arguments.agent else ""
        versions = fetch_all(
            connection,
            "SELECT a.agent_id, a.current_version_id FROM agent a "
            f"{where} ORDER BY a.agent_id",
            (arguments.agent,) if arguments.agent else (),
        )
        if not versions:
            print("evaluate: no agents to evaluate", file=sys.stderr)
            return 1

        failed: list[str] = []
        for row in versions:
            result = evaluation.run_version(
                connection, runtime, row["agent_id"], row["current_version_id"], rubric
            )
            run_id = _record(connection, tenant, result)
            mark = "pass" if result.passed else "FAIL"
            print(
                f"{mark}  {row['agent_id']}  {result.pass_rate_pct}% overall, "
                f"groundedness {result.groundedness_pct}%  ({run_id})"
            )
            for suite in result.suites:
                if suite.passed and not arguments.verbose:
                    continue
                flag = "  " if suite.passed else "! "
                print(
                    f"    {flag}{suite.suite}: {suite.pass_rate_pct}% of {suite.total} "
                    f"(threshold {suite.threshold_pct}%"
                    + (", blocking)" if suite.blocking else ", advisory)")
                )
                for case in suite.cases:
                    if case.passed and not arguments.verbose:
                        continue
                    print(f"        {case.case_id}: {case.detail}")
            if not result.passed:
                failed.append(row["agent_id"])
        connection.commit()

    print(f"\nevaluate: {len(versions)} version(s), {len(failed)} not publishable")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
