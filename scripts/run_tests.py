#!/usr/bin/env python3
"""Run one pytest suite.

pytest exits 5 when a suite collects nothing. The suites in ``tests/`` fill up
milestone by milestone, so an empty suite is reported as empty and does not fail
the pipeline — but a *missing* suite directory does, because that means the
pipeline stage has been deleted rather than not yet written.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._paths import REPO_ROOT  # noqa: E402

NO_TESTS_COLLECTED = 5


def main(argv: list[str]) -> int:
    if not argv:
        print("run_tests: expected a suite directory", file=sys.stderr)
        return 1
    suite = argv[0]
    suite_path = REPO_ROOT / suite
    if not suite_path.is_dir():
        print(f"run_tests: suite directory {suite} does not exist", file=sys.stderr)
        return 1

    result = subprocess.run(
        [sys.executable, "-m", "pytest", suite, "-q", *argv[1:]],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode == NO_TESTS_COLLECTED:
        print(f"run_tests: {suite} is empty at this milestone")
        return 0
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
