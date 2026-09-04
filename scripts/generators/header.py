"""Header stamping and the determinism rule for generated files.

BUILD.md section 9 requires every generated file to carry:

    AUTO-GENERATED FROM manifests/<path> BY scripts/gen.py — DO NOT EDIT
    generator_version: <semver>  manifest_hash: <sha256>  generated_at: <iso8601>

and M2.2 requires determinism with "no timestamps inside hashed content", while
the CI step ``npm run gen && git diff --exit-code generated/`` requires the whole
file to be byte-identical when the inputs have not changed.

Both hold at once by making ``generated_at`` a property of the *content* rather
than of the run: the writer compares the newly rendered body against the body
already on disk, and when they match it leaves the existing file — and therefore
its existing timestamp — untouched. ``manifest_hash`` is computed over the inputs
only, never over the header, so the hash is stable under a re-stamp.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

BANNER = "AUTO-GENERATED FROM {source} BY scripts/gen.py — DO NOT EDIT"
STAMP = "generator_version: {version}  manifest_hash: {digest}  generated_at: {generated_at}"

COMMENT_PREFIX = {
    ".sql": "--",
    ".py": "#",
    ".yaml": "#",
    ".yml": "#",
    ".ts": "//",
    ".tsx": "//",
}

_EXISTING_STAMP = re.compile(
    r"generator_version:\s*(?P<version>\S+)\s+manifest_hash:\s*(?P<digest>[0-9a-f]{64})"
    r"\s+generated_at:\s*(?P<generated_at>\S+)"
)


def content_digest(*parts: str) -> str:
    """sha256 over the generator's inputs, in the order given."""
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


def _split_existing(path: Path, prefix: str) -> tuple[str | None, str]:
    """Return ``(generated_at, body)`` of a file already on disk."""
    if not path.exists():
        return None, ""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    header_lines = 0
    generated_at: str | None = None
    for line in lines:
        if not line.startswith(prefix):
            break
        header_lines += 1
        match = _EXISTING_STAMP.search(line)
        if match:
            generated_at = match.group("generated_at")
    # Drop the header and the blank line that follows it.
    body_lines = lines[header_lines:]
    if body_lines and body_lines[0] == "":
        body_lines = body_lines[1:]
    return generated_at, "\n".join(body_lines)


def write_generated(
    path: Path,
    body: str,
    *,
    source: str,
    version: str,
    digest: str,
    json_style: bool = False,
) -> bool:
    """Write ``body`` under a stamped header. Returns True when the file changed.

    An unchanged body keeps the file — and its ``generated_at`` — exactly as it is,
    which is what lets the gen-diff gate be meaningful rather than noisy.
    """
    prefix = COMMENT_PREFIX.get(path.suffix, "#")
    previous_generated_at, previous_body = _split_existing(path, prefix)

    normalised = body.rstrip("\n") + "\n"
    if previous_body.rstrip("\n") + "\n" == normalised and previous_generated_at is not None:
        return False

    generated_at = previous_generated_at
    if generated_at is None or previous_body.rstrip("\n") + "\n" != normalised:
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    if json_style:
        rendered = normalised
    else:
        header = "\n".join(
            [
                f"{prefix} {BANNER.format(source=source)}",
                f"{prefix} "
                + STAMP.format(version=version, digest=digest, generated_at=generated_at),
            ]
        )
        rendered = f"{header}\n\n{normalised}"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True
