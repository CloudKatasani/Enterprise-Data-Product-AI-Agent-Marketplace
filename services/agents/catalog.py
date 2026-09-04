"""The agent catalog and agent detail.

The agent card is the data-product card's sibling and deliberately answers the
same question in the same order: what is this, who owns it, how good is it, and
can I use it. The one thing an agent card carries that a product card does not
is what it *will not* do — the declared boundary — because with an agent that is
the most decision-relevant fact on the card.

Access is reported, never enforced by omission: an agent the caller cannot
invoke is still listed, with the scope to request. Hiding it would make the
catalog lie about what exists (section 12).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.pagination import Cursor, Page
from services.common.principal import Principal, held_scopes
from services.common.rubrics import Rubric

INVOKE_SCOPE = "agent:{agent_id}:invoke"
REQUEST_URL = "/requests/new/access?asset={agent_id}&surface=agent"

DEFAULT_SORT = "name"
# (sort column, direction). Every sort is a keyset over (column, agent_id), so a
# page continues from a position rather than a count and an agent cannot be
# shown twice because another was certified between requests.
SORTS: dict[str, tuple[str, str]] = {
    "name": ("a.name", "asc"),
    "coverage": ("coverage_count", "desc"),
    "adoption": ("answers_30d", "desc"),
    "quality": ("r.pass_rate_pct", "desc"),
}

_CARD = """
SELECT a.agent_id, a.name, a.industry_code, a.domain_code, a.certification,
       a.owner_party_id, a.on_call, p.display_name AS owner_name,
       v.agent_version_id, v.semver, v.status, v.autonomy_level,
       v.capability_statement, v.business_value_block, v.out_of_scope, v.personas,
       v.analyses, v.budget_p95_latency_ms, v.budget_cost_per_answer_usd,
       v.eval_threshold_pct, v.eval_run_id,
       (SELECT count(*) FROM agent_kpi_coverage c
         WHERE c.agent_version_id = v.agent_version_id) AS coverage_count,
       (SELECT count(*) FROM agent_product_binding b
         WHERE b.agent_version_id = v.agent_version_id) AS product_count,
       (SELECT count(*) FROM demo_exchange e
         WHERE e.agent_version_id = v.agent_version_id
           AND e.validation_state = 'passing') AS demo_count,
       (SELECT count(*) FROM agent_interaction i
         WHERE i.agent_version_id = v.agent_version_id
           AND i.occurred_at > now() - interval '30 days') AS answers_30d,
       r.pass_rate_pct, r.groundedness_pct, r.passed AS eval_passed
FROM agent a
JOIN agent_version v ON v.agent_version_id = a.current_version_id
LEFT JOIN party p ON p.party_id = a.owner_party_id
LEFT JOIN evaluation_run r ON r.eval_run_id = v.eval_run_id
WHERE a.tenant_id = %(tenant)s
"""


@dataclass
class AgentFilters:
    industry: list[str] | None = None
    domain: list[str] | None = None
    autonomy: list[str] | None = None
    certification: list[str] | None = None
    kpi: list[str] | None = None
    product: list[str] | None = None

    def clauses(self) -> tuple[str, dict[str, Any]]:
        where: list[str] = []
        arguments: dict[str, Any] = {}
        simple = {
            "industry": "a.industry_code",
            "domain": "a.domain_code",
            "autonomy": "v.autonomy_level",
            "certification": "a.certification",
        }
        for name, column in simple.items():
            values = getattr(self, name)
            if values:
                where.append(f"{column} = ANY(%({name})s)")
                arguments[name] = values
        if self.kpi:
            where.append(
                "EXISTS (SELECT 1 FROM agent_kpi_coverage c "
                "WHERE c.agent_version_id = v.agent_version_id AND c.kpi_id = ANY(%(kpi)s))"
            )
            arguments["kpi"] = self.kpi
        if self.product:
            where.append(
                "EXISTS (SELECT 1 FROM agent_product_binding b "
                "WHERE b.agent_version_id = v.agent_version_id "
                "AND b.product_id = ANY(%(product)s))"
            )
            arguments["product"] = self.product
        return (" AND " + " AND ".join(where) if where else ""), arguments


def _access(agent_id: str, scopes: frozenset[str]) -> dict[str, Any]:
    scope = INVOKE_SCOPE.format(agent_id=agent_id)
    return {
        "granted": scope in scopes,
        "required_scope": scope,
        "request_access_url": REQUEST_URL.format(agent_id=agent_id),
    }


def _card(row: dict[str, Any], scopes: frozenset[str]) -> dict[str, Any]:
    return {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "capability_statement": row["capability_statement"],
        "industry": row["industry_code"],
        "domain": row["domain_code"],
        "autonomy_level": row["autonomy_level"],
        "certification": row["certification"],
        "status": row["status"],
        "version": row["semver"],
        # The boundary sits on the card, not behind a tab. What an agent will
        # not do is a first-class fact about it.
        "out_of_scope": list(row["out_of_scope"]),
        "personas": list(row["personas"]),
        "owner": {"party_id": row["owner_party_id"], "name": row["owner_name"],
                  "on_call": row["on_call"]},
        "coverage": {"kpis": int(row["coverage_count"]),
                     "data_products": int(row["product_count"])},
        "demo": {"validated_exchanges": int(row["demo_count"])},
        "evaluation": {
            "pass_rate_pct": float(row["pass_rate_pct"]) if row["pass_rate_pct"] else None,
            "groundedness_pct": (
                float(row["groundedness_pct"]) if row["groundedness_pct"] else None
            ),
            "threshold_pct": float(row["eval_threshold_pct"]),
            "passed": row["eval_passed"],
        },
        "budgets": {
            "p95_latency_ms": int(row["budget_p95_latency_ms"]),
            "cost_per_answer_usd": float(row["budget_cost_per_answer_usd"]),
        },
        "adoption": {"answers_30d": int(row["answers_30d"])},
        "access": _access(row["agent_id"], scopes),
    }


def _cursor_value(row: dict[str, Any], sort: str) -> Any:
    column, _ = SORTS.get(sort, SORTS[DEFAULT_SORT])
    key = column.split(".")[-1] if "." in column else column
    value = row.get("name" if key == "name" else key)
    return float(value) if isinstance(value, Decimal) else value


def list_agents(
    connection: psycopg.Connection[Any],
    tenant: str,
    principal: Principal,
    rubric: Rubric,
    *,
    filters: AgentFilters | None = None,
    sort: str = DEFAULT_SORT,
    cursor: str | None = None,
    limit: int | None = None,
) -> Page:
    filters = filters or AgentFilters()
    where, arguments = filters.clauses()
    column, direction = SORTS.get(sort, SORTS[DEFAULT_SORT])

    size = int(rubric.number("page_size.default")) if limit is None else limit
    size = min(size, int(rubric.number("page_size.max")))

    parameters: dict[str, Any] = {**arguments, "tenant": tenant, "limit": size + 1}
    predicates = [where] if where else []
    if cursor:
        decoded = Cursor.decode(cursor)
        comparison = ">" if direction == "asc" else "<"
        predicates.append(
            f" AND ({column}, a.agent_id) {comparison} (%(cursor_value)s, %(cursor_id)s)"
        )
        parameters["cursor_value"] = decoded.sort_value
        parameters["cursor_id"] = decoded.identifier

    rows = fetch_all(
        connection,
        f"{_CARD}{''.join(predicates)} ORDER BY {column} {direction.upper()} NULLS LAST, "
        "a.agent_id LIMIT %(limit)s",
        parameters,
    )
    total = fetch_one(
        connection,
        "SELECT count(*) AS total FROM agent WHERE tenant_id = %s",
        (tenant,),
    )
    scopes = held_scopes(connection, principal.party_id)
    has_more = len(rows) > size
    visible = rows[:size]
    next_cursor = None
    if has_more and visible:
        next_cursor = Cursor(
            sort_value=_cursor_value(visible[-1], sort), identifier=visible[-1]["agent_id"]
        ).encode()
    return Page(
        items=[_card(row, scopes) for row in visible],
        total=int(total["total"]) if total else None,
        next_cursor=next_cursor,
    )


def get_agent(
    connection: psycopg.Connection[Any], tenant: str, agent_id: str, principal: Principal
) -> dict[str, Any] | None:
    row = fetch_one(
        connection, f"{_CARD} AND a.agent_id = %(agent_id)s",
        {"tenant": tenant, "agent_id": agent_id},
    )
    if row is None:
        return None
    return _card(row, held_scopes(connection, principal.party_id))


def coverage(connection: psycopg.Connection[Any], version_id: str) -> list[dict[str, Any]]:
    """The coverage map, with the eval accuracy and sample size behind each row.

    A coverage claim with no sample size behind it is a marketing claim, so the
    numbers travel with the row rather than being available on request.
    """
    return [
        {
            "kpi_id": row["kpi_id"],
            "kpi_name": row["kpi_name"],
            "source_product_id": row["source_product_id"],
            "columns_used": list(row["columns_used"]),
            "supported_grains": list(row["supported_grains"]),
            "supported_slices": list(row["supported_slices"]),
            "analysis_depth": row["analysis_depth"],
            "eval_accuracy": float(row["eval_accuracy"]) if row["eval_accuracy"] else None,
            "eval_sample_size": row["eval_sample_size"],
        }
        for row in fetch_all(
            connection,
            "SELECT c.*, k.kpi_name FROM agent_kpi_coverage c "
            "JOIN kpi_definition k ON k.kpi_id = c.kpi_id "
            "WHERE c.agent_version_id = %s ORDER BY c.kpi_id",
            (version_id,),
        )
    ]
