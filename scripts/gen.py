#!/usr/bin/env python3
"""Generator entry point — manifests/ + the canonical model -> generated/.

Deterministic: the same inputs produce byte-identical outputs, which is what lets
CI run `npm run gen && git diff --exit-code generated/` as a gate (I9).

Usage:
    python3 scripts/gen.py             # every generator
    python3 scripts/gen.py gen:ddl     # one generator
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generators.registry import run_all  # noqa: E402


def main(argv: list[str]) -> int:
    return run_all(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
