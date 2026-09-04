#!/usr/bin/env python3
"""BUILD.md 13.1 — only ``transform`` and ``opacity`` may be animated.

Animating width, height, top, left, box-shadow, filter or background-position
forces layout or paint inside the animation frame and blows the 4ms main-thread
budget in 13.6. This rule scans:

  * CSS ``transition`` / ``transition-property`` declarations
  * ``@keyframes`` blocks, for declarations of a forbidden property
  * Web Animations API keyframe arrays in TypeScript (``el.animate([...])``)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lint._common import REPO_ROOT, Finding, report, walk  # noqa: E402

PORTAL = REPO_ROOT / "portal"

FORBIDDEN = (
    "width",
    "height",
    "top",
    "left",
    "right",
    "bottom",
    "box-shadow",
    "filter",
    "background-position",
    "margin",
    "padding",
)
FORBIDDEN_JS = {
    "width",
    "height",
    "top",
    "left",
    "right",
    "bottom",
    "boxShadow",
    "filter",
    "backgroundPosition",
    "margin",
    "padding",
}

TRANSITION = re.compile(r"transition(?:-property)?\s*:\s*([^;{}]+)", re.IGNORECASE)
KEYFRAMES_OPEN = re.compile(r"@keyframes[^{]*\{", re.IGNORECASE)
DECLARATION = re.compile(r"([-a-z]+)\s*:", re.IGNORECASE)
ANIMATE_CALL = re.compile(r"\.animate\s*\(\s*(\[.*?\])", re.DOTALL)
JS_KEY = re.compile(r"([A-Za-z][A-Za-z0-9]*)\s*:")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def keyframe_blocks(text: str) -> list[tuple[int, str]]:
    """Every ``@keyframes`` body, found by matching braces.

    Matching braces rather than looking for a closing brace in the first column:
    a keyframes block nested inside ``@layer`` is indented, and a rule that
    assumed otherwise would run past the end of the block and report every
    declaration in the rest of the file.
    """
    blocks: list[tuple[int, str]] = []
    for opening in KEYFRAMES_OPEN.finditer(text):
        depth = 0
        start = opening.end()
        for index in range(opening.end() - 1, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((start, text[start:index]))
                    break
    return blocks


def scan_css() -> list[Finding]:
    findings: list[Finding] = []
    for path in walk(PORTAL, (".css",)):
        text = path.read_text(encoding="utf-8")
        for match in TRANSITION.finditer(text):
            value = match.group(1).lower()
            for prop in FORBIDDEN:
                if re.search(rf"(?<![-a-z]){re.escape(prop)}(?![-a-z])", value):
                    findings.append(
                        Finding(
                            path,
                            _line_of(text, match.start()),
                            f"transition animates {prop!r}; only transform and opacity may animate",
                        )
                    )
        for start, body in keyframe_blocks(text):
            for declaration in DECLARATION.finditer(body):
                prop = declaration.group(1).lower()
                if prop in FORBIDDEN:
                    findings.append(
                        Finding(
                            path,
                            _line_of(text, start + declaration.start()),
                            f"@keyframes declares {prop!r}; only transform and opacity may animate",
                        )
                    )
    return findings


def scan_ts() -> list[Finding]:
    findings: list[Finding] = []
    for path in walk(PORTAL, (".ts", ".tsx")):
        text = path.read_text(encoding="utf-8")
        for call in ANIMATE_CALL.finditer(text):
            for key in JS_KEY.finditer(call.group(1)):
                name = key.group(1)
                if name in FORBIDDEN_JS:
                    findings.append(
                        Finding(
                            path,
                            _line_of(text, call.start(1) + key.start()),
                            f"Web Animations keyframe sets {name!r}; "
                            "only transform and opacity may animate",
                        )
                    )
    return findings


def main() -> int:
    return report("lint:animatable-props", scan_css() + scan_ts())


if __name__ == "__main__":
    raise SystemExit(main())
