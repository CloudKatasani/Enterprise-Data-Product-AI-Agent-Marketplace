#!/usr/bin/env python3
"""Load taxonomies, rubrics, KPIs, products, agents and synthetic demo data.

Seeding is idempotent: running it twice leaves the same database state. The
loaders land milestone by milestone; this entry point dispatches to whichever
are registered.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    try:
        from scripts.seeders import run_all
    except ImportError:
        print("seed: no seeders registered yet (M1)")
        return 0
    return run_all()


if __name__ == "__main__":
    raise SystemExit(main())
