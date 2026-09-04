"""Shared helpers for the CI lint rules.

The lint rules in this package enforce the rules of engagement in BUILD.md
section 0. They fail the build; they are not advisory.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

EXCLUDED_DIR_NAMES = {
    ".git",
    "node_modules",
    ".next",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "coverage",
    "generated",
}


class Finding:
    def __init__(self, path: Path, line: int, message: str) -> None:
        self.path = path
        self.line = line
        self.message = message

    def render(self) -> str:
        rel = os.path.relpath(self.path, REPO_ROOT)
        return f"{rel}:{self.line}: {self.message}"


def walk(root: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIR_NAMES)
        for filename in sorted(filenames):
            if filename.endswith(suffixes):
                yield Path(dirpath) / filename


def report(rule: str, findings: list[Finding]) -> int:
    if not findings:
        print(f"{rule}: clean")
        return 0
    print(f"{rule}: {len(findings)} violation(s)", file=sys.stderr)
    for finding in findings:
        print(f"  {finding.render()}", file=sys.stderr)
    return 1
