#!/usr/bin/env python3
"""Run the platform harvest.

    python3 scripts/harvest.py                 # every pass
    python3 scripts/harvest.py metadata usage  # named passes

Opens whichever session the environment supports (a real Snowflake account when
a private key is configured, otherwise the local sandbox platform), runs the
passes, and prints what landed in each canonical table.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from connectors.base import HarvestResult, ReadOnlyViolation  # noqa: E402
from connectors.snowflake import harvest as snowflake_harvest  # noqa: E402
from connectors.snowflake.session import open_session  # noqa: E402
from services.common.db import connect, tenant_id  # noqa: E402
from services.common.rubrics import load_current  # noqa: E402

PASSES = {
    "metadata": snowflake_harvest.harvest_metadata,
    "lineage": snowflake_harvest.harvest_lineage,
    "usage": snowflake_harvest.harvest_usage,
    "cost": snowflake_harvest.harvest_cost,
    "quality": snowflake_harvest.harvest_quality,
}


def main(argv: list[str]) -> int:
    requested = argv or list(PASSES)
    unknown = [name for name in requested if name not in PASSES]
    if unknown:
        print(f"harvest: unknown pass(es) {', '.join(unknown)}", file=sys.stderr)
        return 1

    tenant = tenant_id()
    session = open_session()
    print(f"harvest: session on {session.platform} for tenant {tenant}")
    try:
        with connect(tenant) as marketplace:
            rubric = load_current(marketplace, snowflake_harvest.RUBRIC_CODE)
            print(f"harvest: rubric {rubric.code}@{rubric.semver} ({rubric.rubric_version_id})")
            total = HarvestResult({})
            for name in requested:
                result = PASSES[name](session, marketplace, tenant, rubric)
                print(f"harvest: {name} — " + ", ".join(result.render()))
                total = total + result
    except ReadOnlyViolation as error:
        print(f"harvest: refused — {error}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print(f"harvest: {total.total()} row(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
