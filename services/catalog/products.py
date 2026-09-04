"""Product listing and detail assembly.

Two shapes are served from here, and they are deliberately different:

* **The card** (section 12) — twelve elements in fixed positions. Every listing
  surface uses the same projection, so the grid stays scannable and the landing
  ribbon shows the same card as the catalog.
* **The detail** — eight tabs, each assembled from real metadata. Nothing on a
  tab is a placeholder: where a fact does not exist yet the tab says so and says
  what would produce it, which is a different thing from an empty box.

Both carry ``visibility``. A consumer sees an asset's metadata before they can
query it (that is the point of a catalog), so the card and the detail always
render, and the parts that need a grant carry ``granted: false`` with the scope
that would unlock them. This is the partial-permission state, and it is the
common case rather than an edge case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from services.catalog import facets as facet_module
from services.common.db import fetch_all, fetch_one
from services.common.pagination import Cursor, Page
from services.common.principal import Principal, effective_scopes
from services.common.rubrics import Rubric

CARD_SQL = """
SELECT p.product_id, p.name, p.purpose, p.industry_code, p.domain_code, p.archetype_code,
       p.sensitivity_tier, p.certification, p.owner_party_id, p.current_version, p.grain,
       p.tier, p.updated_at,
       owner.display_name AS owner_name,
       q.composite AS quality_composite, q.band AS quality_band,
       q.rubric_version_id AS quality_rubric_version_id, q.computed_at AS quality_computed_at,
       f.target_text AS freshness_target, f.target_numeric AS freshness_p95_minutes,
       coalesce(u.active_consumers, 0) AS active_consumers,
       coalesce(u.distinct_teams, 0) AS distinct_teams,
       coalesce(agents.attached, '{}') AS attached_agents,
       coalesce(kpis.certified, '{}') AS certified_kpis,
       coalesce(surfaces.endpoints, '{}') AS endpoints,
       inc.incident_id AS open_incident_id, inc.severity AS open_incident_severity
FROM data_product p
JOIN party owner ON owner.party_id = p.owner_party_id
LEFT JOIN LATERAL (
  SELECT composite, band, rubric_version_id, computed_at
  FROM quality_score_snapshot s
  WHERE s.product_id = p.product_id ORDER BY s.computed_at DESC LIMIT 1
) q ON true
LEFT JOIN LATERAL (
  SELECT g.target_text, g.target_numeric
  FROM data_contract_version c
  JOIN contract_guarantee g ON g.contract_version_id = c.contract_version_id
  WHERE c.product_id = p.product_id AND c.status = 'active' AND g.dimension = 'freshness'
  LIMIT 1
) f ON true
LEFT JOIN LATERAL (
  SELECT max(active_consumers) AS active_consumers, max(distinct_teams) AS distinct_teams
  FROM usage_daily_agg a
  WHERE a.asset_id = p.product_id AND a.asset_type = 'data_product'
    AND a.activity_date > current_date - %(adoption_window)s::int
) u ON true
LEFT JOIN LATERAL (
  SELECT array_agg(DISTINCT ag.agent_id ORDER BY ag.agent_id) AS attached
  FROM agent_product_binding b
  JOIN agent_version v ON v.agent_version_id = b.agent_version_id
  JOIN agent ag ON ag.current_version_id = v.agent_version_id
  WHERE b.product_id = p.product_id
) agents ON true
LEFT JOIN LATERAL (
  SELECT array_agg(DISTINCT k.kpi_id ORDER BY k.kpi_id) AS certified
  FROM kpi_definition k WHERE k.source_of_record = p.product_id
) kpis ON true
LEFT JOIN LATERAL (
  SELECT array_agg(DISTINCT e.surface ORDER BY e.surface) AS endpoints
  FROM endpoint e WHERE e.product_id = p.product_id
) surfaces ON true
LEFT JOIN LATERAL (
  SELECT i.incident_id, i.severity FROM incident i
  WHERE i.asset_type = 'data_product' AND i.asset_id = p.product_id
    AND i.status IN ('open', 'mitigating')
  ORDER BY i.detected_at DESC LIMIT 1
) inc ON true
WHERE p.tenant_id = %(tenant)s
"""


@dataclass(frozen=True)
class ProductFilters:
    industry: list[str] | None = None
    domain: list[str] | None = None
    archetype: list[str] | None = None
    certification: list[str] | None = None
    sensitivity: list[str] | None = None
    tier: list[str] | None = None
    owner: list[str] | None = None
    endpoint: list[str] | None = None
    kpi: list[str] | None = None
    quality_band: list[str] | None = None

    def selected(self) -> dict[str, list[str]]:
        return {
            code: values
            for code, values in {
                "industry": self.industry, "domain": self.domain, "archetype": self.archetype,
                "certification": self.certification, "sensitivity": self.sensitivity,
                "tier": self.tier, "owner": self.owner, "endpoint": self.endpoint,
                "kpi": self.kpi, "quality_band": self.quality_band,
            }.items()
            if values
        }


SORTS = {
    "name": ("p.name", "asc"),
    "quality": ("q.composite", "desc"),
    "adoption": ("u.active_consumers", "desc"),
    "recent": ("p.updated_at", "desc"),
}
DEFAULT_SORT = "name"


def _card(row: dict[str, Any], scopes: frozenset[str]) -> dict[str, Any]:
    """The twelve-element product card, in fixed positions."""
    product_id = row["product_id"]
    read_scope = f"dp:{product_id}:read"
    return {
        # 1 identity, 2 purpose
        "product_id": product_id,
        "name": row["name"],
        "purpose": row["purpose"],
        # 3 taxonomy
        "industry": row["industry_code"],
        "domain": row["domain_code"],
        "archetype": row["archetype_code"],
        # 4 certification, 5 sensitivity
        "certification": row["certification"],
        "sensitivity": row["sensitivity_tier"],
        "tier": row["tier"],
        # 6 quality
        "quality": {
            "composite": float(row["quality_composite"]) if row["quality_composite"] else None,
            "band": row["quality_band"],
            "rubric_version_id": row["quality_rubric_version_id"],
            "computed_at": _iso(row["quality_computed_at"]),
        },
        # 7 freshness
        "freshness": {
            "target": row["freshness_target"],
            "p95_minutes": float(row["freshness_p95_minutes"])
            if row["freshness_p95_minutes"] is not None
            else None,
        },
        # 8 owner
        "owner": {"party_id": row["owner_party_id"], "name": row["owner_name"]},
        # 9 adoption
        "adoption": {
            "active_consumers": row["active_consumers"],
            "distinct_teams": row["distinct_teams"],
        },
        # 10 attached agents, 11 certified KPIs
        "attached_agents": list(row["attached_agents"]),
        "certified_kpis": list(row["certified_kpis"]),
        # 12 surfaces and access state
        "endpoints": list(row["endpoints"]),
        "access": {
            "granted": read_scope in scopes,
            "required_scope": read_scope,
            "request_access_url": f"/requests/new/access?asset={product_id}&surface=sql",
        },
        "incident": (
            {"incident_id": row["open_incident_id"], "severity": row["open_incident_severity"]}
            if row["open_incident_id"]
            else None
        ),
        "grain": row["grain"],
        "current_version": row["current_version"],
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def list_products(
    connection: psycopg.Connection[Any],
    tenant: str,
    principal: Principal,
    rubric: Rubric,
    *,
    filters: ProductFilters | None = None,
    sort: str = DEFAULT_SORT,
    cursor: str | None = None,
    limit: int | None = None,
    featured: bool = False,
) -> tuple[Page, list[facet_module.Facet]]:
    from services.common.problem import bad_request

    if sort not in SORTS:
        raise bad_request(
            f"unknown sort {sort!r}; expected one of {', '.join(sorted(SORTS))}", sort=sort
        )
    filters = filters or ProductFilters()
    page_size = int(rubric.number("page_size.default")) if limit is None else limit
    maximum = int(rubric.number("page_size.max"))
    page_size = min(page_size, maximum)
    adoption_window = int(rubric.number("adoption_window_days"))

    column, direction = SORTS[sort]
    params: dict[str, Any] = {"tenant": tenant, "adoption_window": adoption_window}
    predicates: list[str] = []

    for code, values in filters.selected().items():
        definition = next(d for d in facet_module.PRODUCT_FACETS if d.code == code)
        if definition.join:
            # Facet joins on the listing use an EXISTS so a product with two
            # endpoints is not returned twice.
            predicates.append(_exists_predicate(code, f"%({code})s"))
        else:
            predicates.append(f"{definition.column} = ANY(%({code})s)")
        params[code] = values

    if featured:
        # The landing band shows certified, healthy, adopted products only: a
        # marketing surface that promotes an at-risk asset is a governance
        # failure, not a design choice.
        predicates.append("p.certification = 'certified'")
        predicates.append("coalesce(q.composite, 0) >= %(featured_floor)s")
        params["featured_floor"] = rubric.number("featured_ranking.min_quality_composite")

    if cursor:
        decoded = Cursor.decode(cursor)
        comparison = ">" if direction == "asc" else "<"
        predicates.append(
            f"({column}, p.product_id) {comparison} (%(cursor_value)s, %(cursor_id)s)"
        )
        params["cursor_value"] = decoded.sort_value
        params["cursor_id"] = decoded.identifier

    sql = CARD_SQL
    if predicates:
        sql += " AND " + " AND ".join(predicates)
    sql += f" ORDER BY {column} {direction.upper()} NULLS LAST, p.product_id LIMIT %(limit)s"
    params["limit"] = page_size + 1

    rows = fetch_all(connection, sql, params)
    scopes = effective_scopes(connection, principal)

    has_more = len(rows) > page_size
    visible = rows[:page_size]
    next_cursor = None
    if has_more and visible:
        last = visible[-1]
        next_cursor = Cursor(
            sort_value=_cursor_value(last, sort), identifier=last["product_id"]
        ).encode()

    total = fetch_one(
        connection,
        "SELECT count(*) AS total FROM data_product p WHERE p.tenant_id = %s",
        (tenant,),
    )
    page = Page(
        items=[_card(row, scopes) for row in visible],
        next_cursor=next_cursor,
        total=int(total["total"]) if total else None,
    )
    computed_facets = facet_module.compute(
        connection, tenant, facet_module.PRODUCT_FACETS, "data_product", "p",
        filters.selected(), rubric,
    )
    return page, computed_facets


def _exists_predicate(code: str, placeholder: str) -> str:
    return {
        "endpoint": f"EXISTS (SELECT 1 FROM endpoint e2 WHERE e2.product_id = p.product_id "
                    f"AND e2.surface = ANY({placeholder}))",
        "kpi": f"EXISTS (SELECT 1 FROM kpi_definition k2 "
               f"WHERE k2.source_of_record = p.product_id AND k2.kpi_id = ANY({placeholder}))",
        "quality_band": f"q.band = ANY({placeholder})",
    }[code]


def _cursor_value(row: dict[str, Any], sort: str) -> Any:
    value = {
        "name": row["name"],
        "quality": row["quality_composite"],
        "adoption": row["active_consumers"],
        "recent": row["updated_at"],
    }[sort]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is not None and not isinstance(value, str | int):
        return float(value)
    return value


def get_card(
    connection: psycopg.Connection[Any], tenant: str, product_id: str, principal: Principal,
    rubric: Rubric,
) -> dict[str, Any] | None:
    adoption_window = int(rubric.number("adoption_window_days"))
    rows = fetch_all(
        connection,
        CARD_SQL + " AND p.product_id = %(product_id)s",
        {"tenant": tenant, "adoption_window": adoption_window, "product_id": product_id},
    )
    if not rows:
        return None
    return _card(rows[0], effective_scopes(connection, principal))
