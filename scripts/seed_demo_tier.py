#!/usr/bin/env python3
"""Materialise the demo-tier row data (BUILD.md 18.1).

Physically separate from the marketplace's own tables and from anything
production: everything lands in ``DEMO_TIER_SCHEMA``, generated from the product
contracts, with no path to real data.

``DEMO_TIER_SCALE`` scales the manifests' ``rows_target`` down for a development
machine. The distributions, seasonality, referential integrity and the planted
patterns are unaffected by scale; only the row count changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seeders._base import load_directory  # noqa: E402
from seed.synthetic.framework import create_and_fill  # noqa: E402
from seed.synthetic.products import ALL_SPECS  # noqa: E402
from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, grant_read, tenant_id  # noqa: E402


def main(argv: list[str]) -> int:
    load_dotenv()
    schema = os.environ["DEMO_TIER_SCHEMA"].lower()
    scale = float(os.environ.get("DEMO_TIER_SCALE", "1.0"))
    wanted = set(argv)

    manifests = {
        document["metadata"]["id"]: document for document in load_directory("products")
    }
    total = 0
    # As the owner: creating a schema needs privileges the application role
    # deliberately does not have, and the grant below is what gives it read
    # access to what is created here.
    with connect(tenant_id(), as_owner=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        grant_read(connection, schema)
        for spec in ALL_SPECS:
            if wanted and spec.product_id not in wanted:
                continue
            manifest = manifests.get(spec.product_id)
            if manifest is None:
                print(f"demo-tier: no manifest for {spec.product_id}", file=sys.stderr)
                return 1
            written = create_and_fill(connection, schema, manifest, spec, scale)
            total += written
            print(f"demo-tier: {spec.product_id} — {written} rows  ({spec.notes})")

    print(f"demo-tier: {total} rows in schema {schema} at scale {scale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
