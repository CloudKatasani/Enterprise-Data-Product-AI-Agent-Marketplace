"""Paths, modules, enrolment and the certification that follows.

The module body is read from the manifest it was seeded from rather than stored
a second time. One copy of every sentence means the database and the manifest
cannot disagree about what the estate teaches — and re-seeding after an edit
changes an index rather than migrating content.

Progress is per party. Assessment results are append-only: an attempt that
failed is part of the record, because a certification earned on a fourth attempt
and one earned on a first are the same certificate and not the same evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import yaml

from services.common.config import REPO_ROOT
from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric

STATE_ENROLLED = "enrolled"
STATE_COMPLETED = "completed"

PASS_SCORE_PATH = "assessment.pass_score_pct"
ATTEMPTS_PATH = "assessment.attempts_before_review"
VALID_DAYS_PATH = "certification.valid_days"
RENEWAL_PATH = "certification.renewal_notice_days"
COMPLETION_PATH = "certification.completion_fraction"

ZERO = Decimal(0)


class ModuleNotFound(LookupError):
    """A module id with no manifest behind it."""


class PathNotFound(LookupError):
    """A path id nobody has seeded."""


@dataclass(frozen=True)
class Module:
    module_id: str
    title: str
    summary: str
    estimated_minutes: int
    sandbox_tier: str | None
    asset_type: str | None
    asset_id: str | None
    sort_order: int

    def document(self, body: str | None = None) -> dict[str, Any]:
        payload = {
            "module_id": self.module_id,
            "title": self.title,
            "summary": self.summary,
            "estimated_minutes": self.estimated_minutes,
            "sandbox_tier": self.sandbox_tier,
            "asset_type": self.asset_type,
            "asset_id": self.asset_id,
        }
        if body is not None:
            payload["body"] = body
        return payload


def _module_from(row: dict[str, Any]) -> Module:
    return Module(
        module_id=row["module_id"],
        title=row["title"],
        summary=row["summary"],
        estimated_minutes=int(row["estimated_minutes"]),
        sandbox_tier=row["sandbox_tier"],
        asset_type=row["asset_type"],
        asset_id=row["asset_id"],
        sort_order=int(row["sort_order"]),
    )


def body_of(connection: psycopg.Connection[Any], module_id: str) -> str:
    """Resolve a module's body from the manifest it was seeded from."""
    row = fetch_one(
        connection, "SELECT body_ref FROM academy_module WHERE module_id = %s", (module_id,)
    )
    if row is None:
        raise ModuleNotFound(module_id)

    reference = str(row["body_ref"])
    relative, _, wanted = reference.partition("#")
    document = yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))
    for module in document["spec"]["modules"]:
        if module["module_id"] == wanted:
            return str(module["body"])
    raise ModuleNotFound(reference)


def paths(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    rows = fetch_all(
        connection,
        "SELECT path_id, title, persona, summary, module_ids, certification_code "
        "FROM learning_path ORDER BY path_id",
    )
    modules = {
        row["module_id"]: _module_from(row)
        for row in fetch_all(connection, "SELECT * FROM academy_module")
    }
    return [
        {
            "path_id": row["path_id"],
            "title": row["title"],
            "persona": row["persona"],
            "summary": row["summary"],
            "certification_code": row["certification_code"],
            "modules": [
                modules[module_id].document()
                for module_id in row["module_ids"]
                if module_id in modules
            ],
            "estimated_minutes": sum(
                modules[module_id].estimated_minutes
                for module_id in row["module_ids"]
                if module_id in modules
            ),
        }
        for row in rows
    ]


def path(connection: psycopg.Connection[Any], path_id: str) -> dict[str, Any]:
    for candidate in paths(connection):
        if candidate["path_id"] == path_id:
            return candidate
    raise PathNotFound(path_id)


# The path that teaches an asset class. A listing links to this one, not to the
# whole academy: a consumer looking at a data product wants the six modules
# about consuming data products, and eleven modules spanning two paths is a
# reading list rather than an answer.
PATH_FOR_ASSET = {"data_product": "LP-CONSUME", "agent": "LP-AGENTS"}


def contextual(
    connection: psycopg.Connection[Any], asset_type: str, asset_id: str
) -> list[dict[str, Any]]:
    """The modules a consumer of this asset should read (section 20.2).

    A module bound to this specific asset comes first, then the asset class's
    own path in order — a consumer meeting their first data product needs the
    class before the instance.
    """
    path_id = PATH_FOR_ASSET.get(asset_type)
    if path_id is None:
        return []

    modules = {
        row["module_id"]: _module_from(row)
        for row in fetch_all(connection, "SELECT * FROM academy_module")
    }
    specific = [
        module.document()
        for module in sorted(modules.values(), key=lambda item: item.sort_order)
        if module.asset_type == asset_type and module.asset_id == asset_id
    ]
    named = {entry["module_id"] for entry in specific}
    ordered = [entry["module_id"] for entry in path(connection, path_id)["modules"]]
    return specific + [
        modules[module_id].document()
        for module_id in ordered
        if module_id in modules and module_id not in named
    ]


# ---------------------------------------------------------------------------
# Enrolment and progress
# ---------------------------------------------------------------------------


def enrol(
    connection: psycopg.Connection[Any], tenant: str, *, party_id: str, path_id: str
) -> dict[str, Any]:
    """Enrol a party, or return the enrolment they already have.

    Idempotent on purpose: a second click on Start should not lose the progress
    behind the first.
    """
    known = path(connection, path_id)
    enrollment_id = f"ENR-{path_id}-{party_id}"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO enrollment (enrollment_id, tenant_id, path_id, party_id, state, "
            "  completed_module_ids, enrolled_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (enrollment_id) DO NOTHING",
            (enrollment_id, tenant, path_id, party_id, STATE_ENROLLED, []),
        )
    return progress(connection, party_id=party_id, path_id=known["path_id"])


def progress(
    connection: psycopg.Connection[Any], *, party_id: str, path_id: str
) -> dict[str, Any]:
    known = path(connection, path_id)
    row = fetch_one(
        connection,
        "SELECT enrollment_id, state, completed_module_ids, enrolled_at, completed_at "
        "FROM enrollment WHERE path_id = %s AND party_id = %s",
        (path_id, party_id),
    )
    completed = list(row["completed_module_ids"]) if row else []
    total = len(known["modules"])
    return {
        "path_id": path_id,
        "party_id": party_id,
        "enrolled": row is not None,
        "state": row["state"] if row else None,
        "completed_module_ids": completed,
        "completed": len(completed),
        "total": total,
        "certification_code": known["certification_code"],
    }


def record_assessment(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    party_id: str,
    path_id: str,
    module_id: str,
    score_pct: Decimal,
) -> dict[str, Any]:
    """Record one attempt and, if the path is now complete, issue the certificate.

    Attempts are append-only. A pass on the fourth try and a pass on the first
    are the same certificate and not the same evidence, and only one of those
    facts survives if a failed attempt can be overwritten.
    """
    pass_score = Decimal(str(rubric.number(PASS_SCORE_PATH)))
    passed = score_pct >= pass_score
    enrollment = fetch_one(
        connection,
        "SELECT enrollment_id, completed_module_ids FROM enrollment "
        "WHERE path_id = %s AND party_id = %s",
        (path_id, party_id),
    )
    if enrollment is None:
        enrol(connection, tenant, party_id=party_id, path_id=path_id)
        enrollment = fetch_one(
            connection,
            "SELECT enrollment_id, completed_module_ids FROM enrollment "
            "WHERE path_id = %s AND party_id = %s",
            (path_id, party_id),
        )
    assert enrollment is not None

    stamp = datetime.now(UTC)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO assessment_result (result_id, tenant_id, enrollment_id, module_id, "
            "  score_pct, passed, rubric_version_id, attempted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                f"ASR-{enrollment['enrollment_id']}-{module_id}-{stamp:%Y%m%d%H%M%S%f}",
                tenant,
                enrollment["enrollment_id"],
                module_id,
                score_pct,
                passed,
                rubric.rubric_version_id,
                stamp,
            ),
        )
        if passed:
            cursor.execute(
                "UPDATE enrollment SET completed_module_ids = ("
                "  SELECT array_agg(DISTINCT m ORDER BY m) FROM unnest("
                "    completed_module_ids || %s::text[]) AS m) "
                "WHERE enrollment_id = %s",
                ([module_id], enrollment["enrollment_id"]),
            )

    state = progress(connection, party_id=party_id, path_id=path_id)
    certificate = None
    if state["total"] and _complete(state, rubric):
        certificate = _certify(connection, tenant, rubric, party_id=party_id, path_id=path_id)
    return {
        "module_id": module_id,
        "score_pct": float(score_pct),
        "pass_score_pct": float(pass_score),
        "passed": passed,
        "attempts": _attempts(connection, enrollment["enrollment_id"], module_id),
        "attempts_before_review": int(rubric.number(ATTEMPTS_PATH)),
        "progress": state,
        "certification": certificate,
        "rubric_version_id": rubric.rubric_version_id,
    }


def _attempts(connection: psycopg.Connection[Any], enrollment_id: str, module_id: str) -> int:
    row = fetch_one(
        connection,
        "SELECT count(*) AS attempts FROM assessment_result "
        "WHERE enrollment_id = %s AND module_id = %s",
        (enrollment_id, module_id),
    )
    return int(row["attempts"]) if row else 0


def _complete(state: dict[str, Any], rubric: Rubric) -> bool:
    fraction = Decimal(str(rubric.number(COMPLETION_PATH)))
    return Decimal(state["completed"]) >= Decimal(state["total"]) * fraction


def _certify(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    party_id: str,
    path_id: str,
) -> dict[str, Any]:
    known = path(connection, path_id)
    code = known["certification_code"]
    valid_days = int(rubric.number(VALID_DAYS_PATH))
    issued = datetime.now(UTC)
    expires = issued + timedelta(days=valid_days)

    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO certification (certification_id, tenant_id, code, party_id, path_id, "
            "  issued_at, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (certification_id) DO NOTHING",
            (f"CRT-{code}-{party_id}", tenant, code, party_id, path_id, issued, expires),
        )
        cursor.execute(
            "UPDATE enrollment SET state = %s, completed_at = now() "
            "WHERE path_id = %s AND party_id = %s AND state <> %s",
            (STATE_COMPLETED, path_id, party_id, STATE_COMPLETED),
        )
    return {
        "code": code,
        "path_id": path_id,
        "issued_at": issued.isoformat(),
        "expires_at": expires.isoformat(),
        "renewal_notice_days": int(rubric.number(RENEWAL_PATH)),
    }


def held(connection: psycopg.Connection[Any], party_id: str) -> list[dict[str, Any]]:
    """Live certifications for a party. An expired one is not a certification."""
    return [
        {
            "code": row["code"],
            "path_id": row["path_id"],
            "issued_at": row["issued_at"].isoformat(),
            "expires_at": row["expires_at"].isoformat(),
        }
        for row in fetch_all(
            connection,
            "SELECT code, path_id, issued_at, expires_at FROM certification "
            "WHERE party_id = %s AND revoked_at IS NULL AND expires_at > now() "
            "ORDER BY code",
            (party_id,),
        )
    ]
