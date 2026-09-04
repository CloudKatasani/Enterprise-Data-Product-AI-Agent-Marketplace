"""Manifest loading for the generators.

Generators read manifests through here so they all see the same documents in the
same order — which is half of what makes regeneration byte-identical (I9).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from scripts._paths import MANIFESTS
from scripts.manifests.loader import load_manifest


def load(kind: str) -> list[tuple[Path, dict[str, Any]]]:
    directory = MANIFESTS / kind
    if not directory.exists():
        return []
    return [(path, load_manifest(path).data) for path in sorted(directory.glob("*.yaml"))]


def digest_of(paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(paths):
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(path.read_bytes())
        hasher.update(b"\x00")
    return hasher.hexdigest()
