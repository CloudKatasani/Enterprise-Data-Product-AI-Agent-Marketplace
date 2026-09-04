#!/usr/bin/env python3
"""Materialise the local stand-in data platform (see scripts/seeders/platform_sandbox.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seeders import platform_sandbox  # noqa: E402
from services.common.config import load_dotenv  # noqa: E402
from services.common.db import connect, tenant_id  # noqa: E402


def main() -> int:
    load_dotenv()
    if os.environ.get("SNOWFLAKE_PRIVATE_KEY", "").strip():
        print("seed:platform: a real Snowflake account is configured; nothing to materialise")
        return 0
    schema = os.environ["DEMO_TIER_SCHEMA"].lower()
    tenant = tenant_id()
    with connect(tenant) as connection:
        written = platform_sandbox.seed(connection, tenant, schema)
    print(f"seed:platform: {written} row(s) in schema {schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
