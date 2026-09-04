"""Feedback on an answer, and what it becomes.

Acceptance is counted. Rejection does more than that: a rejection with a reason
that describes a *behaviour* — a wrong number, the wrong scope, stale data —
becomes an evaluation case, so the next run of the suites asks the question that
went wrong. That is the loop the marketplace is built around; without it,
feedback is a satisfaction score and nothing improves.

Reasons that describe a preference rather than a defect ("unclear", "other") are
recorded but not promoted. Promoting them would fill the corpus with cases that
have no correct answer, and a corpus like that stops being evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg

from services.common.db import fetch_one
from services.common.problem import bad_request, not_found

# The reason codes the schema permits, split by whether a case can be authored
# from them. A defect names something checkable; a preference does not.
DEFECT_REASONS = frozenset({"wrong_number", "wrong_scope", "missing_context", "stale_data"})
PREFERENCE_REASONS = frozenset({"correct", "useful_partial", "unclear", "other"})
REASONS = DEFECT_REASONS | PREFERENCE_REASONS

# Which suite a promoted case belongs to. A wrong number is a groundedness or
# accuracy problem; a wrong scope is a boundary problem.
SUITE_FOR_REASON = {
    "wrong_number": "golden_accuracy",
    "stale_data": "golden_accuracy",
    "missing_context": "golden_accuracy",
    "wrong_scope": "boundary_refusal",
}
ORIGIN_FEEDBACK = "feedback"


@dataclass(frozen=True)
class Recorded:
    feedback_id: str
    accepted: bool
    promoted_case_id: str | None

    def document(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "accepted": self.accepted,
            "promoted_case_id": self.promoted_case_id,
            "promoted": self.promoted_case_id is not None,
        }


def record(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    agent_id: str,
    interaction_id: str,
    party_id: str,
    accepted: bool,
    reason_code: str,
    reason_text: str | None = None,
) -> Recorded:
    if reason_code not in REASONS:
        raise bad_request(
            f"{reason_code!r} is not a reason code; use one of "
            + ", ".join(sorted(REASONS)),
            reason_code=reason_code,
        )

    interaction = fetch_one(
        connection,
        "SELECT i.interaction_id, i.question, v.agent_id FROM agent_interaction i "
        "JOIN agent_version v ON v.agent_version_id = i.agent_version_id "
        "WHERE i.interaction_id = %s",
        (interaction_id,),
    )
    if interaction is None or interaction["agent_id"] != agent_id:
        raise not_found("interaction", interaction_id)

    stamp = f"{datetime.now(UTC):%Y%m%d%H%M%S}"
    case_id = None
    if not accepted and reason_code in DEFECT_REASONS:
        case_id = f"CASE-FB-{interaction_id}-{stamp}"
        connection.execute(
            "INSERT INTO evaluation_case (case_id, tenant_id, agent_id, suite, question, "
            "  expected_behaviour, expected_payload, blocking, origin) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, true, %s) "
            "ON CONFLICT (case_id) DO NOTHING",
            (
                case_id, tenant, agent_id, SUITE_FOR_REASON[reason_code],
                interaction["question"],
                reason_text or f"a consumer rejected this answer as {reason_code}",
                json.dumps({"reason_code": reason_code, "from_interaction": interaction_id}),
                ORIGIN_FEEDBACK,
            ),
        )

    feedback_id = f"FBK-{interaction_id}-{party_id}"
    connection.execute(
        "INSERT INTO answer_feedback (feedback_id, tenant_id, interaction_id, party_id, "
        "  accepted, reason_code, reason_text, promoted_case_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (interaction_id, party_id) DO UPDATE SET "
        "  accepted = EXCLUDED.accepted, reason_code = EXCLUDED.reason_code, "
        "  reason_text = EXCLUDED.reason_text, "
        "  promoted_case_id = coalesce(answer_feedback.promoted_case_id, "
        "                              EXCLUDED.promoted_case_id)",
        (feedback_id, tenant, interaction_id, party_id, accepted, reason_code, reason_text,
         case_id),
    )
    return Recorded(feedback_id=feedback_id, accepted=accepted, promoted_case_id=case_id)
