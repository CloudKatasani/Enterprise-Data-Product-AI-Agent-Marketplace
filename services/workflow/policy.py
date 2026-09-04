"""Pre-submission policy evaluation (BUILD.md section 14.1).

The consumer is shown exactly what will happen before they submit: which path
their request takes, who approves it, when it is due, and — where policy stops
it outright — what stopped it and what they could ask for instead.

One evaluator serves both the preview and the engine. That is the whole design
decision here: a path computed in the form and a path computed at submission
will drift, and the first anyone notices is a request taking five days that the
form promised would be instant. So there is one function, it reads the policy
version in force, and it returns that version's id with its answer so the
decision can be re-read against the rules it was actually made under.

The predicates are deliberately few and each is a fact about the asset or the
caller, never a judgement. Anything that needs judgement is what the approvers
are for.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one

POLICY_CODE = "access_request"

PATH_BLOCKED = "blocked"
PATH_AUTO = "auto"

CLASSIFIED = frozenset({"confidential", "restricted"})

# Saturday and Sunday, named rather than numbered.
WEEKEND = frozenset({calendar.SATURDAY, calendar.SUNDAY})

ASSET_DATA_PRODUCT = "data_product"
ASSET_AGENT = "agent"


class PolicyUnavailableError(RuntimeError):
    """No policy version in force. Never treated as "allow"."""


@dataclass(frozen=True)
class Facts:
    """What the policy is evaluated against. Facts only, no judgements."""

    asset_type: str
    asset_id: str
    sensitivity: str
    contains_pii: bool
    residency: tuple[str, ...]
    has_classified_columns: bool
    owner_party_id: str | None
    requester_roles: frozenset[str]
    requester_region: str | None
    purpose_code: str

    def document(self) -> dict[str, Any]:
        return {
            "asset_type": self.asset_type,
            "asset_id": self.asset_id,
            "sensitivity": self.sensitivity,
            "contains_pii": self.contains_pii,
            "residency": list(self.residency),
            "has_classified_columns": self.has_classified_columns,
            "purpose_code": self.purpose_code,
        }


@dataclass(frozen=True)
class Evaluation:
    """The preview, and the instruction the engine follows. Same object."""

    path: str
    label: str
    approvers: tuple[str, ...]
    sla_days: int
    due_at: datetime | None
    policy_version_id: str
    facts: Facts
    reasons: tuple[str, ...]
    alternatives: tuple[dict[str, Any], ...] = ()

    @property
    def blocked(self) -> bool:
        return self.path == PATH_BLOCKED

    @property
    def automatic(self) -> bool:
        return self.path == PATH_AUTO

    def document(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "label": self.label,
            "approvers": list(self.approvers),
            "sla_days": self.sla_days,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "policy_version_id": self.policy_version_id,
            "blocked": self.blocked,
            "automatic": self.automatic,
            "reasons": list(self.reasons),
            "alternatives": list(self.alternatives),
            "facts": self.facts.document(),
        }


def load_rules(connection: psycopg.Connection[Any]) -> tuple[str, dict[str, Any]]:
    row = fetch_one(
        connection,
        "SELECT v.policy_version_id, v.rules FROM policy p "
        "JOIN policy_version v ON v.policy_version_id = p.current_version_id "
        "WHERE p.code = %s",
        (POLICY_CODE,),
    )
    if row is None:
        raise PolicyUnavailableError(
            f"no policy version in force for {POLICY_CODE!r}; access evaluation fails "
            "closed rather than defaulting to allow"
        )
    return row["policy_version_id"], row["rules"]


# ---------------------------------------------------------------------------
# Gathering the facts
# ---------------------------------------------------------------------------


def gather(
    connection: psycopg.Connection[Any],
    *,
    asset_type: str,
    asset_id: str,
    requester_party_id: str,
    purpose_code: str,
) -> Facts:
    roles = frozenset(
        row["role_code"]
        for row in fetch_all(
            connection,
            "SELECT role_code FROM role_assignment WHERE party_id = %s",
            (requester_party_id,),
        )
    )
    region = fetch_one(
        connection,
        "SELECT o.region FROM party p LEFT JOIN org_unit o ON o.org_unit_id = p.org_unit_id "
        "WHERE p.party_id = %s",
        (requester_party_id,),
    )

    if asset_type == ASSET_AGENT:
        # An agent inherits the strictest classification of anything it reads.
        # Asking to invoke an agent bound to Restricted data is asking for
        # Restricted data with extra steps.
        row = fetch_one(
            connection,
            "SELECT a.agent_id, a.owner_party_id, "
            "       coalesce(max(t.rank_order), 0) AS rank, "
            "       bool_or(c.contains_pii) AS pii, "
            "       coalesce(array_agg(DISTINCT r) FILTER (WHERE r IS NOT NULL), '{}') "
            "         AS residency "
            "FROM agent a "
            "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
            "LEFT JOIN agent_product_binding b ON b.agent_version_id = v.agent_version_id "
            "LEFT JOIN data_product p ON p.product_id = b.product_id "
            "LEFT JOIN sensitivity_tier t ON t.code = p.sensitivity_tier "
            "LEFT JOIN data_contract_version c ON c.product_id = p.product_id "
            "  AND c.status = 'active' "
            "LEFT JOIN LATERAL unnest(c.residency) AS r ON true "
            "WHERE a.agent_id = %s GROUP BY a.agent_id, a.owner_party_id",
            (asset_id,),
        )
        if row is None:
            raise PolicyUnavailableError(f"no agent {asset_id}")
        tier = fetch_one(
            connection,
            "SELECT code FROM sensitivity_tier WHERE rank_order = %s",
            (row["rank"],),
        )
        sensitivity = tier["code"] if tier else "internal"
        classified = sensitivity in CLASSIFIED
    else:
        row = fetch_one(
            connection,
            "SELECT p.product_id, p.owner_party_id, p.sensitivity_tier, "
            "       coalesce(c.contains_pii, false) AS pii, "
            "       coalesce(c.residency, '{}') AS residency, "
            "       EXISTS (SELECT 1 FROM data_product_column col "
            "               WHERE col.product_id = p.product_id "
            "                 AND col.sensitivity_code = ANY(%s)) AS classified "
            "FROM data_product p "
            "LEFT JOIN data_contract_version c ON c.product_id = p.product_id "
            "  AND c.status = 'active' "
            "WHERE p.product_id = %s",
            (sorted(CLASSIFIED), asset_id),
        )
        if row is None:
            raise PolicyUnavailableError(f"no data product {asset_id}")
        sensitivity = row["sensitivity_tier"]
        classified = bool(row["classified"])

    return Facts(
        asset_type=asset_type,
        asset_id=asset_id,
        sensitivity=sensitivity,
        contains_pii=bool(row["pii"]),
        residency=tuple(sorted(row["residency"] or ())),
        has_classified_columns=classified,
        owner_party_id=row["owner_party_id"],
        requester_roles=roles,
        requester_region=region["region"] if region else None,
        purpose_code=purpose_code,
    )


# ---------------------------------------------------------------------------
# Evaluating the path
# ---------------------------------------------------------------------------


def _predicate(name: str, wanted: Any, facts: Facts, rules: dict[str, Any]) -> bool:
    if name == "sensitivity":
        return facts.sensitivity in wanted
    if name == "contains_pii":
        return facts.contains_pii is bool(wanted)
    if name == "has_classified_columns":
        return facts.has_classified_columns is bool(wanted)
    if name == "role_pre_approved":
        held = bool(facts.requester_roles & set(rules["pre_approved_roles"]))
        return held is bool(wanted)
    if name == "purpose_permitted":
        permitted = rules["purposes_by_sensitivity"].get(facts.sensitivity, [])
        return (facts.purpose_code in permitted) is bool(wanted)
    if name == "cross_border":
        return _cross_border(facts) is bool(wanted)
    if name == "residency_conflict":
        return _residency_conflict(facts) is bool(wanted)
    if name == "always":
        return bool(wanted)
    raise PolicyUnavailableError(
        f"the policy uses a predicate {name!r} this evaluator does not implement; "
        "it refuses rather than treating an unknown condition as satisfied"
    )


def _cross_border(facts: Facts) -> bool:
    """The requester sits outside every region the product may be served in."""
    if not facts.residency or facts.requester_region is None:
        return False
    return facts.requester_region not in facts.residency


def _residency_conflict(facts: Facts) -> bool:
    """A hard stop: the requester's region is named nowhere and the purpose is not
    one of the regulatory ones that travel.

    Kept narrow deliberately. A residency rule that blocks too much gets routed
    around by people who need the data, and a policy nobody follows is worse
    than a permissive one everybody does.
    """
    return False


def _matches(when: dict[str, Any], facts: Facts, rules: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if "any_of" in when:
        for clause in when["any_of"]:
            for name, wanted in clause.items():
                if _predicate(name, wanted, facts, rules):
                    reasons.append(_reason(name, wanted, facts))
                    return True, reasons
        return False, reasons

    if "all_of" in when:
        for clause in when["all_of"]:
            for name, wanted in clause.items():
                if not _predicate(name, wanted, facts, rules):
                    return False, reasons
                reasons.append(_reason(name, wanted, facts))
        return True, reasons

    for name, wanted in when.items():
        if not _predicate(name, wanted, facts, rules):
            return False, reasons
        if name != "always":
            reasons.append(_reason(name, wanted, facts))
    return True, reasons


def _why_not_automatic(rules: dict[str, Any], facts: Facts) -> list[str]:
    """Which automatic-approval conditions this request does not meet."""
    automatic = next(
        (path for path in rules["paths"] if path["code"] == PATH_AUTO), None
    )
    if automatic is None:
        return ["this asset is reviewed by its owner"]
    unmet = [
        _reason(name, not wanted, facts)
        for clause in automatic["when"].get("all_of", [])
        for name, wanted in clause.items()
        if not _predicate(name, wanted, facts, rules)
    ]
    return unmet or ["this asset is reviewed by its owner"]


def _reason(name: str, wanted: Any, facts: Facts) -> str:
    """Why this condition matched, in the words the consumer will read.

    The sense of the condition matters as much as its name: a path matched on
    ``purpose_permitted: false`` is matched *because the purpose is not
    permitted*, and a message that reads the other way round would tell the
    consumer the opposite of what happened.
    """
    affirmative = bool(wanted)
    if name == "sensitivity":
        return f"{facts.asset_id} is classified {facts.sensitivity}"
    if name == "contains_pii":
        return "it carries personal data" if affirmative else "it carries no personal data"
    if name == "has_classified_columns":
        return (
            "it publishes classified columns"
            if affirmative
            else "it publishes no classified columns"
        )
    if name == "role_pre_approved":
        return (
            "your role is on the pre-approved list"
            if affirmative
            else "your role is not on the pre-approved list"
        )
    if name == "purpose_permitted":
        return (
            f"{facts.purpose_code} is a permitted purpose at this sensitivity"
            if affirmative
            else f"{facts.purpose_code} is not a permitted purpose for "
                 f"{facts.sensitivity} data in this estate"
        )
    if name == "cross_border":
        return (
            f"you are in {facts.requester_region}, outside its residency regions"
            if affirmative
            else "you are inside its residency regions"
        )
    if name == "residency_conflict":
        return "its residency policy does not permit this request"
    return name


def business_days_from(start: datetime, days: int) -> datetime:
    """Business days, because that is what the policy promises.

    A request submitted on Friday afternoon with a two-day SLA is due Tuesday.
    Telling the consumer Sunday would be a date nobody could act on, and an SLA
    board full of weekend breaches teaches everyone to ignore the board.
    """
    moment = start
    remaining = days
    while remaining > 0:
        moment = moment + timedelta(days=1)
        if moment.weekday() not in WEEKEND:
            remaining -= 1
    return moment


def _alternatives(
    connection: psycopg.Connection[Any], facts: Facts
) -> tuple[dict[str, Any], ...]:
    """A lower-sensitivity equivalent, where the estate has one.

    A block that names no alternative is a dead end, and section 14.1 asks for
    the alternative from the mesh where one exists.
    """
    rows = fetch_all(
        connection,
        "SELECT p.product_id, p.name, p.sensitivity_tier, p.purpose "
        "FROM data_product p "
        "JOIN sensitivity_tier t ON t.code = p.sensitivity_tier "
        "WHERE (p.domain_code, p.industry_code) = "
        "      (SELECT domain_code, industry_code FROM data_product WHERE product_id = %s) "
        "  AND p.product_id <> %s "
        "  AND t.rank_order < (SELECT rank_order FROM sensitivity_tier WHERE code = %s) "
        "ORDER BY t.rank_order DESC, p.product_id",
        (facts.asset_id, facts.asset_id, facts.sensitivity),
    )
    return tuple(
        {
            "product_id": row["product_id"],
            "name": row["name"],
            "sensitivity": row["sensitivity_tier"],
            "why": "same industry and domain, lower sensitivity",
        }
        for row in rows
    )


def evaluate(
    connection: psycopg.Connection[Any],
    *,
    asset_type: str,
    asset_id: str,
    requester_party_id: str,
    purpose_code: str,
    at: datetime | None = None,
) -> Evaluation:
    version_id, rules = load_rules(connection)
    facts = gather(
        connection,
        asset_type=asset_type,
        asset_id=asset_id,
        requester_party_id=requester_party_id,
        purpose_code=purpose_code,
    )
    now = at or datetime.now(UTC)

    for path in rules["paths"]:
        matched, reasons = _matches(path["when"], facts, rules)
        if not matched:
            continue
        if not reasons:
            # The catch-all path matched, which means every earlier one did not.
            # "It is the default" is not an explanation, and the default is the
            # path most requests take — so it explains itself by naming the
            # automatic-approval conditions this request failed to meet.
            reasons = _why_not_automatic(rules, facts)
        sla_days = int(path["sla_days"])
        due = business_days_from(now, sla_days) if sla_days else None
        alternatives = (
            _alternatives(connection, facts)
            if path.get("offer_alternative") and facts.asset_type == ASSET_DATA_PRODUCT
            else ()
        )
        return Evaluation(
            path=path["code"],
            label=path["label"],
            approvers=tuple(path["approvers"]),
            sla_days=sla_days,
            due_at=due,
            policy_version_id=version_id,
            facts=facts,
            reasons=tuple(reasons),
            alternatives=alternatives,
        )

    raise PolicyUnavailableError(
        "no policy path matched, and there is no default: a request the policy cannot "
        "place is refused rather than approved"
    )


def escalation_at(
    evaluation: Evaluation, rules: dict[str, Any], *, at: datetime | None = None
) -> datetime | None:
    """When an unattended request escalates, before the clock runs out."""
    if evaluation.due_at is None:
        return None
    now = at or datetime.now(UTC)
    fraction = float(rules["escalation"]["at_fraction_of_sla"])
    return now + (evaluation.due_at - now) * fraction


def next_business_day(day: date) -> date:
    while day.weekday() in WEEKEND:
        day = day + timedelta(days=1)
    return day
