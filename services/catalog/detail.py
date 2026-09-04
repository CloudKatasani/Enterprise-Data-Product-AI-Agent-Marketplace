"""The eight product detail tabs (BUILD.md section 12).

Overview | Schema | Quality | Contract | Endpoints | Lineage & Mesh | Consumption | Value

Every tab is assembled from real metadata. Where a fact does not exist yet, the
tab returns ``state: "empty"`` with a ``why`` that names what would produce it —
which is a different thing from an empty box, and is what stops a detail page
from looking broken while a product is still being onboarded.

Where a tab needs a grant the caller does not hold, it returns
``state: "partial_permission"`` with the exact scope and a pre-filled request
link. The metadata is still there: seeing an asset you cannot yet query is the
normal state of a catalog, not an error.
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.principal import Principal, effective_scopes

TABS = (
    "overview", "schema", "quality", "contract", "endpoints", "lineage_mesh",
    "consumption", "value",
)


def _tab(
    state: str, data: Any = None, *, why: str | None = None, required_scope: str | None = None,
    asset_id: str | None = None, surface: str = "sql",
) -> dict[str, Any]:
    document: dict[str, Any] = {"state": state, "data": data}
    if why:
        document["why"] = why
    if required_scope:
        document["required_scope"] = required_scope
        document["request_access_url"] = (
            f"/requests/new/access?asset={asset_id}&surface={surface}"
        )
    return document


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _decimal(value: Any) -> float | None:
    return float(value) if value is not None else None


def overview_tab(connection: psycopg.Connection[Any], product_id: str) -> dict[str, Any]:
    row = fetch_one(
        connection,
        """
        SELECT p.*, owner.display_name AS owner_name, owner.email AS owner_email,
               ou.name AS owner_team,
               array_remove(array_agg(DISTINCT k.kpi_id), NULL) AS certified_kpis,
               array_remove(array_agg(DISTINCT l.upstream_id), NULL) AS upstream_sources
        FROM data_product p
        JOIN party owner ON owner.party_id = p.owner_party_id
        LEFT JOIN org_unit ou ON ou.org_unit_id = owner.org_unit_id
        LEFT JOIN kpi_definition k ON k.source_of_record = p.product_id
        LEFT JOIN lineage_edge l ON l.downstream_id = p.product_id
             AND l.upstream_type = 'source_system' AND l.relationship = 'derives_from'
        WHERE p.product_id = %s
        GROUP BY p.product_id, owner.party_id, ou.org_unit_id
        """,
        (product_id,),
    )
    if row is None:
        return _tab("empty", why="this product has no record")
    return _tab(
        "populated",
        {
            "product_id": row["product_id"],
            "name": row["name"],
            "purpose": row["purpose"],
            "grain": row["grain"],
            "history_months": row["history_months"],
            "known_limitations": row["known_limitations"],
            "certification": row["certification"],
            "sensitivity": row["sensitivity_tier"],
            "tier": row["tier"],
            "current_version": row["current_version"],
            "industry": row["industry_code"],
            "domain": row["domain_code"],
            "archetype": row["archetype_code"],
            "owner": {
                "party_id": row["owner_party_id"],
                "name": row["owner_name"],
                "email": row["owner_email"],
                "team": row["owner_team"],
            },
            "certified_kpis": list(row["certified_kpis"]),
            "upstream_sources": list(row["upstream_sources"]),
            "updated_at": _iso(row["updated_at"]),
        },
    )


def schema_tab(
    connection: psycopg.Connection[Any], product_id: str, scopes: frozenset[str]
) -> dict[str, Any]:
    """Column list. Classification is always visible; a masked column says so.

    Seeing that a PII column exists is not a disclosure — it is what lets a
    consumer decide whether to request access at all. What the column *contains*
    needs a grant, and the data plane enforces that, not this tab.
    """
    rows = fetch_all(
        connection,
        "SELECT name, business_name, data_type, nullable, classification, sensitivity_code, "
        "       description, masking_policy, ordinal "
        "FROM data_product_column WHERE product_id = %s ORDER BY ordinal",
        (product_id,),
    )
    if not rows:
        return _tab(
            "empty",
            why="no columns have been declared or harvested for this product yet; "
                "publish a manifest version or run the platform harvest",
        )

    pii_scope = f"dp:{product_id}:read_pii"
    holds_pii = pii_scope in scopes
    columns = []
    for row in rows:
        classified = bool(row["classification"])
        columns.append(
            {
                "name": row["name"],
                "business_name": row["business_name"],
                "data_type": row["data_type"],
                "nullable": row["nullable"],
                "classification": list(row["classification"]),
                "sensitivity": row["sensitivity_code"],
                "description": row["description"],
                "masked_for_caller": classified and not holds_pii,
                "masking_policy": row["masking_policy"],
            }
        )
    state = "partial_permission" if any(c["masked_for_caller"] for c in columns) else "populated"
    return _tab(
        state,
        {"columns": columns, "column_count": len(columns)},
        required_scope=pii_scope if state == "partial_permission" else None,
        asset_id=product_id,
        why="classified columns are listed but their values are masked for this caller"
        if state == "partial_permission"
        else None,
    )


def quality_tab(connection: psycopg.Connection[Any], product_id: str) -> dict[str, Any]:
    """Current composite, its history, and the rule results that produced it."""
    current = fetch_one(
        connection,
        "SELECT * FROM quality_score_snapshot WHERE product_id = %s "
        "ORDER BY computed_at DESC LIMIT 1",
        (product_id,),
    )
    history = fetch_all(
        connection,
        "SELECT snapshot_id, composite, band, rubric_version_id, blocker_applied, computed_at "
        "FROM quality_score_snapshot WHERE product_id = %s ORDER BY computed_at DESC",
        (product_id,),
    )
    results = fetch_all(
        connection,
        "SELECT r.result_id, r.rule_id, q.dimension, q.rule_type, q.severity, q.threshold_pct, "
        "       r.observed_pct, r.passed, r.source, r.evaluated_at "
        "FROM quality_result r JOIN quality_rule q ON q.rule_id = r.rule_id "
        "WHERE r.product_id = %s ORDER BY r.evaluated_at DESC, r.rule_id",
        (product_id,),
    )
    rules = fetch_all(
        connection,
        "SELECT rule_id, dimension, rule_type, target_columns, threshold_pct, severity, enabled "
        "FROM quality_rule WHERE product_id = %s ORDER BY rule_id",
        (product_id,),
    )

    if current is None:
        return _tab(
            "empty",
            {
                "rules": [dict(rule) for rule in rules],
                "contributing_results": [_result(row) for row in results],
            },
            why="no quality snapshot has been computed yet; the scoring job produces one "
                "once rule results exist for this product",
        )

    return _tab(
        "populated",
        {
            "current": {
                "snapshot_id": current["snapshot_id"],
                "composite": _decimal(current["composite"]),
                "band": current["band"],
                "rubric_version_id": current["rubric_version_id"],
                "blocker_applied": current["blocker_applied"],
                "dimensions": {
                    dimension: _decimal(current[dimension])
                    for dimension in (
                        "completeness", "accuracy", "freshness", "consistency", "validity",
                        "uniqueness",
                    )
                },
                "evidence_ref": current["evidence_ref"],
                "computed_at": _iso(current["computed_at"]),
            },
            "history": [
                {
                    "snapshot_id": row["snapshot_id"],
                    "composite": _decimal(row["composite"]),
                    "band": row["band"],
                    "rubric_version_id": row["rubric_version_id"],
                    "blocker_applied": row["blocker_applied"],
                    "computed_at": _iso(row["computed_at"]),
                }
                for row in history
            ],
            "rules": [dict(rule) for rule in rules],
            "contributing_results": [_result(row) for row in results],
        },
    )


def _result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": row["result_id"],
        "rule_id": row["rule_id"],
        "dimension": row["dimension"],
        "rule_type": row["rule_type"],
        "severity": row["severity"],
        "threshold_pct": _decimal(row["threshold_pct"]),
        "observed_pct": _decimal(row["observed_pct"]),
        "passed": row["passed"],
        "source": row["source"],
        "evaluated_at": _iso(row["evaluated_at"]),
    }


def contract_tab(connection: psycopg.Connection[Any], product_id: str) -> dict[str, Any]:
    """The contract in force, its guarantees, and how earlier versions differed."""
    versions = fetch_all(
        connection,
        "SELECT * FROM data_contract_version WHERE product_id = %s "
        "ORDER BY effective_from DESC",
        (product_id,),
    )
    if not versions:
        return _tab("empty", why="this product has published no data contract")

    active = next((v for v in versions if v["status"] == "active"), versions[0])
    guarantees = fetch_all(
        connection,
        "SELECT dimension, target_text, target_numeric, unit, measurement_window, "
        "       measured_at_grain, reference_system "
        "FROM contract_guarantee WHERE contract_version_id = %s ORDER BY dimension",
        (active["contract_version_id"],),
    )
    conformance = fetch_all(
        connection,
        "SELECT q.dimension, count(*) FILTER (WHERE r.passed) AS met, count(*) AS evaluated "
        "FROM quality_result r JOIN quality_rule q ON q.rule_id = r.rule_id "
        "WHERE r.product_id = %s GROUP BY q.dimension ORDER BY q.dimension",
        (product_id,),
    )

    return _tab(
        "populated",
        {
            "active": {
                "contract_version_id": active["contract_version_id"],
                "semver": active["semver"],
                "schema_stability": active["schema_stability"],
                "deprecation": {
                    "notice_days": active["deprecation_notice_days"],
                    "minimum_parallel_run_days": active["minimum_parallel_run_days"],
                },
                "support": {
                    "hours": active["support_hours"],
                    "p1_response_minutes": active["p1_response_minutes"],
                    "on_call": active["on_call"],
                },
                "classification": {
                    "max_sensitivity": active["max_sensitivity"],
                    "contains_pii": active["contains_pii"],
                    "residency": list(active["residency"]),
                },
                "consumer_obligations": list(active["consumer_obligations"]),
                "breach_process": active["breach_process"],
                "effective_from": _iso(active["effective_from"]),
            },
            "guarantees": [
                {
                    "dimension": row["dimension"],
                    "target_text": row["target_text"],
                    "target_numeric": _decimal(row["target_numeric"]),
                    "unit": row["unit"],
                    "measurement_window": row["measurement_window"],
                    "measured_at_grain": row["measured_at_grain"],
                    "reference_system": row["reference_system"],
                }
                for row in guarantees
            ],
            "conformance": [
                {
                    "dimension": row["dimension"],
                    "met": int(row["met"]),
                    "evaluated": int(row["evaluated"]),
                }
                for row in conformance
            ],
            "versions": [
                {
                    "contract_version_id": row["contract_version_id"],
                    "semver": row["semver"],
                    "status": row["status"],
                    "effective_from": _iso(row["effective_from"]),
                }
                for row in versions
            ],
        },
    )


def endpoints_tab(
    connection: psycopg.Connection[Any], product_id: str, scopes: frozenset[str]
) -> dict[str, Any]:
    rows = fetch_all(
        connection,
        "SELECT surface, uri, auth_mode, required_scope, row_limit, documentation_ref "
        "FROM endpoint WHERE product_id = %s ORDER BY surface",
        (product_id,),
    )
    if not rows:
        return _tab("empty", why="this product publishes no consumption endpoints")

    endpoints = [
        {
            "surface": row["surface"],
            "uri": row["uri"],
            "auth_mode": row["auth_mode"],
            "required_scope": row["required_scope"],
            "row_limit": row["row_limit"],
            "documentation_ref": row["documentation_ref"],
            "granted": row["required_scope"] in scopes,
        }
        for row in rows
    ]
    state = "populated" if all(e["granted"] for e in endpoints) else "partial_permission"
    return _tab(
        state,
        {"endpoints": endpoints},
        required_scope=f"dp:{product_id}:read" if state == "partial_permission" else None,
        asset_id=product_id,
        why="the endpoints are listed; querying them needs a grant"
        if state == "partial_permission"
        else None,
    )


def lineage_mesh_tab(connection: psycopg.Connection[Any], product_id: str) -> dict[str, Any]:
    """Upstream, downstream and the mesh neighbourhood.

    Edges below the confidence floor are not returned: an inference nobody has
    reviewed does not get rendered (I6). The count of held edges is returned so
    the absence is visible rather than silent.
    """
    upstream = fetch_all(
        connection,
        "SELECT upstream_type, upstream_id, relationship, confidence, rationale, harvested_from "
        "FROM lineage_edge WHERE downstream_id = %s ORDER BY upstream_id",
        (product_id,),
    )
    downstream = fetch_all(
        connection,
        "SELECT downstream_type, downstream_id, relationship, confidence, rationale "
        "FROM lineage_edge WHERE upstream_id = %s ORDER BY downstream_id",
        (product_id,),
    )
    edges = fetch_all(
        connection,
        "SELECT edge_id, product_a, product_b, edge_type, strength, factors, confidence, "
        "       rationale, reviewed_by, computed_at "
        "FROM mesh_edge_data WHERE (product_a = %s OR product_b = %s) "
        "  AND (confidence >= %s OR reviewed_by IS NOT NULL) "
        "ORDER BY strength DESC",
        (product_id, product_id, _mesh_floor(connection)),
    )
    held = fetch_one(
        connection,
        "SELECT count(*) AS held FROM mesh_edge_data "
        "WHERE (product_a = %s OR product_b = %s) AND confidence < %s AND reviewed_by IS NULL",
        (product_id, product_id, _mesh_floor(connection)),
    )

    if not upstream and not downstream and not edges:
        return _tab(
            "empty",
            {"held_for_review": int(held["held"]) if held else 0},
            why="no lineage has been harvested and no mesh edge has been computed for this "
                "product yet; the nightly mesh job and the platform harvest produce both",
        )

    return _tab(
        "populated",
        {
            "upstream": [
                {
                    "type": row["upstream_type"],
                    "id": row["upstream_id"],
                    "relationship": row["relationship"],
                    "confidence": _decimal(row["confidence"]),
                    "rationale": row["rationale"],
                    "harvested_from": row["harvested_from"],
                }
                for row in upstream
            ],
            "downstream": [
                {
                    "type": row["downstream_type"],
                    "id": row["downstream_id"],
                    "relationship": row["relationship"],
                    "confidence": _decimal(row["confidence"]),
                    "rationale": row["rationale"],
                }
                for row in downstream
            ],
            "mesh": [
                {
                    "edge_id": row["edge_id"],
                    "neighbour": row["product_b"] if row["product_a"] == product_id
                    else row["product_a"],
                    "edge_type": row["edge_type"],
                    "strength": _decimal(row["strength"]),
                    "factors": row["factors"],
                    "confidence": _decimal(row["confidence"]),
                    "rationale": row["rationale"],
                    "reviewed_by": row["reviewed_by"],
                }
                for row in edges
            ],
            "held_for_review": int(held["held"]) if held else 0,
        },
    )


def _mesh_floor(connection: psycopg.Connection[Any]) -> float:
    from services.common.rubrics import load_current

    rubric = load_current(connection, "mesh_edges")
    return float(rubric.number("review_required_below_confidence"))


def consumption_tab(
    connection: psycopg.Connection[Any], product_id: str, principal: Principal,
    scopes: frozenset[str],
) -> dict[str, Any]:
    """Usage and adoption within the caller's scope.

    A consumer sees their own consumption; an owner or steward sees the whole
    picture. Nobody sees another consumer's queries, which is why the shape
    differs by role rather than being filtered client-side.
    """
    wide = principal.has_role("owner", "steward", "architect", "administrator")
    daily = fetch_all(
        connection,
        "SELECT activity_date, active_consumers, distinct_teams, query_count, denied_count, "
        "       rows_scanned FROM usage_daily_agg "
        "WHERE asset_type = 'data_product' AND asset_id = %s ORDER BY activity_date DESC",
        (product_id,),
    )
    if not daily:
        return _tab(
            "empty",
            why="no usage has been recorded for this product yet; adoption appears once the "
                "platform harvest sees queries against it",
        )

    document: dict[str, Any] = {
        "scope": "estate" if wide else "caller",
        "daily": [
            {
                "activity_date": row["activity_date"].isoformat(),
                "active_consumers": row["active_consumers"],
                "distinct_teams": row["distinct_teams"],
                "query_count": row["query_count"],
                "denied_count": row["denied_count"],
                "rows_scanned": row["rows_scanned"],
            }
            for row in daily
        ],
    }
    if wide:
        document["top_consumers"] = [
            dict(row)
            for row in fetch_all(
                connection,
                "SELECT principal_id, count(*) AS queries FROM usage_event "
                "WHERE asset_type = 'data_product' AND asset_id = %s AND principal_id IS NOT NULL "
                "GROUP BY principal_id ORDER BY queries DESC LIMIT "
                "(SELECT numeric_value::int FROM rubric_criterion c "
                " JOIN rubric_version v ON v.rubric_version_id = c.rubric_version_id "
                " JOIN rubric r ON r.rubric_id = v.rubric_id "
                " WHERE r.code = 'catalog_ranking' AND c.path = 'page_size.facet_values' "
                " AND v.superseded_at IS NULL LIMIT 1)",
                (product_id,),
            )
        ]
    state = "populated" if wide or f"dp:{product_id}:read" in scopes else "partial_permission"
    return _tab(
        state,
        document,
        required_scope=f"dp:{product_id}:read" if state == "partial_permission" else None,
        asset_id=product_id,
        why="estate-wide consumption is visible to the owner and steward roles"
        if state == "partial_permission"
        else None,
    )


def value_tab(connection: psycopg.Connection[Any], product_id: str) -> dict[str, Any]:
    """The value case, its assumptions and the measurements taken against it.

    Every assumption is shown with its sample size and date beside the figure
    derived from it (15.7): a number whose provenance is hidden is not evidence.
    """
    case = fetch_one(
        connection,
        "SELECT * FROM value_case WHERE asset_type = 'data_product' AND asset_id = %s",
        (product_id,),
    )
    if case is None:
        return _tab(
            "empty",
            why="no value case has been authored for this product; the publish gate requires "
                "one before an asset can be certified",
        )
    assumptions = fetch_all(
        connection,
        "SELECT text, numeric_value, unit, sample_size, source, dated FROM value_assumption "
        "WHERE value_case_id = %s ORDER BY dated DESC, text",
        (case["value_case_id"],),
    )
    measurements = fetch_all(
        connection,
        "SELECT period_start, period_end, answered_questions, acceptance_rate, deflected_hours, "
        "       deflected_value_usd, total_cost_usd, net_value_usd, value_ratio, "
        "       rubric_version_id, snapshot_ref, computed_at "
        "FROM value_measurement WHERE value_case_id = %s ORDER BY period_start DESC",
        (case["value_case_id"],),
    )
    return _tab(
        "populated" if measurements else "partial",
        {
            "case": {
                "value_case_id": case["value_case_id"],
                "business_outcome": case["business_outcome"],
                "baseline_method": case["baseline_method"],
                "baseline_captured": case["baseline_captured"].isoformat(),
                "benefit_model": case["benefit_model"],
                "attribution_confidence": case["attribution_confidence"],
                "rubric_version_id": case["rubric_version_id"],
                "last_reviewed": case["last_reviewed"].isoformat(),
                "review_due": case["review_due"].isoformat(),
            },
            "assumptions": [
                {
                    "text": row["text"],
                    "value": _decimal(row["numeric_value"]),
                    "unit": row["unit"],
                    "sample_size": row["sample_size"],
                    "source": row["source"],
                    "dated": row["dated"].isoformat(),
                }
                for row in assumptions
            ],
            "measurements": [
                {
                    "period_start": row["period_start"].isoformat(),
                    "period_end": row["period_end"].isoformat(),
                    "answered_questions": row["answered_questions"],
                    "acceptance_rate": _decimal(row["acceptance_rate"]),
                    "deflected_hours": _decimal(row["deflected_hours"]),
                    "deflected_value_usd": _decimal(row["deflected_value_usd"]),
                    "total_cost_usd": _decimal(row["total_cost_usd"]),
                    "net_value_usd": _decimal(row["net_value_usd"]),
                    "value_ratio": _decimal(row["value_ratio"]),
                    "rubric_version_id": row["rubric_version_id"],
                    "snapshot_ref": row["snapshot_ref"],
                    "computed_at": _iso(row["computed_at"]),
                }
                for row in measurements
            ],
        },
        why="the value case is authored but no measurement period has closed yet"
        if not measurements
        else None,
    )


def assemble(
    connection: psycopg.Connection[Any], product_id: str, principal: Principal
) -> dict[str, Any]:
    """All eight tabs. Assembled server-side so the portal makes one call."""
    scopes = effective_scopes(connection, principal)
    return {
        "overview": overview_tab(connection, product_id),
        "schema": schema_tab(connection, product_id, scopes),
        "quality": quality_tab(connection, product_id),
        "contract": contract_tab(connection, product_id),
        "endpoints": endpoints_tab(connection, product_id, scopes),
        "lineage_mesh": lineage_mesh_tab(connection, product_id),
        "consumption": consumption_tab(connection, product_id, principal, scopes),
        "value": value_tab(connection, product_id),
    }
