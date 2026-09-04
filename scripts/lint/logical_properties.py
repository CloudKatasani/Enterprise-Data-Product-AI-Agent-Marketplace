#!/usr/bin/env python3
"""M12.4 — no physical direction property survives in the portal.

Right-to-left support is not a translation task done at the end; it is a
property of every rule written along the way. A stylesheet using ``margin-left``
and ``text-align: left`` mirrors by being rewritten, and a stylesheet using
``margin-inline-start`` and ``text-align: start`` mirrors by setting one
attribute on the document.

So this rule fails the build on a physical direction property anywhere in
``portal/`` — in CSS, and in the Tailwind classes that compile to the same
thing. There is no suppression comment: a rule that needs a physical side is a
rule that needs rethinking, and the logical equivalent exists for every one of
them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lint._common import REPO_ROOT, Finding, report, walk  # noqa: E402

PORTAL = REPO_ROOT / "portal"

# property -> the logical property to use instead.
CSS_PHYSICAL = {
    "margin-left": "margin-inline-start",
    "margin-right": "margin-inline-end",
    "padding-left": "padding-inline-start",
    "padding-right": "padding-inline-end",
    "border-left": "border-inline-start",
    "border-right": "border-inline-end",
    "border-left-width": "border-inline-start-width",
    "border-right-width": "border-inline-end-width",
    "border-left-color": "border-inline-start-color",
    "border-right-color": "border-inline-end-color",
    "border-top-left-radius": "border-start-start-radius",
    "border-top-right-radius": "border-start-end-radius",
    "border-bottom-left-radius": "border-end-start-radius",
    "border-bottom-right-radius": "border-end-end-radius",
}

# `left`/`right` as positioning offsets, and the two text alignments. Written
# separately because they need their own word boundaries.
CSS_OFFSETS = re.compile(r"(?<![-a-z])(left|right)\s*:", re.IGNORECASE)
CSS_TEXT_ALIGN = re.compile(r"text-align\s*:\s*(left|right)\b", re.IGNORECASE)
CSS_TRANSFORM_ORIGIN = re.compile(r"transform-origin\s*:[^;]*\b(left|right)\b", re.IGNORECASE)

TAILWIND_PHYSICAL = {
    "ml-": "ms-",
    "mr-": "me-",
    "pl-": "ps-",
    "pr-": "pe-",
    "border-l-": "border-s-",
    "border-r-": "border-e-",
    "text-left": "text-start",
    "text-right": "text-end",
    "rounded-l-": "rounded-s-",
    "rounded-r-": "rounded-e-",
    "left-": "start-",
    "right-": "end-",
}

# Written as an attribute on the document, which is the one place a direction
# belongs.
ALLOWED_FILES = {PORTAL / "app" / "layout.tsx", PORTAL / "lib" / "locale.ts"}


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def scan_css() -> list[Finding]:
    findings: list[Finding] = []
    for path in walk(PORTAL, (".css",)):
        text = path.read_text(encoding="utf-8")
        for physical, logical in CSS_PHYSICAL.items():
            for match in re.finditer(rf"(?<![-a-z]){re.escape(physical)}\s*:", text):
                findings.append(
                    Finding(
                        path, _line_of(text, match.start()),
                        f"{physical!r} does not mirror; use {logical!r}",
                    )
                )
        for pattern, advice in (
            (CSS_OFFSETS, "use 'inset-inline-start' / 'inset-inline-end'"),
            (CSS_TEXT_ALIGN, "use 'text-align: start' / 'end'"),
            (CSS_TRANSFORM_ORIGIN, "use 'inline-start' / 'inline-end'"),
        ):
            for match in pattern.finditer(text):
                findings.append(
                    Finding(
                        path, _line_of(text, match.start()),
                        f"{match.group(0).strip()!r} does not mirror; {advice}",
                    )
                )
    return findings


def scan_tsx() -> list[Finding]:
    findings: list[Finding] = []
    for path in walk(PORTAL, (".tsx", ".ts")):
        if path in ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for physical, logical in TAILWIND_PHYSICAL.items():
            pattern = (
                rf"(?<![-a-zA-Z]){re.escape(physical)}[a-z0-9]"
                if physical.endswith("-")
                else rf"(?<![-a-zA-Z]){re.escape(physical)}(?![-a-zA-Z])"
            )
            for match in re.finditer(pattern, text):
                findings.append(
                    Finding(
                        path, _line_of(text, match.start()),
                        f"{physical!r} does not mirror; use {logical!r}",
                    )
                )
    return findings


def main() -> int:
    return report("lint:logical-properties", scan_css() + scan_tsx())


if __name__ == "__main__":
    raise SystemExit(main())
