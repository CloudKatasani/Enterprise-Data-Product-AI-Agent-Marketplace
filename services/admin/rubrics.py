"""Rubric versioning through the console (M12.2).

The acceptance criterion is precise: a weight change made here re-scores the
estate and preserves prior snapshots. Both halves matter, and the second is the
harder one — a system that re-scores by updating rows in place would satisfy the
first half and destroy the evidence behind every decision it had already made.

So a change publishes a *new version*. The previous one is superseded, not
edited; every score already recorded keeps pointing at the version it was
computed under; and re-scoring writes new snapshots beside the old ones rather
than over them.

The same two rules the seeder enforces apply here, for the same reason:

* content is addressed by the hash of the payload, so publishing an unchanged
  payload is a no-op rather than a duplicate version;
* content that moved without the declared semver moving is refused, because two
  different rubrics answering to one version name makes every score computed
  under that name unreplayable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import psycopg

from services.common import audit
from services.common.db import fetch_all, fetch_one
from services.common.rubric_source import RubricVersionConflict, criterion_rows
from services.common.rubrics import Rubric, load_current

EVENT_PUBLISHED = "rubric_version.published"
ACTOR_CONSOLE = "console"

QUALITY_RUBRIC = "data_product_quality"

# How much of a content hash is shown. Not a threshold — nothing decides on it —
# but the portal carries no numeric literals and neither does a service, so the
# length of a human-readable digest is stated once with its reason: enough to
# tell two versions apart in a console, short enough to read aloud.
SHORT_DIGEST = len("0123456789ab")


class RubricUnknown(LookupError):
    """A rubric code with no row behind it."""


@dataclass(frozen=True)
class Published:
    rubric_version_id: str
    semver: str
    created: bool

    def document(self) -> dict[str, Any]:
        return {
            "rubric_version_id": self.rubric_version_id,
            "semver": self.semver,
            # False when the payload was already in force. A console that
            # reported success either way would let someone believe they had
            # changed something they had not.
            "created": self.created,
        }


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def catalog(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """Every rubric, its version in force, and how many things it decides."""
    return [
        {
            "code": row["code"],
            "description": row["description"],
            "rubric_version_id": row["rubric_version_id"],
            "semver": row["semver"],
            "effective_from": row["effective_from"].isoformat() if row["effective_from"] else None,
            "created_by": row["created_by"],
            "criteria": int(row["criteria"]),
            "versions": int(row["versions"]),
        }
        for row in fetch_all(
            connection,
            "SELECT r.code, r.description, v.rubric_version_id, v.semver, v.effective_from, "
            "       v.created_by, "
            "       (SELECT count(*) FROM rubric_criterion c "
            "         WHERE c.rubric_version_id = v.rubric_version_id) AS criteria, "
            "       (SELECT count(*) FROM rubric_version h WHERE h.rubric_id = r.rubric_id) "
            "         AS versions "
            "FROM rubric r "
            "LEFT JOIN rubric_version v ON v.rubric_version_id = r.current_version_id "
            "ORDER BY r.code",
        )
    ]


def history(connection: psycopg.Connection[Any], code: str) -> list[dict[str, Any]]:
    """Every version of one rubric, newest first, with what it was scored against.

    The usage count is what makes a supersession safe to look at: a version with
    snapshots behind it is a version that is still explaining decisions, and
    nothing here can remove it.
    """
    return [
        {
            "rubric_version_id": row["rubric_version_id"],
            "semver": row["semver"],
            "source_hash": row["source_hash"][:SHORT_DIGEST],
            "effective_from": row["effective_from"].isoformat(),
            "created_by": row["created_by"],
            "superseded_at": (
                row["superseded_at"].isoformat() if row["superseded_at"] else None
            ),
            "in_force": row["superseded_at"] is None,
            "quality_snapshots": int(row["snapshots"]),
        }
        for row in fetch_all(
            connection,
            "SELECT v.rubric_version_id, v.semver, v.source_hash, v.effective_from, "
            "       v.created_by, v.superseded_at, "
            "       (SELECT count(*) FROM quality_score_snapshot s "
            "         WHERE s.rubric_version_id = v.rubric_version_id) AS snapshots "
            "FROM rubric_version v JOIN rubric r ON r.rubric_id = v.rubric_id "
            "WHERE r.code = %s ORDER BY v.effective_from DESC",
            (code,),
        )
    ]


def payload_of(connection: psycopg.Connection[Any], code: str) -> dict[str, Any]:
    """The document behind the version in force, for the console to edit."""
    row = fetch_one(
        connection,
        "SELECT v.payload FROM rubric r "
        "JOIN rubric_version v ON v.rubric_version_id = r.current_version_id "
        "WHERE r.code = %s",
        (code,),
    )
    if row is None:
        raise RubricUnknown(code)
    payload = row["payload"]
    return payload if isinstance(payload, dict) else json.loads(payload)


def publish(
    connection: psycopg.Connection[Any],
    tenant: str,
    governance: Rubric,
    *,
    code: str,
    payload: dict[str, Any],
    actor_party_id: str | None,
) -> Published:
    """Publish an edited payload as a new version of ``code``.

    The write is one transaction: supersede, insert the version, insert its
    criteria, point the rubric at it, audit. A half-published rubric — a version
    row with no criteria — would answer every lookup with "criterion not found",
    which fails closed but fails confusingly.
    """
    rubric_row = fetch_one(
        connection, "SELECT rubric_id FROM rubric WHERE code = %s", (code,)
    )
    if rubric_row is None:
        raise RubricUnknown(code)
    rubric_id = rubric_row["rubric_id"]

    if payload.get("rubric") != code:
        raise ValueError(
            f"the payload declares rubric {payload.get('rubric')!r}; publishing under {code!r} "
            "would give one document two names"
        )
    semver = str(payload.get("version") or "")
    if not semver:
        raise ValueError("the payload declares no version")

    digest = _payload_hash(payload)
    version_id = f"RV-{tenant}-{code}-{digest[:SHORT_DIGEST]}"

    # Two publishers hash two different things: the seeder addresses the YAML
    # file it read, this addresses the payload it was handed. So an unchanged
    # rubric is recognised by comparing the *document*, not the digest — without
    # this, a round trip through the console would publish a new version of a
    # rubric nobody edited.
    current = fetch_one(
        connection,
        "SELECT v.rubric_version_id, v.payload FROM rubric r "
        "JOIN rubric_version v ON v.rubric_version_id = r.current_version_id "
        "WHERE r.rubric_id = %s",
        (rubric_id,),
    )
    if current is not None:
        held = current["payload"]
        held = held if isinstance(held, dict) else json.loads(held)
        if held == payload:
            return Published(current["rubric_version_id"], semver, created=False)

    existing = fetch_one(
        connection,
        "SELECT rubric_version_id FROM rubric_version "
        "WHERE rubric_id = %s AND source_hash = %s",
        (rubric_id, digest),
    )
    if existing is not None:
        # Nothing changed. Point at it and say so rather than writing a second
        # version of an identical document.
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE rubric SET current_version_id = %s WHERE rubric_id = %s",
                (existing["rubric_version_id"], rubric_id),
            )
        return Published(existing["rubric_version_id"], semver, created=False)

    clash = fetch_one(
        connection,
        "SELECT rubric_version_id, source_hash FROM rubric_version "
        "WHERE rubric_id = %s AND semver = %s",
        (rubric_id, semver),
    )
    if clash is not None:
        raise RubricVersionConflict(
            f"{code}: the content changed but 'version: {semver}' did not. Existing version "
            f"{clash['rubric_version_id']} was built from "
            f"{clash['source_hash'][:SHORT_DIGEST]}; this payload hashes to "
            f"{digest[:SHORT_DIGEST]}. Bump the version to publish; prior scores keep "
            "pointing at the version they were computed under."
        )

    rows = criterion_rows(payload)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE rubric_version SET superseded_at = now() "
            "WHERE rubric_id = %s AND superseded_at IS NULL",
            (rubric_id,),
        )
        cursor.execute(
            "INSERT INTO rubric_version (rubric_version_id, tenant_id, rubric_id, semver, "
            "  source_hash, payload, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (version_id, tenant, rubric_id, semver, digest,
             json.dumps(payload, sort_keys=True), actor_party_id or ACTOR_CONSOLE),
        )
        for index, row in enumerate(rows):
            cursor.execute(
                "INSERT INTO rubric_criterion (criterion_id, tenant_id, rubric_version_id, "
                "  path, kind, numeric_value, text_value, scope) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (f"RC-{version_id}-{index}", tenant, version_id, row["path"], row["kind"],
                 row["numeric_value"], row["text_value"], row["scope"]),
            )
        cursor.execute(
            "UPDATE rubric SET current_version_id = %s WHERE rubric_id = %s",
            (version_id, rubric_id),
        )

    audit.record(
        connection,
        tenant,
        governance,
        audit_id=f"AUD-{version_id}",
        event_name=EVENT_PUBLISHED,
        outcome="published",
        actor_party_id=actor_party_id,
        asset_type="rubric",
        asset_id=code,
        detail={"semver": semver, "criteria": len(rows), "source_hash": digest},
    )
    return Published(version_id, semver, created=True)


def rescore(connection: psycopg.Connection[Any], tenant: str) -> dict[str, Any]:
    """Re-score the estate under whatever is now in force.

    Snapshots are append-only, so this adds a new one per product and touches
    none of the old. The console shows the two side by side: the point of
    changing a weight is to see what it moves, and a re-score that overwrote the
    previous answer would hide exactly that.
    """
    from services.quality import engine

    rubric = load_current(connection, QUALITY_RUBRIC)
    before = fetch_one(
        connection, "SELECT count(*) AS snapshots FROM quality_score_snapshot"
    )
    products = [
        row["product_id"]
        for row in fetch_all(
            connection, "SELECT product_id FROM data_product ORDER BY product_id"
        )
    ]
    for product_id in products:
        engine.write_snapshot(
            connection, tenant, engine.score_product(connection, product_id, rubric)
        )
    after = fetch_one(
        connection, "SELECT count(*) AS snapshots FROM quality_score_snapshot"
    )
    return {
        "products_scored": len(products),
        "snapshots_before": int(before["snapshots"]) if before else 0,
        "snapshots_after": int(after["snapshots"]) if after else 0,
        "rubric_version_id": rubric.rubric_version_id,
    }
