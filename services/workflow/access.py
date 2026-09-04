"""The access request, end to end (BUILD.md section 14.1).

Draft -> PolicyEvaluated -> Submitted -> {Approved | PartiallyApproved | Declined
       | Blocked} -> Provisioned -> Active -> {Renewed | Expired | Revoked}

Provisioning is mechanical and that is the point of it. Nobody edits a role by
hand, so there is no step where a well-meaning administrator grants a little
more than was approved, and no step where the grant and the approval can differ.
The seven steps in section 14.1 are seven statements in one transaction: if any
of them fails, none of them happened, and the request stays Approved rather than
becoming half-provisioned.

Partial approval is a first-class outcome rather than a failure. An approver who
grants four of six requested columns is doing the right thing, and the requester
is told which two were withheld and why — a partial approval with no reason is
just a decline that looks friendlier.
"""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from services.common import audit
from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric
from services.common.timing import hours_in
from services.workflow import engine, policy

ASSET_DATA_PRODUCT = "data_product"
ASSET_AGENT = "agent"

ACCESS_READ_DATA = "read_data"
ACCESS_AGENT_INVOKE = "agent_invoke"

STEP_PENDING = "pending"
STEP_APPROVED = "approved"
STEP_DECLINED = "declined"

OUTCOME_APPROVED = "approve"
OUTCOME_PARTIAL = "partial"
OUTCOME_DECLINED = "decline"
OUTCOME_BLOCKED = "block"

EVENT_PROVISIONED = "entitlement.provisioned"
EVENT_REVOKED = "entitlement.revoked"

ROLE_TEMPLATE = "MKT_{asset}_{level}"


class RequestRefusedError(RuntimeError):
    """The request cannot proceed. Carries the reason the consumer sees."""


@dataclass(frozen=True)
class Provisioned:
    """What a completed provisioning produced. Every field is checkable."""

    grant_id: str
    platform_role: str
    oauth_scopes: tuple[str, ...]
    columns: tuple[str, ...]
    purpose_code: str
    expires_at: datetime
    audit_id: str

    def document(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "platform_role": self.platform_role,
            "oauth_scopes": list(self.oauth_scopes),
            "columns": list(self.columns),
            "purpose_code": self.purpose_code,
            "expires_at": self.expires_at.isoformat(),
            "audit_id": self.audit_id,
        }


def _scope_for(asset_type: str, asset_id: str) -> str:
    return (
        f"agent:{asset_id}:invoke"
        if asset_type == ASSET_AGENT
        else f"dp:{asset_id}:read"
    )


def _access_level(asset_type: str) -> str:
    return ACCESS_AGENT_INVOKE if asset_type == ASSET_AGENT else ACCESS_READ_DATA


def _platform_role(asset_id: str, level: str) -> str:
    return ROLE_TEMPLATE.format(
        asset=asset_id.replace("-", "_"), level=level.upper()
    )


# ---------------------------------------------------------------------------
# Draft and evaluate
# ---------------------------------------------------------------------------


def create(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    request_id: str,
    requester_party_id: str,
    asset_type: str,
    asset_id: str,
    columns: list[str],
    purpose_code: str,
    purpose_text: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Draft a request and evaluate it, in one step.

    The consumer never sees a Draft that has not been evaluated: the whole
    reason evaluation runs before submission is that the form can show what will
    happen, and a form that shows nothing until you submit is the thing this
    replaces.
    """
    evaluation = policy.evaluate(
        connection,
        asset_type=asset_type,
        asset_id=asset_id,
        requester_party_id=requester_party_id,
        purpose_code=purpose_code,
    )

    connection.execute(
        "INSERT INTO request (request_id, tenant_id, request_type, state, requester_party_id, "
        "  title, body, purpose_code, purpose_text, policy_path, policy_version_id, "
        "  sla_hours, sla_due_at) "
        "VALUES (%s, %s, 'access', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (request_id) DO NOTHING",
        (
            request_id, tenant, engine.ACCESS_EVALUATED, requester_party_id,
            title or f"Access to {asset_id}", purpose_text, purpose_code, purpose_text,
            evaluation.path, evaluation.policy_version_id,
            hours_in(evaluation.sla_days), evaluation.due_at,
        ),
    )
    connection.execute(
        "INSERT INTO request_item (request_item_id, tenant_id, request_id, asset_type, "
        "  asset_id, access_level, columns_requested) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (request_item_id) DO NOTHING",
        (
            f"RQI-{request_id}-{asset_id}", tenant, request_id, asset_type, asset_id,
            _access_level(asset_type), columns,
        ),
    )

    engine.start(
        connection, tenant,
        workflow_type=engine.TYPE_ACCESS,
        subject_id=request_id,
        actor=requester_party_id,
        payload={"evaluation": evaluation.document()},
    )
    engine.transition(
        connection, tenant,
        workflow_type=engine.TYPE_ACCESS,
        subject_id=request_id,
        to_state=engine.ACCESS_EVALUATED,
        actor=requester_party_id,
        detail={"path": evaluation.path, "policy_version_id": evaluation.policy_version_id},
    )
    return {"request_id": request_id, "evaluation": evaluation.document()}


def submit(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    request_id: str,
    actor: str,
    governance: Rubric,
) -> dict[str, Any]:
    """Submit an evaluated request, building its approval chain.

    A blocked request is not submittable. That is enforced here rather than in
    the form, because the form is a client like any other.
    """
    instance = engine.load(connection, engine.TYPE_ACCESS, request_id)
    evaluation = instance.payload["evaluation"]

    if evaluation["blocked"]:
        engine.transition(
            connection, tenant, workflow_type=engine.TYPE_ACCESS, subject_id=request_id,
            to_state=engine.ACCESS_BLOCKED, actor=actor,
            detail={"reasons": evaluation["reasons"],
                    "alternatives": evaluation["alternatives"]},
        )
        _close(connection, request_id, engine.ACCESS_BLOCKED)
        raise RequestRefusedError(
            "; ".join(evaluation["reasons"])
            or "policy blocks this request"
        )

    if evaluation["automatic"]:
        # Auto-approve is still a decision and is recorded as one, with the
        # policy as its actor. "The policy approved it" is a better audit record
        # than an approval with no approver at all.
        engine.transition(
            connection, tenant, workflow_type=engine.TYPE_ACCESS, subject_id=request_id,
            to_state=engine.ACCESS_APPROVED, actor=evaluation["policy_version_id"],
            detail={"automatic": True, "reasons": evaluation["reasons"]},
        )
        provisioned = provision(
            connection, tenant, request_id=request_id, actor=evaluation["policy_version_id"],
            governance=governance,
        )
        return {"state": engine.ACCESS_ACTIVE, "provisioned": provisioned.document()}

    _build_chain(connection, tenant, request_id, evaluation)
    engine.transition(
        connection, tenant, workflow_type=engine.TYPE_ACCESS, subject_id=request_id,
        to_state=engine.ACCESS_SUBMITTED, actor=actor,
        detail={"approvers": evaluation["approvers"], "due_at": evaluation["due_at"]},
    )
    connection.execute(
        "UPDATE request SET state = %s, submitted_at = now() WHERE request_id = %s",
        (engine.ACCESS_SUBMITTED, request_id),
    )
    return {
        "state": engine.ACCESS_SUBMITTED,
        "approvers": evaluation["approvers"],
        "due_at": evaluation["due_at"],
    }


def _build_chain(
    connection: psycopg.Connection[Any],
    tenant: str,
    request_id: str,
    evaluation: dict[str, Any],
) -> None:
    """One step per approver, in order, each with its own due date.

    The chain is sequential: an approver sees a request only once the one before
    them has acted. Parallel approval reads as faster and produces approvals
    given without the context the earlier approver would have added.
    """
    due = evaluation["due_at"]
    for ordinal, role in enumerate(evaluation["approvers"], start=1):
        connection.execute(
            "INSERT INTO approval_step (step_id, tenant_id, request_id, ordinal, "
            "  approver_role, state, due_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (step_id) DO NOTHING",
            (f"APS-{request_id}-{ordinal}", tenant, request_id, ordinal, role,
             STEP_PENDING, due),
        )


def _close(connection: psycopg.Connection[Any], request_id: str, state: str) -> None:
    connection.execute(
        "UPDATE request SET state = %s, closed_at = now() WHERE request_id = %s",
        (state, request_id),
    )


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------


def decide(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    request_id: str,
    approver_party_id: str,
    outcome: str,
    reason: str,
    granted_columns: list[str] | None = None,
    governance: Rubric | None = None,
) -> dict[str, Any]:
    """Record one approver's decision and advance if the chain is complete."""
    step = fetch_one(
        connection,
        "SELECT step_id, ordinal, approver_role FROM approval_step "
        "WHERE request_id = %s AND state = %s ORDER BY ordinal LIMIT 1",
        (request_id, STEP_PENDING),
    )
    if step is None:
        raise RequestRefusedError(f"{request_id} has no approval step waiting on a decision")

    if outcome == OUTCOME_DECLINED and not reason.strip():
        raise RequestRefusedError("a decline must carry a reason the requester can read")
    if outcome == OUTCOME_PARTIAL and not reason.strip():
        # Section 14.1: partial approval requires a reason returned to the
        # requester. Without one it is a decline wearing a friendlier word.
        raise RequestRefusedError(
            "a partial approval must say which part was withheld and why"
        )

    connection.execute(
        "UPDATE approval_step SET state = %s, approver_party_id = %s, acted_at = now() "
        "WHERE step_id = %s",
        (STEP_APPROVED if outcome != OUTCOME_DECLINED else STEP_DECLINED,
         approver_party_id, step["step_id"]),
    )

    if outcome == OUTCOME_DECLINED:
        engine.transition(
            connection, tenant, workflow_type=engine.TYPE_ACCESS, subject_id=request_id,
            to_state=engine.ACCESS_DECLINED, actor=approver_party_id,
            detail={"role": step["approver_role"], "reason": reason},
        )
        _close(connection, request_id, engine.ACCESS_DECLINED)
        return {"state": engine.ACCESS_DECLINED, "reason": reason}

    if granted_columns is not None:
        connection.execute(
            "UPDATE request_item SET columns_requested = %s, outcome = %s, "
            "  outcome_reason = %s WHERE request_id = %s",
            (granted_columns, outcome, reason, request_id),
        )

    remaining = fetch_one(
        connection,
        "SELECT count(*) AS n FROM approval_step WHERE request_id = %s AND state = %s",
        (request_id, STEP_PENDING),
    )
    if remaining and int(remaining["n"]) > 0:
        return {"state": engine.ACCESS_SUBMITTED, "waiting_on": int(remaining["n"])}

    final = engine.ACCESS_PARTIAL if outcome == OUTCOME_PARTIAL else engine.ACCESS_APPROVED
    engine.transition(
        connection, tenant, workflow_type=engine.TYPE_ACCESS, subject_id=request_id,
        to_state=final, actor=approver_party_id,
        detail={"role": step["approver_role"], "reason": reason, "outcome": outcome},
    )
    if governance is None:
        return {"state": final}
    provisioned = provision(
        connection, tenant, request_id=request_id, actor=approver_party_id,
        governance=governance,
    )
    return {"state": engine.ACCESS_ACTIVE, "provisioned": provisioned.document()}


# ---------------------------------------------------------------------------
# Provisioning — the seven mechanical steps
# ---------------------------------------------------------------------------


def provision(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    request_id: str,
    actor: str,
    governance: Rubric,
) -> Provisioned:
    """Section 14.1's seven steps, as one transaction.

    1 resolve the platform role, 2 grant it, 3 apply masking and row policy,
    4 bind purpose and expiry, 5 issue OAuth scopes, 6 notify, 7 audit.

    Steps 2 and 3 are the connector's, and in this deployment the connector is
    read-only by construction (I8), so what is written here is the register the
    platform provisioner reads — never a direct grant issued from application
    code. The distinction matters: an application that can grant itself access
    is not governed by the register, it is merely described by it.
    """
    item = fetch_one(
        connection,
        "SELECT asset_type, asset_id, access_level, columns_requested FROM request_item "
        "WHERE request_id = %s",
        (request_id,),
    )
    header = fetch_one(
        connection,
        "SELECT requester_party_id, purpose_code, purpose_text, policy_version_id "
        "FROM request WHERE request_id = %s",
        (request_id,),
    )
    if item is None or header is None:
        raise RequestRefusedError(f"{request_id} has nothing to provision")

    rules = policy.load_rules(connection)[1]
    duration = int(rules["grant"]["duration_days"])
    expires = datetime.now(UTC) + timedelta(days=duration)

    grant_id = f"GRT-{header['requester_party_id']}-{item['asset_id']}"
    role = _platform_role(item["asset_id"], item["access_level"])
    scopes = (_scope_for(item["asset_type"], item["asset_id"]),)

    connection.execute(
        "INSERT INTO entitlement_grant (grant_id, tenant_id, request_id, principal_id, "
        "  asset_type, asset_id, access_level, purpose_code, purpose_text, platform_role, "
        "  oauth_scopes, granted_at, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s) "
        "ON CONFLICT (grant_id) DO NOTHING",
        (
            grant_id, tenant, request_id, header["requester_party_id"], item["asset_type"],
            item["asset_id"], item["access_level"], header["purpose_code"],
            header["purpose_text"], role, list(scopes), expires,
        ),
    )
    connection.execute(
        "INSERT INTO grant_scope (scope_id, tenant_id, grant_id, scope_kind, expression, "
        "  applied_in_platform) VALUES (%s, %s, %s, 'columns', %s, false) "
        "ON CONFLICT (scope_id) DO NOTHING",
        (f"SCP-{grant_id}-COLS", tenant, grant_id,
         ",".join(item["columns_requested"] or ())),
    )

    audit_id = audit.record(
        connection, tenant, governance,
        audit_id=f"AUD-PROV-{grant_id}-{datetime.now(UTC):%Y%m%d%H%M%S}",
        event_name=EVENT_PROVISIONED,
        outcome=OUTCOME_APPROVED,
        actor_party_id=actor if actor.startswith("PTY-") else None,
        on_behalf_of=header["requester_party_id"],
        asset_type=item["asset_type"],
        asset_id=item["asset_id"],
        purpose_code=header["purpose_code"],
        detail={
            "request_id": request_id,
            "grant_id": grant_id,
            "platform_role": role,
            "oauth_scopes": list(scopes),
            "columns": list(item["columns_requested"] or ()),
            "expires_at": expires,
            "policy_version_id": header["policy_version_id"],
            "decided_by": actor,
        },
    )

    engine.transition(
        connection, tenant, workflow_type=engine.TYPE_ACCESS, subject_id=request_id,
        to_state=engine.ACCESS_PROVISIONED, actor=actor,
        detail={"grant_id": grant_id, "platform_role": role},
    )
    engine.transition(
        connection, tenant, workflow_type=engine.TYPE_ACCESS, subject_id=request_id,
        to_state=engine.ACCESS_ACTIVE, actor=actor,
        detail={"expires_at": expires.isoformat()},
    )
    _close(connection, request_id, engine.ACCESS_ACTIVE)

    return Provisioned(
        grant_id=grant_id,
        platform_role=role,
        oauth_scopes=scopes,
        columns=tuple(item["columns_requested"] or ()),
        purpose_code=header["purpose_code"],
        expires_at=expires,
        audit_id=audit_id,
    )


# ---------------------------------------------------------------------------
# The clocks
# ---------------------------------------------------------------------------


def expiring(connection: psycopg.Connection[Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
    """Grants inside the renewal notice window."""
    days = int(rules["grant"]["renewal_notice_days"])
    return fetch_all(
        connection,
        "SELECT grant_id, principal_id, asset_id, expires_at FROM entitlement_grant "
        "WHERE revoked_at IS NULL AND expires_at > now() "
        "  AND expires_at <= now() + %s::interval ORDER BY expires_at",
        (f"{days} days",),
    )


def expired(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        "SELECT grant_id, principal_id, asset_id, expires_at FROM entitlement_grant "
        "WHERE revoked_at IS NULL AND expires_at <= now() ORDER BY expires_at",
    )


def dormant(connection: psycopg.Connection[Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
    """Live grants nobody has used, flagged to whoever approved them.

    A grant that has never been used is the cheapest access to take back and the
    most likely to be forgotten, which is exactly the combination that makes an
    estate accumulate standing access nobody can account for.
    """
    days = int(rules["grant"]["dormant_after_days"])
    return fetch_all(
        connection,
        "SELECT g.grant_id, g.principal_id, g.asset_id, g.granted_at, g.last_used_at, "
        "       s.approver_party_id AS approved_by "
        "FROM entitlement_grant g "
        "LEFT JOIN approval_step s ON s.request_id = g.request_id AND s.ordinal = 1 "
        "WHERE g.revoked_at IS NULL AND g.expires_at > now() "
        "  AND coalesce(g.last_used_at, g.granted_at) <= now() - %s::interval "
        "ORDER BY coalesce(g.last_used_at, g.granted_at)",
        (f"{days} days",),
    )


def revoke(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    grant_id: str,
    actor: str,
    reason: str,
    governance: Rubric,
) -> dict[str, Any]:
    """Revoke a grant, keeping the audit record.

    Revocation writes ``revoked_at`` rather than deleting the row: the question
    "who had access to this last March" has to stay answerable.
    """
    grant = fetch_one(
        connection,
        "SELECT request_id, principal_id, asset_type, asset_id, purpose_code "
        "FROM entitlement_grant WHERE grant_id = %s AND revoked_at IS NULL",
        (grant_id,),
    )
    if grant is None:
        raise RequestRefusedError(f"no live grant {grant_id}")

    connection.execute(
        "UPDATE entitlement_grant SET revoked_at = now(), revocation_reason = %s "
        "WHERE grant_id = %s",
        (reason, grant_id),
    )
    audit_id = audit.record(
        connection, tenant, governance,
        audit_id=f"AUD-REV-{grant_id}-{datetime.now(UTC):%Y%m%d%H%M%S}",
        event_name=EVENT_REVOKED,
        outcome="revoked",
        actor_party_id=actor if actor.startswith("PTY-") else None,
        on_behalf_of=grant["principal_id"],
        asset_type=grant["asset_type"],
        asset_id=grant["asset_id"],
        purpose_code=grant["purpose_code"],
        detail={"grant_id": grant_id, "reason": reason},
    )
    if grant["request_id"]:
        # A grant seeded without a workflow, or one already terminal, has no
        # transition to make. The revocation itself is what matters and it is
        # recorded above; the workflow move is bookkeeping on top of it.
        with suppress(engine.WorkflowNotFoundError, engine.IllegalTransitionError):
            engine.transition(
                connection, tenant, workflow_type=engine.TYPE_ACCESS,
                subject_id=grant["request_id"], to_state=engine.ACCESS_REVOKED,
                actor=actor, detail={"grant_id": grant_id, "reason": reason},
            )
    return {"grant_id": grant_id, "revoked": True, "audit_id": audit_id}


def register(
    connection: psycopg.Connection[Any], *, principal_id: str | None = None
) -> list[dict[str, Any]]:
    """The entitlement register (M8.5): who holds what, for what, until when."""
    where = "WHERE g.principal_id = %s" if principal_id else ""
    rows = fetch_all(
        connection,
        "SELECT g.grant_id, g.principal_id, p.display_name, g.asset_type, g.asset_id, "
        "       g.access_level, g.purpose_code, g.purpose_text, g.platform_role, "
        "       g.oauth_scopes, g.granted_at, g.expires_at, g.revoked_at, g.last_used_at, "
        "       (SELECT s.expression FROM grant_scope s WHERE s.grant_id = g.grant_id "
        "        AND s.scope_kind = 'columns') AS columns "
        "FROM entitlement_grant g LEFT JOIN party p ON p.party_id = g.principal_id "
        f"{where} ORDER BY g.granted_at DESC, g.grant_id",
        (principal_id,) if principal_id else (),
    )
    return [
        {
            **row,
            "columns": [c for c in (row["columns"] or "").split(",") if c],
            "live": row["revoked_at"] is None,
        }
        for row in rows
    ]


def audit_export(
    connection: psycopg.Connection[Any], *, event_names: list[str] | None = None
) -> str:
    """The audit trail as newline-delimited JSON (M8.5).

    NDJSON rather than a spreadsheet: an auditor's first question is usually
    "give me everything" and their second is a filter, and a format that streams
    answers both without a size limit.
    """
    rows = fetch_all(
        connection,
        "SELECT audit_id, event_name, actor_party_id, on_behalf_of, asset_type, asset_id, "
        "       purpose_code, outcome, detail, policy_version_id, occurred_at, retain_until "
        "FROM audit_event "
        + ("WHERE event_name = ANY(%s) " if event_names else "")
        + "ORDER BY occurred_at, audit_id",
        (event_names,) if event_names else (),
    )
    return "\n".join(json.dumps(row, default=str, sort_keys=True) for row in rows)
