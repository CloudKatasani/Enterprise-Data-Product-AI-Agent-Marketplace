#!/usr/bin/env python3
"""Scan for signals, raise incidents, attribute cost and take a value snapshot.

The scheduled job behind the observability and value planes. Ordering matters
and is not arbitrary: costs are attributed before the value snapshot, because a
snapshot that runs first would record a value ratio against yesterday's cost.

Exit code is non-zero when any consumer notification missed its deadline. The
M10 acceptance criterion is a time — a freshness breach notifies consumers and
banners every affected listing within five minutes — and a job that reported a
missed deadline as a success would make the criterion unenforceable.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402
from services.observability import incidents, signals  # noqa: E402
from services.value import finops, model  # noqa: E402

WINDOW_PATH = "reporting.default_window_days"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan signals and refresh the value plane.")
    parser.add_argument("--verbose", action="store_true")
    arguments = parser.parse_args(argv)

    load_dotenv()
    tenant = tenant_id()

    with connect(tenant) as connection:
        watch = load_current(connection, "observability")
        value_rubric = load_current(connection, "value_model")
        cost_rubric = load_current(connection, "finops")

        findings = signals.scan(connection, watch)
        raised = [
            incidents.raise_incident(connection, tenant, watch, finding)
            for finding in findings
        ]
        connection.commit()

        by_severity: dict[str, int] = {}
        for item in raised:
            by_severity[item["severity"]] = by_severity.get(item["severity"], 0) + 1
        print(
            f"observe: {len(findings)} finding(s), {len(raised)} incident(s) "
            + (", ".join(f"{code}={count}" for code, count in sorted(by_severity.items()))
               or "none")
        )
        if arguments.verbose:
            for finding in findings:
                print(f"  [{finding.signal}] {finding.asset_id}: {finding.detail}")

        window = int(value_rubric.number(WINDOW_PATH))
        since = (datetime.now(UTC) - timedelta(days=window)).date()
        rows = finops.attribute_agent_costs(connection, tenant, cost_rubric, since=since)
        snapshot = model.snapshot(
            connection, tenant, value_rubric,
            period_start=since, period_end=datetime.now(UTC).date(),
        )
        connection.commit()
        print(
            f"observe: attributed {rows} agent-day cost row(s); value snapshot "
            f"{snapshot['snapshot_ref']} over {len(snapshot['items'])} asset(s)"
        )

        for candidate in finops.retirement_candidates(connection, cost_rubric):
            print(f"  RETIREMENT  {candidate['asset_id']}: {candidate['why']}")
        for budget in finops.budgets(connection, cost_rubric):
            if budget["state"] != "within":
                print(
                    f"  BUDGET  {budget['agent_id']} is {budget['state']}: "
                    f"{budget['consumed_fraction']} of its per-answer budget"
                )
        share = finops.demo_tier_share(connection, cost_rubric)
        if not share["within_cap"]:
            print(
                f"  DEMO SPEND  {share['share']} of inference goes on demos, above the "
                f"{share['cap']} cap"
            )

        overdue = incidents.overdue_notifications(connection, watch)
        for item in overdue:
            print(
                f"  LATE NOTIFICATION  {item['incident_id']} detected "
                f"{item['detected_at']}, notified {item['notified_at']}"
            )

    return 1 if overdue else 0


if __name__ == "__main__":
    raise SystemExit(main())
