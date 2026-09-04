#!/usr/bin/env python3
"""Prepare a workstation for `npm run dev`.

Creates ``.env`` from ``.env.example`` when absent, installs Python dependencies
and reports anything the developer still has to do. Safe to re-run.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._paths import REPO_ROOT  # noqa: E402


def main() -> int:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        shutil.copyfile(REPO_ROOT / ".env.example", env_path)
        print("created .env from .env.example")
    else:
        print(".env already present")

    print("installing python dependencies")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-e", ".[dev]"],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print("pip install failed; see output above", file=sys.stderr)
        return result.returncode

    print("bootstrap complete — run: npm run dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
