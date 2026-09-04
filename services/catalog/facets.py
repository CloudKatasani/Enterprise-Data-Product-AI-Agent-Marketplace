"""Facets for the catalog rail.

A facet is only useful if its counts reflect the *other* filters a consumer has
applied but not its own — otherwise selecting "Telecom" collapses the industry
list to one row and the consumer cannot change their mind without starting over.
So each facet is counted against the filter set with that facet's own predicate
removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric


@dataclass(frozen=True)
class FacetDefinition:
    code: str
    label: str
    column: str
    # Some facets read from a joined table rather than the base row.
    join: str | None = None


PRODUCT_FACETS: tuple[FacetDefinition, ...] = (
    FacetDefinition("industry", "Industry", "p.industry_code"),
    FacetDefinition("domain", "Business domain", "p.domain_code"),
    FacetDefinition("archetype", "Archetype", "p.archetype_code"),
    FacetDefinition("certification", "Certification", "p.certification"),
    FacetDefinition("sensitivity", "Sensitivity", "p.sensitivity_tier"),
    FacetDefinition("tier", "Tier", "p.tier"),
    FacetDefinition("owner", "Owner", "p.owner_party_id"),
    FacetDefinition(
        "endpoint", "Endpoint", "e.surface",
        join="LEFT JOIN endpoint e ON e.product_id = p.product_id",
    ),
    FacetDefinition(
        "kpi", "Certified KPI", "k.kpi_id",
        join="LEFT JOIN kpi_definition k ON k.source_of_record = p.product_id",
    ),
    FacetDefinition(
        "quality_band", "Quality band", "q.band",
        join="LEFT JOIN LATERAL (SELECT band FROM quality_score_snapshot s "
             "WHERE s.product_id = p.product_id ORDER BY s.computed_at DESC LIMIT 1) q ON true",
    ),
)

AGENT_FACETS: tuple[FacetDefinition, ...] = (
    FacetDefinition("industry", "Industry", "a.industry_code"),
    FacetDefinition("domain", "Business domain", "a.domain_code"),
    FacetDefinition("certification", "Certification", "a.certification"),
    FacetDefinition("owner", "Owner", "a.owner_party_id"),
    FacetDefinition(
        "autonomy", "Autonomy level", "v.autonomy_level",
        join="LEFT JOIN agent_version v ON v.agent_version_id = a.current_version_id",
    ),
    FacetDefinition(
        "kpi", "KPI answered", "cov.kpi_id",
        join="LEFT JOIN agent_version v2 ON v2.agent_version_id = a.current_version_id "
             "LEFT JOIN agent_kpi_coverage cov ON cov.agent_version_id = v2.agent_version_id",
    ),
    FacetDefinition(
        "product", "Data product", "b.product_id",
        join="LEFT JOIN agent_version v3 ON v3.agent_version_id = a.current_version_id "
             "LEFT JOIN agent_product_binding b ON b.agent_version_id = v3.agent_version_id",
    ),
)


@dataclass
class FacetValue:
    value: str
    count: int
    selected: bool


@dataclass
class Facet:
    code: str
    label: str
    values: list[FacetValue] = field(default_factory=list)

    def document(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "values": [
                {"value": value.value, "count": value.count, "selected": value.selected}
                for value in self.values
            ],
        }


def compute(
    connection: psycopg.Connection[Any],
    tenant: str,
    definitions: tuple[FacetDefinition, ...],
    base_table: str,
    base_alias: str,
    selected: dict[str, list[str]],
    rubric: Rubric,
) -> list[Facet]:
    limit = int(rubric.number("page_size.facet_values"))
    facets: list[Facet] = []

    for definition in definitions:
        # Every other facet's selection constrains this one; its own does not.
        others = {code: values for code, values in selected.items() if code != definition.code}
        joins: list[str] = []
        predicates = [f"{base_alias}.tenant_id = %s"]
        params: list[Any] = [tenant]

        if definition.join:
            joins.append(definition.join)
        for code, values in sorted(others.items()):
            if not values:
                continue
            other = next((d for d in definitions if d.code == code), None)
            if other is None:
                continue
            if other.join and other.join not in joins:
                joins.append(other.join)
            predicates.append(f"{other.column} = ANY(%s)")
            params.append(values)

        sql = (
            f"SELECT {definition.column} AS value, count(DISTINCT {base_alias}.{_key(base_alias)})"
            f" AS count FROM {base_table} {base_alias} " + " ".join(joins) +
            " WHERE " + " AND ".join(predicates) +
            f" AND {definition.column} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {limit}"
        )
        rows = fetch_all(connection, sql, tuple(params))
        chosen = set(selected.get(definition.code, []))
        facets.append(
            Facet(
                code=definition.code,
                label=definition.label,
                values=[
                    FacetValue(str(row["value"]), int(row["count"]), str(row["value"]) in chosen)
                    for row in rows
                ],
            )
        )
    return facets


def _key(alias: str) -> str:
    return {"p": "product_id", "a": "agent_id"}[alias]
