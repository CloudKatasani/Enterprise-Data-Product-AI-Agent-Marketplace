"""Repository paths shared by the build scripts."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = REPO_ROOT / "manifests"
GENERATED = REPO_ROOT / "generated"
SEED = REPO_ROOT / "seed"
PORTAL = REPO_ROOT / "portal"
