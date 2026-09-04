"""M1.3 — rubric YAML into rubric / rubric_version / rubric_criterion.

A rubric version is immutable and content-addressed by the sha256 of the YAML
that produced it. Re-seeding unchanged YAML is a no-op; re-seeding changed YAML
supersedes the previous version and writes a new one, so prior scores keep
pointing at the rubric they were actually computed under.

Flattening into addressable criteria is
:mod:`services.common.rubric_source`, shared with the admin console so a weight
edited there and the same weight seeded from a file produce identical rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg

from scripts.seeders._base import load_directory_with_paths, source_hash
from services.common.rubric_source import RubricVersionConflict, criterion_rows

__all__ = ["RubricVersionConflict", "seed"]


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

            for ordinal, row in enumerate(criterion_rows(document)):
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
