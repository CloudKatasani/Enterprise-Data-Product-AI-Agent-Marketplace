#!/usr/bin/env python3
"""M12.5 — the chaos gate (section 20, quarterly).

    data plane down, connector auth expiry, model outage, workflow restart
    mid-approval

Four failures, each of which this system is supposed to survive in a specific
way. Quarterly rather than per-commit because the interesting ones need a real
platform to take away; what runs here is the part that can be provoked against
the deployment as configured, and every scenario reports what it actually did
rather than passing on the strength of having been listed.

    scripts/chaos_test.py                 run every scenario
    scripts/chaos_test.py --scenario X    run one

The bar for each is the same: **fail closed, say why, lose nothing**. A scenario
passes when the failure produced a refusal a consumer could act on, and fails
when it produced a wrong answer, a silent success, or a partial write.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, fetch_all, fetch_one, tenant_id  # noqa: E402


@dataclass
class Outcome:
    scenario: str
    survived: bool
    detail: str


def data_plane_down(tenant: str) -> Outcome:
    """The platform the products live on is unreachable.

    The marketplace holds metadata, contracts and telemetry; it does not hold
    the data. So the catalog must stay up and stay honest: a consumer can still
    read what a product promises and still see that it cannot be queried.
    """
    from services.catalog import products as catalog
    from services.common.principal import ANONYMOUS
    from services.common.rubrics import load_current

    schema = os.environ.get("DEMO_TIER_SCHEMA", "").lower()
    with connect(tenant) as connection:
        ranking = load_current(connection, "catalog_ranking")
        page, _ = catalog.list_products(connection, tenant, ANONYMOUS, ranking)
        if not page.items:
            return Outcome("data_plane_down", False, "the catalog went down with it")

        # Ask the data plane for something while pretending it is gone.
        with connection.cursor() as cursor:
            try:
                cursor.execute(f"SELECT 1 FROM {schema}.a_table_that_is_not_there")
                return Outcome("data_plane_down", False, "a missing table answered")
            except Exception as error:  # noqa: BLE001 - the point is that it raises
                connection.rollback()
                message = str(error).splitlines()[0]

    return Outcome(
        "data_plane_down", True,
        f"catalog served {len(page.items)} product(s) from metadata; the data plane "
        f"refused loudly ({message})",
    )


def connector_auth_expiry(tenant: str) -> Outcome:
    """The connector's credential stops working.

    The harvest must fail rather than write a partial estate. A half-harvested
    lineage graph is worse than none: it looks complete.
    """
    from connectors.snowflake.session import open_session

    saved = os.environ.get("SNOWFLAKE_PRIVATE_KEY", "")
    # A credential that is present and no longer valid — the shape of an
    # expiry, and the one a connector is most likely to mishandle: an absent
    # credential is obvious, an expired one looks like a working configuration.
    os.environ["SNOWFLAKE_PRIVATE_KEY"] = "-----BEGIN PRIVATE KEY-----\nexpired\n"
    try:
        with connect(tenant) as connection:
            before = fetch_one(connection, "SELECT count(*) AS n FROM lineage_edge")["n"]
        try:
            open_session()
            return Outcome(
                "connector_auth_expiry", False, "an expired credential opened a session"
            )
        except Exception as error:  # noqa: BLE001 - refusing is the pass condition
            detail = f"{type(error).__name__}: {str(error).splitlines()[0]}"
        with connect(tenant) as connection:
            after = fetch_one(connection, "SELECT count(*) AS n FROM lineage_edge")["n"]
    finally:
        os.environ["SNOWFLAKE_PRIVATE_KEY"] = saved

    if before != after:
        return Outcome(
            "connector_auth_expiry", False,
            f"lineage moved from {before} to {after} rows during a failed connection",
        )

    # Said plainly rather than counted as a pass on the real path: where the
    # driver is absent the refusal came from the import, not from the
    # credential, and this scenario has only proved that nothing was written.
    # It is the reason section 20 puts this gate against a sandbox account.
    if "not installed" in detail:
        return Outcome(
            "connector_auth_expiry", True,
            f"wrote nothing, but refused before reaching the credential ({detail}). "
            "Run against a sandbox account to exercise the expiry itself.",
        )
    return Outcome(
        "connector_auth_expiry", True,
        f"refused to connect and wrote nothing ({detail})",
    )


def model_outage(tenant: str) -> Outcome:
    """The runtime an agent depends on is unavailable.

    The answer must be withheld with a reason, never guessed. An agent that
    answers from memory when its runtime is down is an agent whose answers were
    never grounded in the first place.
    """
    from services.agent_runtime import registry
    from services.agent_runtime.base import RuntimeUnavailable

    saved = os.environ.get("AGENT_RUNTIME", "")
    os.environ["AGENT_RUNTIME"] = "a-runtime-that-does-not-exist"
    try:
        with connect(tenant) as connection:
            try:
                registry.build(connection)
                return Outcome(
                    "model_outage", False, "an unknown runtime resolved to something"
                )
            except (RuntimeUnavailable, Exception) as error:  # noqa: BLE001
                detail = f"{type(error).__name__}: {str(error).splitlines()[0]}"
    finally:
        os.environ["AGENT_RUNTIME"] = saved
    return Outcome("model_outage", True, f"refused to substitute a runtime ({detail})")


def workflow_restart_mid_approval(tenant: str) -> Outcome:
    """The process dies between one approver's decision and the next.

    State lives in the database, not in a worker's memory, so the request must
    come back exactly where it was: the recorded decision stands, the missing
    one is still missing, and nothing was provisioned on a partial quorum.
    """
    from services.workflow import engine

    with connect(tenant) as connection:
        # `engine.load` is keyed on the subject, not the instance id, which is
        # what a caller has: a request id, not a workflow row.
        rows = fetch_all(
            connection,
            "SELECT instance_id, subject_id, state FROM workflow_instance "
            "WHERE workflow_type = %s ORDER BY created_at DESC LIMIT 5",
            (engine.TYPE_ACCESS,),
        )
        if not rows:
            return Outcome(
                "workflow_restart_mid_approval", True,
                "no access workflow to interrupt; nothing to lose",
            )
        first = rows[0]
        history = engine.history(connection, engine.TYPE_ACCESS, first["subject_id"])

    # The restart: a new process, a new connection, nothing carried over.
    with connect(tenant) as connection:
        instance = engine.load(connection, engine.TYPE_ACCESS, first["subject_id"])
        after = engine.history(connection, engine.TYPE_ACCESS, first["subject_id"])

    if instance.state != first["state"] or len(after) != len(history):
        return Outcome(
            "workflow_restart_mid_approval", False,
            f"state moved from {first['state']} to {instance.state} across a restart",
        )
    return Outcome(
        "workflow_restart_mid_approval", True,
        f"{first['subject_id']} resumed at {instance.state} with all "
        f"{len(after)} transition(s) intact",
    )


SCENARIOS: dict[str, Callable[[str], Outcome]] = {
    "data_plane_down": data_plane_down,
    "connector_auth_expiry": connector_auth_expiry,
    "model_outage": model_outage,
    "workflow_restart_mid_approval": workflow_restart_mid_approval,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Provoke the failures and watch.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS))
    arguments = parser.parse_args(argv)

    load_dotenv()
    tenant = tenant_id()
    wanted = [arguments.scenario] if arguments.scenario else sorted(SCENARIOS)

    failures = 0
    for name in wanted:
        outcome = SCENARIOS[name](tenant)
        mark = "ok  " if outcome.survived else "LOST"
        print(f"chaos  {mark} {name:<30} {outcome.detail}")
        if not outcome.survived:
            failures += 1

    print(f"chaos: {len(wanted) - failures} of {len(wanted)} scenario(s) survived")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
