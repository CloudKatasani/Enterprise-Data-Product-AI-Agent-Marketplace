#!/usr/bin/env python3
"""BUILD.md I10 — no numeric threshold lives in application source.

Every weight, threshold, grade band, SLA target, similarity cutoff and ranking
coefficient must be resolved from a rubric table seeded from YAML. This rule
scans ``services/`` (Python) and ``portal/`` (TypeScript) and fails on numeric
literals outside a narrow whitelist:

  * ``0``, ``1`` and ``-1``            — identity, emptiness and "not found"
  * integer literals used as a subscript index
  * HTTP status codes, but only inside ``services/common/http_status.py``
  * anything inside ``portal/styles/`` (design tokens are CSS, not logic)

There is no inline suppression comment. A threshold that needs to exist goes in
``manifests/rubrics/`` and is read at runtime by rubric version id.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lint._common import REPO_ROOT, Finding, report, walk  # noqa: E402

ALLOWED_VALUES = {0, 1, -1}

PY_ROOTS = [REPO_ROOT / "services", REPO_ROOT / "connectors"]
TS_ROOT = REPO_ROOT / "portal"

PY_EXEMPT_FILES = {REPO_ROOT / "services" / "common" / "http_status.py"}
TS_EXEMPT_PREFIXES = (
    TS_ROOT / "styles",
    TS_ROOT / "node_modules",
)
TS_EXEMPT_FILENAMES = {"next.config.ts", "tailwind.config.ts", "postcss.config.mjs"}


class PythonNumberVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self._index_nodes: set[int] = set()

    def visit_Subscript(self, node: ast.Subscript) -> None:
        for child in ast.walk(node.slice):
            if isinstance(child, ast.Constant) and isinstance(child.value, int):
                self._index_nodes.add(id(child))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            return
        if id(node) in self._index_nodes:
            return
        if node.value in ALLOWED_VALUES:
            return
        self.findings.append(
            Finding(
                self.path,
                node.lineno,
                f"numeric literal {node.value!r} in application source; "
                "move it to a rubric in manifests/rubrics/ and resolve it by rubric_version_id",
            )
        )


def scan_python() -> list[Finding]:
    findings: list[Finding] = []
    for root in PY_ROOTS:
        for path in walk(root, (".py",)):
            if path in PY_EXEMPT_FILES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visitor = PythonNumberVisitor(path)
            visitor.visit(tree)
            findings.extend(visitor.findings)
    return findings


TS_STRING_OR_COMMENT = re.compile(
    r"""(?s)(/\*.*?\*/)|(//[^\n]*)|('(?:\\.|[^'\\])*')|("(?:\\.|[^"\\])*")|(`(?:\\.|[^`\\])*`)"""
)
TS_NUMBER = re.compile(r"(?<![\w.$])-?\d+(?:_\d+)*(?:\.\d+)?(?:e[-+]?\d+)?(?![\w.])", re.IGNORECASE)
TS_INDEX = re.compile(r"\[\s*-?\d+\s*\]")


def _blank_strings_and_comments(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return TS_STRING_OR_COMMENT.sub(replace, source)


def scan_typescript() -> list[Finding]:
    findings: list[Finding] = []
    for path in walk(TS_ROOT, (".ts", ".tsx")):
        if any(str(path).startswith(str(prefix)) for prefix in TS_EXEMPT_PREFIXES):
            continue
        if path.name in TS_EXEMPT_FILENAMES:
            continue
        cleaned = _blank_strings_and_comments(path.read_text(encoding="utf-8"))
        cleaned = TS_INDEX.sub(lambda m: " " * len(m.group(0)), cleaned)
        for lineno, line in enumerate(cleaned.splitlines(), start=1):
            for match in TS_NUMBER.finditer(line):
                value = float(match.group(0).replace("_", ""))
                if value in ALLOWED_VALUES:
                    continue
                findings.append(
                    Finding(
                        path,
                        lineno,
                        f"numeric literal {match.group(0)} in portal source; "
                        "read it from a rubric via the API or from a motion/design token",
                    )
                )
    return findings


def main() -> int:
    findings = scan_python() + scan_typescript()
    return report("lint:no-magic-numbers", findings)


if __name__ == "__main__":
    raise SystemExit(main())
