"""The workflow engine. One engine, three request types (BUILD.md section 14).

Durable execution, which here means something narrow and testable: the state of
a request lives in the database and nowhere else. There is no in-memory machine
to lose. A transition reads the current state, checks the move is legal, writes
the new state and an event, and commits. A restart mid-flight leaves a request
in its last committed state with an event trail explaining how it got there, and
the next call picks up from exactly there.

Two rules the transition table enforces rather than documents:

* **A state cannot be reached except through a declared edge.** A request cannot
  become Provisioned without having been Approved, whatever code tries.
* **Every transition names an actor.** An approval with no approver is not a
  softer record of the same fact; it is an unauditable one.

The tables are the specification's diagrams, transcribed. Where the diagram and
this disagree, the diagram is right and this is a bug.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one

TYPE_ACCESS = "access"
TYPE_ENHANCEMENT = "enhancement"
TYPE_DEMAND = "demand"

# --- Access (14.1) ---------------------------------------------------------
ACCESS_DRAFT = "draft"
ACCESS_EVALUATED = "policy_evaluated"
ACCESS_SUBMITTED = "submitted"
ACCESS_APPROVED = "approved"
ACCESS_PARTIAL = "partially_approved"
ACCESS_DECLINED = "declined"
ACCESS_BLOCKED = "blocked"
ACCESS_PROVISIONED = "provisioned"
ACCESS_ACTIVE = "active"
ACCESS_RENEWED = "renewed"
ACCESS_EXPIRED = "expired"
ACCESS_REVOKED = "revoked"

# --- Enhancement (14.2) ----------------------------------------------------
ENH_SUBMITTED = "submitted"
ENH_TRIAGED = "triaged"
ENH_ASSESSED = "assessed"
ENH_ACCEPTED = "accepted"
ENH_DECLINED = "declined"
ENH_MERGED = "merged"
ENH_SCHEDULED = "scheduled"
ENH_IN_PROGRESS = "in_progress"
ENH_DELIVERED = "delivered"
ENH_VERIFIED = "verified"

# --- Demand (14.3) ---------------------------------------------------------
DEM_SUBMITTED = "submitted"
DEM_DUPLICATE_REVIEW = "duplicate_review"
DEM_TRIAGED = "triaged"
DEM_SCORED = "scored"
DEM_ROADMAPPED = "roadmapped"
DEM_IN_BUILD = "in_build"
DEM_DELIVERED = "delivered"
DEM_DECLINED = "declined"

TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {
    TYPE_ACCESS: {
        ACCESS_DRAFT: frozenset({ACCESS_EVALUATED}),
        ACCESS_EVALUATED: frozenset({ACCESS_SUBMITTED, ACCESS_BLOCKED, ACCESS_APPROVED}),
        ACCESS_SUBMITTED: frozenset(
            {ACCESS_APPROVED, ACCESS_PARTIAL, ACCESS_DECLINED, ACCESS_BLOCKED}
        ),
        ACCESS_APPROVED: frozenset({ACCESS_PROVISIONED}),
        ACCESS_PARTIAL: frozenset({ACCESS_PROVISIONED}),
        ACCESS_PROVISIONED: frozenset({ACCESS_ACTIVE}),
        ACCESS_ACTIVE: frozenset({ACCESS_RENEWED, ACCESS_EXPIRED, ACCESS_REVOKED}),
        ACCESS_RENEWED: frozenset({ACCESS_ACTIVE, ACCESS_EXPIRED, ACCESS_REVOKED}),
        # Terminal.
        ACCESS_DECLINED: frozenset(),
        ACCESS_BLOCKED: frozenset(),
        ACCESS_EXPIRED: frozenset(),
        ACCESS_REVOKED: frozenset(),
    },
    TYPE_ENHANCEMENT: {
        ENH_SUBMITTED: frozenset({ENH_TRIAGED}),
        ENH_TRIAGED: frozenset({ENH_ASSESSED}),
        ENH_ASSESSED: frozenset({ENH_ACCEPTED, ENH_DECLINED, ENH_MERGED}),
        ENH_ACCEPTED: frozenset({ENH_SCHEDULED}),
        ENH_SCHEDULED: frozenset({ENH_IN_PROGRESS}),
        ENH_IN_PROGRESS: frozenset({ENH_DELIVERED}),
        ENH_DELIVERED: frozenset({ENH_VERIFIED}),
        ENH_DECLINED: frozenset(),
        ENH_MERGED: frozenset(),
        ENH_VERIFIED: frozenset(),
    },
    TYPE_DEMAND: {
        DEM_SUBMITTED: frozenset({DEM_DUPLICATE_REVIEW, DEM_TRIAGED}),
        DEM_DUPLICATE_REVIEW: frozenset({DEM_TRIAGED, DEM_DECLINED}),
        DEM_TRIAGED: frozenset({DEM_SCORED, DEM_DECLINED}),
        DEM_SCORED: frozenset({DEM_ROADMAPPED, DEM_DECLINED}),
        DEM_ROADMAPPED: frozenset({DEM_IN_BUILD}),
        DEM_IN_BUILD: frozenset({DEM_DELIVERED}),
        DEM_DELIVERED: frozenset(),
        DEM_DECLINED: frozenset(),
    },
}

INITIAL = {
    TYPE_ACCESS: ACCESS_DRAFT,
    TYPE_ENHANCEMENT: ENH_SUBMITTED,
    TYPE_DEMAND: DEM_SUBMITTED,
}

TERMINAL = {
    workflow: frozenset(state for state, onward in table.items() if not onward)
    for workflow, table in TRANSITIONS.items()
}


class IllegalTransitionError(RuntimeError):
    """A move the state machine does not permit.

    Raised rather than tolerated. The alternative — writing the state anyway and
    trusting callers — means a request can be Provisioned without ever having
    been Approved, and no amount of downstream checking recovers from that.
    """


class WorkflowNotFoundError(LookupError):
    """No instance for this subject."""


@dataclass(frozen=True)
class Instance:
    instance_id: str
    workflow_type: str
    subject_id: str
    state: str
    payload: dict[str, Any]

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL[self.workflow_type]

    def onward(self) -> frozenset[str]:
        return TRANSITIONS[self.workflow_type][self.state]

    def document(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "workflow_type": self.workflow_type,
            "subject_id": self.subject_id,
            "state": self.state,
            "terminal": self.terminal,
            "onward": sorted(self.onward()),
            "payload": self.payload,
        }


def _instance_id(workflow_type: str, subject_id: str) -> str:
    return f"WFI-{workflow_type}-{subject_id}"


def start(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    workflow_type: str,
    subject_id: str,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> Instance:
    if workflow_type not in TRANSITIONS:
        raise IllegalTransitionError(
            f"{workflow_type!r} is not a workflow; this engine runs "
            + ", ".join(sorted(TRANSITIONS))
        )
    state = INITIAL[workflow_type]
    instance_id = _instance_id(workflow_type, subject_id)
    body = payload or {}

    connection.execute(
        "INSERT INTO workflow_instance (instance_id, tenant_id, workflow_type, subject_id, "
        "  state, payload) VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (instance_id) DO NOTHING",
        (instance_id, tenant, workflow_type, subject_id, state, json.dumps(body, default=str)),
    )
    _event(connection, tenant, instance_id, None, state, actor, {"started": True})
    return load(connection, workflow_type, subject_id)


def load(
    connection: psycopg.Connection[Any], workflow_type: str, subject_id: str
) -> Instance:
    row = fetch_one(
        connection,
        "SELECT instance_id, workflow_type, subject_id, state, payload "
        "FROM workflow_instance WHERE instance_id = %s",
        (_instance_id(workflow_type, subject_id),),
    )
    if row is None:
        raise WorkflowNotFoundError(f"no {workflow_type} workflow for {subject_id}")
    return Instance(
        instance_id=row["instance_id"],
        workflow_type=row["workflow_type"],
        subject_id=row["subject_id"],
        state=row["state"],
        payload=row["payload"],
    )


def _event(
    connection: psycopg.Connection[Any],
    tenant: str,
    instance_id: str,
    from_state: str | None,
    to_state: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    # clock_timestamp(), not now(): now() is fixed for the whole transaction, so
    # three transitions committed together would carry identical timestamps and
    # the history would read back in whatever order the ids happened to sort.
    # The history is the answer to "how did this get here", and an unordered
    # answer is not one.
    connection.execute(
        "INSERT INTO workflow_event (event_id, tenant_id, instance_id, from_state, to_state, "
        "  actor, detail, occurred_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, clock_timestamp())",
        (
            f"WFE-{instance_id}-{from_state or 'start'}-{to_state}-"
            f"{datetime.now(UTC):%Y%m%d%H%M%S%f}",
            tenant, instance_id, from_state, to_state, actor,
            json.dumps(detail, default=str),
        ),
    )


def transition(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    workflow_type: str,
    subject_id: str,
    to_state: str,
    actor: str,
    detail: dict[str, Any] | None = None,
    payload_updates: dict[str, Any] | None = None,
) -> Instance:
    """Move a request, or refuse.

    ``actor`` is required and is not defaulted. A transition whose actor is
    unknown is an unauditable record of a decision that someone did make.
    """
    if not actor:
        raise IllegalTransitionError(
            "a transition must name its actor; an unattributed decision is not recorded"
        )

    instance = load(connection, workflow_type, subject_id)
    if to_state == instance.state:
        return instance
    if to_state not in instance.onward():
        permitted = ", ".join(sorted(instance.onward())) or "nothing (it is terminal)"
        raise IllegalTransitionError(
            f"{subject_id} is {instance.state}; from there it can move to {permitted}, "
            f"not to {to_state!r}"
        )

    payload = {**instance.payload, **(payload_updates or {})}
    completed = to_state in TERMINAL[workflow_type]
    connection.execute(
        "UPDATE workflow_instance SET state = %s, payload = %s, "
        "  completed_at = CASE WHEN %s THEN now() ELSE NULL END "
        "WHERE instance_id = %s",
        (to_state, json.dumps(payload, default=str), completed, instance.instance_id),
    )
    _event(
        connection, tenant, instance.instance_id, instance.state, to_state, actor,
        detail or {},
    )
    return load(connection, workflow_type, subject_id)


def history(
    connection: psycopg.Connection[Any], workflow_type: str, subject_id: str
) -> list[dict[str, Any]]:
    """Every move, in order. This is the answer to "how did this get here?"."""
    return [
        {
            "from_state": row["from_state"],
            "to_state": row["to_state"],
            "actor": row["actor"],
            "detail": row["detail"],
            "occurred_at": row["occurred_at"],
        }
        for row in fetch_all(
            connection,
            "SELECT from_state, to_state, actor, detail, occurred_at FROM workflow_event "
            "WHERE instance_id = %s ORDER BY occurred_at, event_id",
            (_instance_id(workflow_type, subject_id),),
        )
    ]


def due(
    connection: psycopg.Connection[Any], workflow_type: str | None = None
) -> list[Instance]:
    """Instances whose timer has come round. The worker's queue."""
    rows = fetch_all(
        connection,
        "SELECT instance_id, workflow_type, subject_id, state, payload "
        "FROM workflow_instance "
        "WHERE completed_at IS NULL AND run_after <= now() "
        + ("AND workflow_type = %s " if workflow_type else "")
        + "ORDER BY run_after",
        (workflow_type,) if workflow_type else (),
    )
    return [
        Instance(
            instance_id=row["instance_id"],
            workflow_type=row["workflow_type"],
            subject_id=row["subject_id"],
            state=row["state"],
            payload=row["payload"],
        )
        for row in rows
    ]
