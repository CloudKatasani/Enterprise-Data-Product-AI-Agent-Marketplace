#!/usr/bin/env python3
"""Rule 3 — generated files are never hand-edited.

Two checks, both cheap enough to run on every commit:

1. **Header present.** Every file under ``generated/`` carries the auto-generated
   banner with a generator version and a manifest hash. A file without one either
   escaped the generator or was written by hand.
2. **Content matches the generator.** ``npm run gen`` is re-run into a temporary
   directory and every file compared byte for byte, ignoring only the
   ``generated_at`` stamp (which by design does not move when content has not).
   A hand edit shows up here as a mismatch naming the file and the first
   differing line.

CI additionally runs ``npm run gen && git diff --exit-code generated/``, which
catches the same thing from the other direction: a generator whose output has
drifted from what is committed.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lint._common import REPO_ROOT, Finding, report  # noqa: E402

GENERATED = REPO_ROOT / "generated"
BANNER = re.compile(r"AUTO-GENERATED FROM .+ BY scripts/gen\.py")
STAMP = re.compile(r"generator_version:\s*\S+\s+manifest_hash:\s*[0-9a-f]{64}")
GENERATED_AT = re.compile(r"generated_at:\s*\S+")

# JSON cannot carry a comment, so those files carry the same facts in a
# "_generated" object instead.
JSON_MARKER = '"_generated"'


def _has_header(path: Path, text: str) -> bool:
    head = text[:512]
    if path.suffix == ".json":
        # A JSON document carries the same facts in a "_generated" object, or
        # under "x-generated" where a specification forbids unknown top-level keys.
        return ("DO NOT EDIT" in text[:4096]) and (
            JSON_MARKER in text[:4096] or '"x-generated"' in text[:4096]
        )
    return bool(BANNER.search(head) and STAMP.search(head))


def _normalise(text: str) -> str:
    return GENERATED_AT.sub("generated_at: <stamp>", text)


def _first_difference(left: str, right: str) -> int:
    left_lines = left.splitlines()
    right_lines = right.splitlines()
    for index in range(max(len(left_lines), len(right_lines))):
        if left_lines[index : index + 1] != right_lines[index : index + 1]:
            return index + 1
    return 1


def _generated_files(root: Path) -> list[Path]:
    """Files a generator wrote. Build caches such as __pycache__ are not ours."""
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


def main() -> int:
    if not GENERATED.exists():
        print("lint:generated: nothing generated yet")
        return 0

    findings: list[Finding] = []
    committed = sorted(_generated_files(GENERATED))

    for path in committed:
        text = path.read_text(encoding="utf-8")
        if not _has_header(path, text):
            findings.append(
                Finding(path, 1, "generated file carries no auto-generated header")
            )

    from scripts.generators.registry import GENERATORS

    with tempfile.TemporaryDirectory() as workdir:
        scratch = Path(workdir) / "generated"
        # Seed the scratch tree so the writers see the committed content and
        # preserve its timestamps rather than restamping everything.
        shutil.copytree(GENERATED, scratch)
        produced: list[Path] = []
        for _, generator in GENERATORS:
            produced.extend(generator(scratch))

        # The set of generated files is what the generators reported writing —
        # not what happens to be sitting in the scratch tree, which still holds
        # the copies seeded above.
        regenerated = {path.relative_to(scratch) for path in produced}
        existing = {p.relative_to(GENERATED) for p in committed}

        for missing in sorted(existing - regenerated):
            findings.append(
                Finding(GENERATED / missing, 1, "file is not produced by any generator")
            )
        for extra in sorted(regenerated - existing):
            findings.append(
                Finding(GENERATED / extra, 1, "generator produces a file that is not committed")
            )
        for relative in sorted(existing & regenerated):
            expected = _normalise((scratch / relative).read_text(encoding="utf-8"))
            actual = _normalise((GENERATED / relative).read_text(encoding="utf-8"))
            if expected != actual:
                findings.append(
                    Finding(
                        GENERATED / relative,
                        _first_difference(actual, expected),
                        "content differs from what the generator produces; "
                        "edit the manifest or the generator, then run npm run gen",
                    )
                )

    return report("lint:generated", findings)


if __name__ == "__main__":
    raise SystemExit(main())
