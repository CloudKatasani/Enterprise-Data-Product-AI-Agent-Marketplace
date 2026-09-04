"""M8.1 — policy YAML into policy / policy_version.

Same discipline as rubrics: a version is immutable and content-addressed by the
sha256 of the file that produced it, and content that moved without the declared
version moving is refused rather than written under a synthesised one. Every
approval decision records the policy version in force when it was made, so a
decision can be re-read against the rules it was actually made under — which is
the only way to answer "why was this approved?" a year later.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg

from scripts.seeders._base import load_directory_with_paths, source_hash

CATEGORY = "access"


class PolicyVersionConflictError(RuntimeError):
    """Policy content moved but its declared version did not."""


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    written = 0
    for path, document in load_directory_with_paths("policies"):
        code = document["policy"]
        semver = document["version"]
        digest = source_hash(Path(path))
        policy_id = f"POL-{tenant}-{code}"
        version_id = f"PV-{tenant}-{code}-{digest[:12]}"

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO policy (policy_id, tenant_id, code, category, description) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tenant_id, code) DO UPDATE "
                "SET description = EXCLUDED.description",
                (policy_id, tenant, code, CATEGORY,
                 f"{code} policy seeded from {Path(path).name}"),
            )

            cursor.execute(
                "SELECT policy_version_id FROM policy_version "
                "WHERE policy_id = %s AND rules = %s::jsonb",
                (policy_id, json.dumps(document, sort_keys=True)),
            )
            if cursor.fetchone() is not None:
                cursor.execute(
                    "UPDATE policy SET current_version_id = %s WHERE policy_id = %s",
                    (version_id, policy_id),
                )
                continue

            cursor.execute(
                "SELECT policy_version_id FROM policy_version "
                "WHERE policy_id = %s AND semver = %s",
                (policy_id, semver),
            )
            clash = cursor.fetchone()
            if clash is not None:
                raise PolicyVersionConflictError(
                    f"{Path(path).name}: content changed but 'version: {semver}' did not. "
                    f"Existing version {dict(clash)['policy_version_id']} holds different "
                    "rules. Bump 'version' to publish a new policy version; decisions "
                    "already made keep pointing at the rules they were made under."
                )

            cursor.execute(
                "UPDATE policy_version SET superseded_at = now() "
                "WHERE policy_id = %s AND superseded_at IS NULL",
                (policy_id,),
            )
            cursor.execute(
                "INSERT INTO policy_version (policy_version_id, tenant_id, policy_id, semver, "
                "  rules, effective_from) VALUES (%s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (policy_version_id) DO NOTHING",
                (version_id, tenant, policy_id, semver,
                 json.dumps(document, sort_keys=True)),
            )
            cursor.execute(
                "UPDATE policy SET current_version_id = %s WHERE policy_id = %s",
                (version_id, policy_id),
            )
            written += 1
    return written
