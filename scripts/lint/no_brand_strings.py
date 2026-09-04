#!/usr/bin/env python3
"""BUILD.md I13 — no brand string or raw hex colour outside token files.

Two checks:

1. **Brand strings.** Literals listed in ``brand_denylist.txt`` may not appear in
   ``services/`` or ``portal/`` source. The display name is the ``PRODUCT_NAME``
   token resolved from theme config at runtime.
2. **Raw hex colours.** ``#rgb`` / ``#rrggbb`` / ``#rrggbbaa`` may only appear in
   ``portal/styles/tokens/``. Everywhere else references a CSS custom property
   or a Tailwind token that maps onto one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lint._common import REPO_ROOT, Finding, report, walk  # noqa: E402

DENYLIST_PATH = Path(__file__).with_name("brand_denylist.txt")
SCAN_ROOTS = [REPO_ROOT / "services", REPO_ROOT / "connectors", REPO_ROOT / "portal"]
SCAN_SUFFIXES = (".py", ".ts", ".tsx", ".css", ".json", ".html")

TOKEN_DIR = REPO_ROOT / "portal" / "styles" / "tokens"
HEX_COLOUR = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
SELF_REFERENCE = re.compile(r"brand_denylist|PRODUCT_NAME", re.IGNORECASE)


def load_denylist() -> list[str]:
    terms: list[str] = []
    for raw in DENYLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def main() -> int:
    denylist = load_denylist()
    patterns = [(term, re.compile(re.escape(term), re.IGNORECASE)) for term in denylist]
    findings: list[Finding] = []

    for root in SCAN_ROOTS:
        for path in walk(root, SCAN_SUFFIXES):
            text = path.read_text(encoding="utf-8")
            in_tokens = str(path).startswith(str(TOKEN_DIR))
            for lineno, line in enumerate(text.splitlines(), start=1):
                if SELF_REFERENCE.search(line):
                    continue
                for term, pattern in patterns:
                    if pattern.search(line):
                        findings.append(
                            Finding(
                                path,
                                lineno,
                                f"hardcoded brand string {term!r}; render the PRODUCT_NAME token",
                            )
                        )
                if not in_tokens:
                    for match in HEX_COLOUR.finditer(line):
                        findings.append(
                            Finding(
                                path,
                                lineno,
                                f"raw hex colour {match.group(0)} outside portal/styles/tokens/",
                            )
                        )
    return report("lint:no-brand-strings", findings)


if __name__ == "__main__":
    raise SystemExit(main())
