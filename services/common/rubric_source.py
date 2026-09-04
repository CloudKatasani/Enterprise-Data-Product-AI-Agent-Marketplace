"""Turning a rubric document into addressable criteria.

Flattening turns the document into paths a caller can ask for:
``dimensions.freshness`` becomes the path ``dimensions.freshness`` with kind
``weight``, and an archetype override becomes the same path with ``scope`` set to
the archetype code. That is what lets the quality engine ask for "the freshness
weight, for this archetype" without knowing which rubric answered.

This lives in ``services/`` rather than in the seeder because two things publish
rubric versions: the seeder, from YAML on disk, and the admin console, from an
edited payload. Two flattenings would mean a weight edited through the console
and the same weight seeded from a file could produce different criteria rows,
and the rubric that scored the estate would depend on how it got there.
"""

from __future__ import annotations

import json
from typing import Any


class RubricVersionConflict(RuntimeError):
    """Rubric content moved but its declared version did not.

    Raised by both publishers — the seeder and the admin console — because two
    different rubrics answering to the same version name is the one thing that
    would make a recorded score unreplayable.
    """

# Path prefixes whose leaves are weights rather than plain numbers.
WEIGHT_PREFIXES = (
    "dimensions",
    "weights",
    "criteria",
    "data_mesh_weights",
    "agent_mesh_weights",
    "duplicate_detection.weights",
    "tier_weights",
)
THRESHOLD_MARKERS = ("threshold", "_min", "_max", "_pct", "confidence", "_days", "_ms")
MULTIPLIER_PREFIXES = ("certification_multiplier", "cost_classes")
TARGET_PREFIXES = ("targets", "budgets", "canary", "publish_gate", "sla_hours", "layout")


def kind_for(path: str, value: Any) -> str:
    if isinstance(value, bool):
        return "flag"
    if isinstance(value, list):
        return "list"
    if path.endswith(".label") or path.endswith(".code"):
        return "band" if path.startswith("bands.") else "reference"
    if path.startswith("bands."):
        return "band"
    if "formula" in path:
        return "formula"
    if any(path.startswith(prefix) for prefix in MULTIPLIER_PREFIXES):
        return "multiplier"
    if any(path.startswith(prefix) for prefix in WEIGHT_PREFIXES):
        return "weight"
    if any(path.startswith(prefix) for prefix in TARGET_PREFIXES):
        return "target"
    if any(marker in path for marker in THRESHOLD_MARKERS):
        return "threshold"
    if isinstance(value, int | float):
        return "threshold"
    return "reference"


# A list of mappings becomes addressable when its entries have a natural key.
# Bands key on "code", hard blockers on "when": both name the case they describe.
LIST_KEYS = ("code", "when", "id", "name")

# Where an entry has exactly one other meaningful field, the entry's own path
# resolves to it, so a caller asks for "the band's minimum" or "the blocker's
# cap" without repeating the field name.
SOLE_VALUE_FIELDS = ("weight", "caps_composite_at")


def list_key(item: dict[str, Any]) -> str | None:
    for candidate in LIST_KEYS:
        if candidate in item:
            return candidate
    return None


def flatten(document: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Depth-first flattening into dotted paths, with keyed lists made addressable."""
    flattened: list[tuple[str, Any]] = []
    if isinstance(document, dict):
        for key, value in document.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.extend(flatten(value, path))
    elif isinstance(document, list):
        keys = {
            list_key(item) for item in document if isinstance(item, dict)
        } if document else set()
        key_field = keys.pop() if len(keys) == 1 else None
        if key_field and all(isinstance(item, dict) for item in document):
            for item in document:
                identifier = item[key_field]
                for key, value in item.items():
                    if key == key_field:
                        continue
                    flattened.extend(flatten(value, f"{prefix}.{identifier}.{key}"))
                    if key in SOLE_VALUE_FIELDS:
                        flattened.append((f"{prefix}.{identifier}", value))
        else:
            flattened.append((prefix, document))
    else:
        flattened.append((prefix, document))
    return flattened


def criterion_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    """(path, kind, numeric, text, scope) rows for a whole rubric document."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()

    def add(path: str, value: Any, scope: str | None) -> None:
        key = (path, scope)
        if key in seen:
            return
        seen.add(key)
        kind = kind_for(path, value)
        numeric = None
        text = None
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, int | float):
            numeric = value
        elif isinstance(value, list):
            text = json.dumps(value, separators=(",", ":"))
        else:
            text = str(value)
        rows.append(
            {"path": path, "kind": kind, "numeric_value": numeric, "text_value": text,
             "scope": scope}
        )

    body = {
        key: value for key, value in document.items()
        if key not in {"rubric", "version", "archetype_overrides"}
    }
    for path, value in flatten(body):
        add(path, value, None)

    # Archetype overrides are the same paths under a scope, so a caller asks for
    # "dimensions.freshness for archetype X" and gets the override when there is
    # one and the base weight when there is not.
    for archetype, overrides in (document.get("archetype_overrides") or {}).items():
        for dimension, weight in overrides.items():
            add(f"dimensions.{dimension}", weight, archetype)

    return sorted(rows, key=lambda row: (row["path"], row["scope"] or ""))
