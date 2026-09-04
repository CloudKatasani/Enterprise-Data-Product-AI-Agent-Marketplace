#!/usr/bin/env python3
"""Generator entry point — manifests/ -> generated/.

The individual generators land in M2. This entry point exists from M0 so the
`gen-diff` CI step is wired from the first commit: whatever exists under
generated/ must be reproducible from manifests/ with no diff.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str]) -> int:
    try:
        from scripts.gen import run_all
    except ImportError:
        print("gen: no generators registered yet (M2)")
        return 0
    return run_all(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
