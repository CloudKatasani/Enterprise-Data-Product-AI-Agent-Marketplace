#!/usr/bin/env python3
"""Publish the agent versions that clear the gate.

Publishing is a separate act from passing. The gate says a version *could* be
published; this says someone published it, and records who and against which
rubric version. A version that does not clear the gate is left alone and the
shortfall is printed — the gate is never overridden here, and there is no flag
to override it, because a publish-anyway switch is the only feature that would
make the whole gate decorative.

Run after `npm run evaluate`: the gate reads the evaluation run, so publishing
before evaluating refuses every version for the same, correct reason.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents import publish_gate  # noqa: E402
from services.common import audit  # noqa: E402
from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, fetch_all, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402

EVENT_PUBLISHED = "agent_version.published"
STATUS_PUBLISHED = "published"
OUTCOME_PUBLISHED = "published"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish agent versions that clear the gate.")
    parser.add_argument("--agent", help="limit to one agent id")
    parser.add_argument(
        "--by",
        default="",
        help="party id publishing; recorded on the version and in the audit trail",
    )
    arguments = parser.parse_args(argv)

    load_dotenv()
    tenant = tenant_id()
    # Resolved after the dotenv load, not as an argparse default: a default is
    # evaluated before main runs, when the environment is still empty.
    publisher = arguments.by or os.environ.get("PORTAL_DEV_SUBJECT", "")
    if not publisher:
        print(
            "publish: no publisher. Pass --by or set PORTAL_DEV_SUBJECT; an unattributed "
            "publish is not recorded.",
            file=sys.stderr,
        )
        return 1

    with connect(tenant) as connection:
        rubric = load_current(connection, "agent_evaluation")
        governance = load_current(connection, audit.GOVERNANCE_RUBRIC)

        where = "WHERE a.agent_id = %s" if arguments.agent else ""
        versions = fetch_all(
            connection,
            f"SELECT a.agent_id, a.current_version_id, v.status FROM agent a "
            f"JOIN agent_version v ON v.agent_version_id = a.current_version_id "
            f"{where} ORDER BY a.agent_id",
            (arguments.agent,) if arguments.agent else (),
        )

        published, blocked = 0, 0
        for row in versions:
            result = publish_gate.evaluate(connection, row["current_version_id"], rubric)
            if not result.publishable:
                blocked += 1
                print(f"BLOCK {row['agent_id']}")
                for shortfall in result.shortfalls:
                    print(f"    - {shortfall}")
                continue
            if row["status"] == STATUS_PUBLISHED:
                print(f"  ok  {row['agent_id']} already published")
                continue

            connection.execute(
                "UPDATE agent_version SET status = %s, published_at = now(), "
                "published_by = %s WHERE agent_version_id = %s",
                (STATUS_PUBLISHED, publisher, row["current_version_id"]),
            )
            audit.record(
                connection,
                tenant,
                governance,
                audit_id=f"AUD-PUB-{row['current_version_id']}-{datetime.now(UTC):%Y%m%d%H%M%S}",
                event_name=EVENT_PUBLISHED,
                outcome=OUTCOME_PUBLISHED,
                actor_party_id=publisher,
                asset_type="agent",
                asset_id=row["agent_id"],
                detail={
                    "agent_version_id": row["current_version_id"],
                    "gate": result.document(),
                },
            )
            published += 1
            print(f"PUB   {row['agent_id']} {row['current_version_id']}")
        connection.commit()

    print(f"\npublish: {published} published, {blocked} blocked, {len(versions)} considered")
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
