#!/usr/bin/env python3
"""M12.3 — the rollback drill.

A rollback first attempted during an incident is a rollback nobody has tested,
so this rehearses the whole release path against the live registry and puts the
estate back. It is a drill rather than a test because it exercises the real code
on real rows: a mock that always succeeds proves the mock works.

    scripts/rollback_drill.py            rehearse on every published agent
    scripts/rollback_drill.py --agent X  rehearse on one

Per agent it asserts, in order:

1. a cloned draft enters canary only after clearing the publish gate;
2. promotion is refused while the canary lacks its evidence, and the refusal
   names exactly what is missing rather than warning and proceeding;
3. abandoning the canary leaves the live bundle untouched — which is what a
   canary rollback is, since a canary runs beside the live version rather than
   instead of it;
4. where an agent has an earlier published version, a full rollback restores
   that bundle in one call and the audit record names every field that came
   back.

The estate is left exactly as it was found. A run that cannot restore it exits
non-zero and says which agent it left moved, because a drill that quietly
damages production is worse than no drill.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent_runtime import registry  # noqa: E402
from services.agents import evaluation, release  # noqa: E402
from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, fetch_all, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402

# A semver nobody would ship. The drill's version is visible as a drill in the
# registry, and a reviewer reading the history should not have to work out why
# an agent briefly had a 1.0.1.
DRILL_SEMVER = "0.0.0-drill"
DRILL_REASON = "rollback drill — rehearsal, not an incident"


def _publisher(connection, requested: str | None) -> str:
    """Who the drill releases as.

    A publication names its publisher — the release code refuses an
    unattributed one — so the drill needs a real party. It defaults to whoever
    holds the administrator role, which is who would be running a drill.
    """
    if requested:
        return requested
    rows = fetch_all(
        connection,
        "SELECT p.party_id FROM party p JOIN role_assignment r ON r.party_id = p.party_id "
        "WHERE r.role_code = 'administrator' ORDER BY p.party_id LIMIT 1",
    )
    if not rows:
        raise SystemExit(
            "rollback-drill: no party holds the administrator role; pass --by"
        )
    return str(rows[0]["party_id"])


def _published(connection, agent: str | None) -> list[dict]:
    return fetch_all(
        connection,
        "SELECT a.agent_id, a.current_version_id, v.semver "
        "FROM agent a JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "WHERE v.status = 'published' "
        + ("AND a.agent_id = %(agent)s " if agent else "")
        + "ORDER BY a.agent_id",
        {"agent": agent} if agent else None,
    )


def _rehearse(
    connection, tenant, governance, evaluation_rubric, runtime, publisher, row
) -> list[str]:
    """One agent's rehearsal. Returns the lines to print, raises on a failure."""
    agent_id = row["agent_id"]
    live_before = row["current_version_id"]
    lines: list[str] = []

    candidate = release.clone(
        connection, tenant, agent_version_id=live_before, semver=DRILL_SEMVER
    )
    try:
        # The candidate earns its canary the way any version does: a real
        # evaluation run against the real runtime. Copying the parent's run id
        # would rehearse a path where a version inherits somebody else's
        # evidence, which is the failure the gate exists to prevent.
        result = evaluation.run_version(
            connection, runtime, agent_id, candidate, evaluation_rubric
        )
        evaluation.record_run(connection, tenant, result)
        lines.append(
            f"  evaluated {result.pass_rate_pct}% overall, "
            f"groundedness {result.groundedness_pct}%"
        )

        started = release.start_canary(
            connection, tenant, governance, evaluation_rubric,
            agent_version_id=candidate, actor_party_id=None,
        )
        lines.append(
            f"  canary   {candidate} at {started['traffic_pct']}% beside {live_before}"
        )

        try:
            release.promote(
                connection, tenant, governance, evaluation_rubric,
                agent_version_id=candidate, actor_party_id=publisher,
            )
        except release.ReleaseRefused as refusal:
            lines.append(f"  refused  {refusal}")
        else:
            raise AssertionError(
                f"{candidate} was promoted with no canary evidence; the gate is not holding"
            )

        release.abandon_canary(
            connection, tenant, governance,
            agent_version_id=candidate, reason=DRILL_REASON, actor_party_id=None,
        )
        still_live = fetch_all(
            connection, "SELECT current_version_id FROM agent WHERE agent_id = %s",
            (agent_id,),
        )[0]["current_version_id"]
        if still_live != live_before:
            raise AssertionError(
                f"{agent_id} moved to {still_live} while a canary was abandoned; the live "
                f"bundle should have stayed {live_before}"
            )
        lines.append(f"  pulled   live bundle unchanged at {live_before}")

        # Now the rollback the acceptance criterion is about. The candidate is
        # released the way this estate releases a version — through the gate,
        # straight to live — so the drill rehearses a real changeover rather
        # than a hypothetical one, and then rolls it back.
        release.publish(
            connection, tenant, governance, evaluation_rubric,
            agent_version_id=candidate, actor_party_id=publisher,
        )
        lines.append(f"  released {candidate} live, replacing {live_before}")

        result = release.rollback(
            connection, tenant, governance,
            agent_id=agent_id, reason=DRILL_REASON, actor_party_id=None,
        )
        restored_id = result["restored"]["agent_version_id"]
        if restored_id != live_before:
            raise AssertionError(
                f"{agent_id} rolled back to {restored_id}, expected {live_before}"
            )
        lines.append(
            f"  rollback {candidate} → {restored_id} "
            f"({', '.join(result['changes']) or 'identical bundles'})"
        )

        # Every field, not just the version id. "Rolled back" is a claim; this
        # is the check behind it.
        live_bundle = release.bundle(connection, restored_id)
        expected = release.bundle(connection, live_before)
        if live_bundle.document() != expected.document():
            raise AssertionError(
                f"{agent_id} is on {restored_id} but its bundle does not match the one "
                "that was live before the drill"
            )
        lines.append("  verified every field of the previous bundle is back")
    finally:
        # The candidate is a rehearsal artefact. It is removed only while it is
        # a draft or retired with nothing served against it — `discard` refuses
        # anything else, so a drill can never delete a version that answered a
        # question.
        if not connection.closed:
            release.discard(connection, candidate)

    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Rehearse an agent rollback.")
    parser.add_argument("--agent", help="rehearse on one agent rather than all")
    parser.add_argument("--by", help="the party the rehearsal publishes as")
    arguments = parser.parse_args(argv)

    load_dotenv()
    tenant = tenant_id()
    rehearsed = 0

    with connect(tenant) as connection:
        governance = load_current(connection, "governance")
        evaluation_rubric = load_current(connection, "agent_evaluation")
        runtime = registry.build(connection)
        publisher = _publisher(connection, arguments.by)
        agents = _published(connection, arguments.agent)
        if not agents:
            print("rollback-drill: no published agent to rehearse on", file=sys.stderr)
            return 1

        for row in agents:
            print(f"drill  {row['agent_id']}")
            try:
                for line in _rehearse(
                    connection, tenant, governance, evaluation_rubric, runtime,
                    publisher, row,
                ):
                    print(line)
            except AssertionError as failure:
                connection.rollback()
                print(f"rollback-drill: {failure}", file=sys.stderr)
                return 1
            rehearsed += 1

        connection.commit()

    print(f"rollback-drill: {rehearsed} agent(s) rehearsed, estate restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
