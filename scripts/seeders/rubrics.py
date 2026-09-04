"""M1.3 — rubric YAML into rubric / rubric_version / rubric_criterion.

A rubric version is immutable and content-addressed by the sha256 of the YAML
that produced it. Re-seeding unchanged YAML is a no-op; re-seeding changed YAML
supersedes the previous version and writes a new one, so prior scores keep
pointing at the rubric they were actually computed under.

Flattening turns the document into addressable criteria: ``dimensions.freshness``
becomes the path ``dimensions.freshness`` with kind ``weight``, and an archetype
override becomes the same path with ``scope`` set to the archetype code. That is
what lets the quality engine ask for "the freshness weight, for this archetype"
without knowing which rubric answered.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg

from scripts.seeders._base import load_directory_with_paths, source_hash

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


def _kind_for(path: str, value: Any) -> str:
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


def _flatten(document: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Depth-first flattening into dotted paths, with list-of-mappings keyed by code."""
    flattened: list[tuple[str, Any]] = []
    if isinstance(document, dict):
        for key, value in document.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.extend(_flatten(value, path))
    elif isinstance(document, list):
        if document and all(isinstance(item, dict) and "code" in item for item in document):
            for item in document:
                code = item["code"]
                for key, value in item.items():
                    if key == "code":
                        continue
                    flattened.extend(_flatten(value, f"{prefix}.{code}.{key}"))
                    # A criterion list entry addressed by its code alone resolves
                    # to its weight, which is what a caller usually wants.
                    if key == "weight":
                        flattened.append((f"{prefix}.{code}", value))
        else:
            flattened.append((prefix, document))
    else:
        flattened.append((prefix, document))
    return flattened


def _criterion_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    """(path, kind, numeric, text, scope) rows for a whole rubric document."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()

    def add(path: str, value: Any, scope: str | None) -> None:
        key = (path, scope)
        if key in seen:
            return
        seen.add(key)
        kind = _kind_for(path, value)
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
    for path, value in _flatten(body):
        add(path, value, None)

    # Archetype overrides are the same paths under a scope, so a caller asks for
    # "dimensions.freshness for archetype X" and gets the override when there is
    # one and the base weight when there is not.
    for archetype, overrides in (document.get("archetype_overrides") or {}).items():
        for dimension, weight in overrides.items():
            add(f"dimensions.{dimension}", weight, archetype)

    return sorted(rows, key=lambda row: (row["path"], row["scope"] or ""))


class RubricVersionConflict(RuntimeError):
    """Rubric content moved but its declared version did not."""


def _rubric_id(code: str, tenant: str) -> str:
    return f"RUB-{tenant}-{code}"


def _version_id(code: str, tenant: str, digest: str) -> str:
    return f"RV-{tenant}-{code}-{digest[:12]}"


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    documents = load_directory_with_paths("rubrics")
    written = 0

    for path, document in documents:
        code = document["rubric"]
        semver = document["version"]
        digest = source_hash(Path(path))
        rubric_id = _rubric_id(code, tenant)
        version_id = _version_id(code, tenant, digest)

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO rubric (rubric_id, tenant_id, code, description) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id, code) DO UPDATE "
                "SET description = EXCLUDED.description",
                (rubric_id, tenant, code, f"{code} rubric seeded from {Path(path).name}"),
            )

            cursor.execute(
                "SELECT rubric_version_id FROM rubric_version "
                "WHERE rubric_id = %s AND source_hash = %s",
                (rubric_id, digest),
            )
            if cursor.fetchone() is not None:
                cursor.execute(
                    "UPDATE rubric SET current_version_id = %s WHERE rubric_id = %s",
                    (version_id, rubric_id),
                )
                continue

            # A rubric version is immutable and auditable. Content that changed
            # without the declared version moving would make two different
            # rubrics answer to the same name, so it is refused rather than
            # written under a synthesised version.
            cursor.execute(
                "SELECT rubric_version_id, source_hash FROM rubric_version "
                "WHERE rubric_id = %s AND semver = %s",
                (rubric_id, semver),
            )
            clash = cursor.fetchone()
            if clash is not None:
                existing = dict(clash)
                raise RubricVersionConflict(
                    f"{Path(path).name}: content changed but 'version: {semver}' did not. "
                    f"Existing version {existing['rubric_version_id']} was built from "
                    f"{existing['source_hash'][:12]}, this file "
                    f"hashes to {digest[:12]}. Bump 'version' to publish a new rubric version; "
                    "prior scores keep pointing at the version they were computed under."
                )

            # Supersede what is in force and write the new version.
            cursor.execute(
                "UPDATE rubric_version SET superseded_at = now() "
                "WHERE rubric_id = %s AND superseded_at IS NULL",
                (rubric_id,),
            )
            cursor.execute(
                "INSERT INTO rubric_version (rubric_version_id, tenant_id, rubric_id, semver, "
                "source_hash, payload, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (rubric_version_id) DO NOTHING",
                (version_id, tenant, rubric_id, semver, digest,
                 json.dumps(document, sort_keys=True), "seed"),
            )
            cursor.execute(
                "UPDATE rubric SET current_version_id = %s WHERE rubric_id = %s",
                (version_id, rubric_id),
            )

            for ordinal, row in enumerate(_criterion_rows(document)):
                cursor.execute(
                    "INSERT INTO rubric_criterion (criterion_id, tenant_id, rubric_version_id, "
                    "path, kind, numeric_value, text_value, scope) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (rubric_version_id, path, scope) DO NOTHING",
                    (f"{version_id}-{ordinal:04d}", tenant, version_id, row["path"],
                     row["kind"], row["numeric_value"], row["text_value"], row["scope"]),
                )
            written += 1

    return written
