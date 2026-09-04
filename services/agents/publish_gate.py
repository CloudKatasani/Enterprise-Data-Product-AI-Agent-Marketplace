"""The agent publish gate (BUILD.md section 15.3).

Eight checks, all blocking, all resolved from data rather than asserted by a
reviewer. The result is a structure rather than a boolean because the agent page
renders it: a consumer looking at an unpublished agent should be able to see
exactly which line is red and what would clear it.

Every threshold comes from the ``agent_evaluation`` rubric's ``publish_gate``
block. Nothing here decides what "enough demo exchanges" means.

The gate refuses; it does not publish. Turning a passing gate into a published
version is a separate, recorded act with an author.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric

MIN_EXCHANGES_PATH = "publish_gate.min_demo_exchanges"
MAX_AGE_DAYS_PATH = "publish_gate.demo_validation_max_age_days"
STATEMENT_MIN_PATH = "publish_gate.capability_statement_min_chars"
STATEMENT_MAX_PATH = "publish_gate.capability_statement_max_chars"
UNCITED_ALLOWED_PATH = "publish_gate.uncited_numeric_claims_allowed"
REQUIRE_OUT_OF_SCOPE_PATH = "publish_gate.require_out_of_scope"
REQUIRE_VALUE_CASE_PATH = "publish_gate.require_value_case"
REQUIRE_ON_CALL_PATH = "publish_gate.require_on_call"

CHECK_STATEMENT = "capability_statement"
CHECK_COVERAGE = "coverage_map"
CHECK_EXCHANGES = "demo_exchanges"
CHECK_ENTITLEMENT = "entitlement_scope"
CHECK_COMPOSITIONAL = "compositional_exposure"
CHECK_EVALUATION = "evaluation_suite"
CHECK_GROUNDEDNESS = "groundedness"
CHECK_OWNERSHIP = "ownership_and_value"

ORDER = (
    CHECK_STATEMENT,
    CHECK_COVERAGE,
    CHECK_EXCHANGES,
    CHECK_ENTITLEMENT,
    CHECK_COMPOSITIONAL,
    CHECK_EVALUATION,
    CHECK_GROUNDEDNESS,
    CHECK_OWNERSHIP,
)

TITLES = {
    CHECK_STATEMENT: "Capability statement, value block and boundary",
    CHECK_COVERAGE: "Coverage map cites certified KPIs and bound products",
    CHECK_EXCHANGES: "Curated demo exchanges validated recently",
    CHECK_ENTITLEMENT: "No reachable column outside the approved scope",
    CHECK_COMPOSITIONAL: "Compositional exposure checked",
    CHECK_EVALUATION: "Evaluation run above the declared threshold",
    CHECK_GROUNDEDNESS: "No uncited numeric claims",
    CHECK_OWNERSHIP: "Owner, on-call, escalation and value case recorded",
}

STATE_PUBLISHED = "published"
KPI_CERTIFIED = "certified"
ASSET_AGENT = "agent"


class GateUnavailableError(RuntimeError):
    """The gate cannot be evaluated. Never treated as a pass."""


@dataclass(frozen=True)
class Check:
    code: str
    title: str
    passed: bool
    detail: str

    def document(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class GateResult:
    agent_id: str
    agent_version_id: str
    rubric_version_id: str
    checks: tuple[Check, ...]

    @property
    def publishable(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def shortfalls(self) -> tuple[str, ...]:
        return tuple(check.detail for check in self.checks if not check.passed)

    def document(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_version_id": self.agent_version_id,
            "rubric_version_id": self.rubric_version_id,
            "publishable": self.publishable,
            "checks": [check.document() for check in self.checks],
        }

    def message(self) -> str:
        """One line a steward can act on, naming every shortfall."""
        if self.publishable:
            return f"{self.agent_version_id} clears every publish-gate check."
        return (
            f"{self.agent_version_id} cannot be published: "
            + "; ".join(self.shortfalls)
            + "."
        )


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def check_statement(version: dict[str, Any], rubric: Rubric) -> Check:
    minimum = int(rubric.number(STATEMENT_MIN_PATH))
    maximum = int(rubric.number(STATEMENT_MAX_PATH))
    statement = (version["capability_statement"] or "").strip()
    problems: list[str] = []
    if not minimum <= len(statement) <= maximum:
        problems.append(
            f"the capability statement is {len(statement)} characters, outside "
            f"{minimum}-{maximum}"
        )
    if not (version["business_value_block"] or "").strip():
        problems.append("no business value block")
    if rubric.flag(REQUIRE_OUT_OF_SCOPE_PATH) and not version["out_of_scope"]:
        problems.append("no declared out-of-scope boundary")
    return Check(
        CHECK_STATEMENT, TITLES[CHECK_STATEMENT], not problems,
        "; ".join(problems)
        or f"{len(statement)} characters, value block present, "
           f"{len(version['out_of_scope'])} boundaries declared",
    )


def _coverage(connection: psycopg.Connection[Any], version_id: str) -> Check:
    rows = fetch_all(
        connection,
        "SELECT c.kpi_id, c.source_product_id, c.columns_used, "
        "       k.kpi_id IS NOT NULL AS kpi_exists, k.status AS kpi_status, "
        "       b.columns_allowed "
        "FROM agent_kpi_coverage c "
        "LEFT JOIN kpi_definition k ON k.kpi_id = c.kpi_id "
        "LEFT JOIN agent_product_binding b ON b.agent_version_id = c.agent_version_id "
        "  AND b.product_id = c.source_product_id "
        "WHERE c.agent_version_id = %s ORDER BY c.kpi_id",
        (version_id,),
    )
    if not rows:
        return Check(CHECK_COVERAGE, TITLES[CHECK_COVERAGE], False, "the coverage map is empty")

    problems: list[str] = []
    for row in rows:
        if not row["kpi_exists"]:
            # A foreign key already stops a coverage row naming a KPI that does
            # not exist. This catches the case the key cannot: a KPI that exists
            # in another tenant and is invisible behind row-level security.
            problems.append(f"{row['kpi_id']} is not in the KPI register")
            continue
        if row["kpi_status"] != KPI_CERTIFIED:
            problems.append(f"{row['kpi_id']} is {row['kpi_status']}, not certified")
        if row["columns_allowed"] is None:
            problems.append(
                f"{row['kpi_id']} reads {row['source_product_id']}, which this version "
                "is not bound to"
            )
            continue
        outside = set(row["columns_used"]) - set(row["columns_allowed"])
        if outside:
            problems.append(
                f"{row['kpi_id']} uses columns on {row['source_product_id']} outside the "
                "binding: " + ", ".join(sorted(outside))
            )
    return Check(
        CHECK_COVERAGE, TITLES[CHECK_COVERAGE], not problems,
        "; ".join(problems) or f"{len(rows)} certified KPI(s), every column inside the binding",
    )


def _exchanges(
    connection: psycopg.Connection[Any], version_id: str, rubric: Rubric
) -> Check:
    minimum = int(rubric.number(MIN_EXCHANGES_PATH))
    max_age = int(rubric.number(MAX_AGE_DAYS_PATH))
    rows = fetch_all(
        connection,
        "SELECT exchange_id, validation_state, last_validated FROM demo_exchange "
        "WHERE agent_version_id = %s ORDER BY ordinal",
        (version_id,),
    )
    problems: list[str] = []
    if len(rows) < minimum:
        problems.append(
            f"{len(rows)} curated demo exchange(s); the gate requires {minimum}. "
            f"Author {minimum - len(rows)} more."
        )
    cutoff = datetime.now(UTC) - timedelta(days=max_age)
    stale = [
        row["exchange_id"]
        for row in rows
        if row["last_validated"] is None or row["last_validated"] < cutoff
    ]
    if stale:
        problems.append(
            f"not validated in the last {max_age} day(s): " + ", ".join(stale)
        )
    failing = [row["exchange_id"] for row in rows if row["validation_state"] != "passing"]
    if failing:
        problems.append("not passing against its golden answer: " + ", ".join(failing))
    return Check(
        CHECK_EXCHANGES, TITLES[CHECK_EXCHANGES], not problems,
        "; ".join(problems) or f"{len(rows)} exchange(s), all validated within {max_age} days",
    )


def _entitlement(connection: psycopg.Connection[Any], version_id: str) -> Check:
    """No column the agent can reach carries a tag its approved scope does not permit."""
    rows = fetch_all(
        connection,
        "SELECT b.product_id, col.name, col.sensitivity_code "
        "FROM agent_product_binding b "
        "JOIN data_product_column col ON col.product_id = b.product_id "
        "  AND col.name = ANY(b.columns_allowed) "
        "WHERE b.agent_version_id = %s",
        (version_id,),
    )
    if not rows:
        return Check(
            CHECK_ENTITLEMENT, TITLES[CHECK_ENTITLEMENT], False,
            "this version is bound to no product, so nothing was checked",
        )

    machine = fetch_one(
        connection,
        "SELECT a.machine_identity FROM agent a "
        "JOIN agent_version v ON v.agent_id = a.agent_id WHERE v.agent_version_id = %s",
        (version_id,),
    )
    if machine is None or not machine["machine_identity"]:
        return Check(
            CHECK_ENTITLEMENT, TITLES[CHECK_ENTITLEMENT], False,
            "the agent holds no machine identity, so its scope cannot be approved",
        )

    granted: dict[str, set[str]] = {}
    for row in fetch_all(
        connection,
        "SELECT g.asset_id, s.expression FROM entitlement_grant g "
        "JOIN grant_scope s ON s.grant_id = g.grant_id AND s.scope_kind = 'columns' "
        "WHERE g.principal_id = %s AND g.revoked_at IS NULL AND g.expires_at > now()",
        (machine["machine_identity"],),
    ):
        granted.setdefault(row["asset_id"], set()).update(
            name.strip() for name in row["expression"].split(",") if name.strip()
        )

    problems: list[str] = []
    for row in rows:
        allowed = granted.get(row["product_id"])
        if allowed is None:
            problems.append(f"no approved scope on {row['product_id']}")
        elif row["name"] not in allowed:
            problems.append(
                f"{row['product_id']} binding reaches a {row['sensitivity_code']} column "
                "the approved scope does not cover"
            )
    return Check(
        CHECK_ENTITLEMENT, TITLES[CHECK_ENTITLEMENT], not problems,
        "; ".join(sorted(set(problems)))
        or f"{len(rows)} reachable column(s), every one inside the approved scope",
    )


def _suite_result(run: dict[str, Any], suite: str) -> dict[str, Any] | None:
    for entry in run["suite_results"]:
        if entry["suite"] == suite:
            return entry
    return None


def _evaluation(run: dict[str, Any] | None, version: dict[str, Any]) -> Check:
    if run is None:
        return Check(
            CHECK_EVALUATION, TITLES[CHECK_EVALUATION], False,
            "no evaluation run recorded for this version",
        )
    failing = [
        entry["suite"]
        for entry in run["suite_results"]
        if entry["blocking"] and not entry["passed"]
    ]
    threshold = Decimal(str(version["eval_threshold_pct"]))
    rate = Decimal(str(run["pass_rate_pct"]))
    problems: list[str] = []
    if failing:
        problems.append("blocking suite(s) below threshold: " + ", ".join(failing))
    if rate < threshold:
        problems.append(f"overall {rate}% against a declared {threshold}%")
    missing = set(version["eval_suites"]) - {entry["suite"] for entry in run["suite_results"]}
    if missing:
        problems.append("declared but not run: " + ", ".join(sorted(missing)))
    return Check(
        CHECK_EVALUATION, TITLES[CHECK_EVALUATION], not problems,
        "; ".join(problems) or f"{rate}% across {len(run['suite_results'])} suite(s)",
    )


def _groundedness(run: dict[str, Any] | None, rubric: Rubric) -> Check:
    allowed = int(rubric.number(UNCITED_ALLOWED_PATH))
    if run is None:
        return Check(
            CHECK_GROUNDEDNESS, TITLES[CHECK_GROUNDEDNESS], False,
            "no evaluation run, so groundedness is unproven",
        )
    entry = _suite_result(run, "groundedness")
    if entry is None:
        return Check(
            CHECK_GROUNDEDNESS, TITLES[CHECK_GROUNDEDNESS], False,
            "the evaluation run did not include the groundedness suite",
        )
    uncited = len(entry["failures"])
    passed = uncited <= allowed
    return Check(
        CHECK_GROUNDEDNESS, TITLES[CHECK_GROUNDEDNESS], passed,
        f"{uncited} answer(s) carry an uncited numeric claim; {allowed} allowed"
        if not passed
        else f"{entry['cases']} answer(s), no uncited numeric claim",
    )


def _compositional(run: dict[str, Any] | None) -> Check:
    if run is None:
        return Check(
            CHECK_COMPOSITIONAL, TITLES[CHECK_COMPOSITIONAL], False,
            "no evaluation run, so compositional exposure is unchecked",
        )
    entry = _suite_result(run, "compositional_exposure")
    if entry is None:
        return Check(
            CHECK_COMPOSITIONAL, TITLES[CHECK_COMPOSITIONAL], False,
            "the evaluation run did not include the compositional exposure suite",
        )
    return Check(
        CHECK_COMPOSITIONAL, TITLES[CHECK_COMPOSITIONAL], bool(entry["passed"]),
        "; ".join(failure["detail"] for failure in entry["failures"])
        or f"{entry['cases']} case(s), no widening through a sub-agent",
    )


def _ownership(
    connection: psycopg.Connection[Any], agent: dict[str, Any], rubric: Rubric
) -> Check:
    problems: list[str] = []
    if not agent["owner_party_id"]:
        problems.append("no owner recorded")
    if rubric.flag(REQUIRE_ON_CALL_PATH):
        if not (agent["on_call"] or "").strip():
            problems.append("no on-call rotation recorded")
        if not (agent["escalation_path"] or "").strip():
            problems.append("no escalation path recorded")
    if rubric.flag(REQUIRE_VALUE_CASE_PATH):
        case = fetch_one(
            connection,
            "SELECT v.value_case_id, count(a.assumption_id) AS assumptions "
            "FROM value_case v LEFT JOIN value_assumption a ON a.value_case_id = v.value_case_id "
            "WHERE v.asset_type = %s AND v.asset_id = %s GROUP BY v.value_case_id",
            (ASSET_AGENT, agent["agent_id"]),
        )
        if case is None:
            problems.append("no value case authored")
        elif not case["assumptions"]:
            problems.append("the value case states no assumptions")
    return Check(
        CHECK_OWNERSHIP, TITLES[CHECK_OWNERSHIP], not problems,
        "; ".join(problems) or "owner, on-call, escalation and a value case with assumptions",
    )


# ---------------------------------------------------------------------------
# Evaluating the gate
# ---------------------------------------------------------------------------


def evaluate(
    connection: psycopg.Connection[Any], agent_version_id: str, rubric: Rubric
) -> GateResult:
    version = fetch_one(
        connection,
        "SELECT v.*, a.agent_id, a.owner_party_id, a.on_call, a.escalation_path "
        "FROM agent_version v JOIN agent a ON a.agent_id = v.agent_id "
        "WHERE v.agent_version_id = %s",
        (agent_version_id,),
    )
    if version is None:
        raise GateUnavailableError(f"no agent version {agent_version_id}")

    run = fetch_one(
        connection,
        "SELECT suite_results, pass_rate_pct, groundedness_pct, passed FROM evaluation_run "
        "WHERE agent_version_ref = %s ORDER BY finished_at DESC LIMIT 1",
        (agent_version_id,),
    )

    checks = (
        check_statement(version, rubric),
        _coverage(connection, agent_version_id),
        _exchanges(connection, agent_version_id, rubric),
        _entitlement(connection, agent_version_id),
        _compositional(run),
        _evaluation(run, version),
        _groundedness(run, rubric),
        _ownership(connection, version, rubric),
    )
    ordered = tuple(sorted(checks, key=lambda check: ORDER.index(check.code)))
    return GateResult(
        agent_id=version["agent_id"],
        agent_version_id=agent_version_id,
        rubric_version_id=rubric.rubric_version_id,
        checks=ordered,
    )
