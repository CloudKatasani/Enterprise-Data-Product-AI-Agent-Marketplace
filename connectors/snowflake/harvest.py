"""M3.2-M3.5 — harvest passes from a Snowflake session into the canonical model.

Each pass reads through the session (so the read-only guard applies) and writes
through the marketplace's own connection. Nothing here writes to the platform.

What is harvested, and where it lands:

  metadata  information_schema + tag_references -> data_product_column, and the
            classification tags that make ``sensitivity_tier`` derive (I5)
  lineage   object_dependencies + access_history -> lineage_edge, each edge
            carrying confidence and a rationale (rule 4)
  usage     query_history -> usage_event and usage_daily_agg, including the
            permission-denied rate that leads entitlement gaps (15.6)
  cost      warehouse_metering_history -> cost_allocation, apportioned to
            products by their share of bytes scanned on the warehouse
  quality   data_quality_monitoring_results -> quality_result, matched to the
            product's declared rules

Every harvested inference records ``confidence`` and ``rationale``: lineage from
a declared dependency is certain, lineage inferred from access history is not,
and the difference is visible in the row rather than lost.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any

import psycopg

from connectors.base import HarvestResult, Session
from connectors.snowflake import queries
from services.common.rubrics import Rubric

# Windows, confidences and the credit rate all resolve from the platform_harvest
# rubric at read time (I10). Confidence in particular is an inference threshold:
# a declared dependency is certain, an access-history edge is not, and the
# difference has to be reviewable without reading this file.
RUBRIC_CODE = "platform_harvest"

SNOWFLAKE_TYPE_TO_MANIFEST = {
    "TEXT": "string", "VARCHAR": "string", "NUMBER": "number", "FLOAT": "number",
    "BOOLEAN": "boolean", "DATE": "date", "TIMESTAMP_NTZ": "timestamp",
    "TIMESTAMP_TZ": "timestamp", "TIMESTAMP_LTZ": "timestamp", "ARRAY": "array",
}

CLASSIFICATION_TAG = "GOVERNANCE.CLASSIFICATION"
SENSITIVITY_TAG = "GOVERNANCE.SENSITIVITY"
MASKING_POLICY_TAG = "GOVERNANCE.MASKING_POLICY"


def _split_qualified(name: str) -> tuple[str, str, str]:
    """Split ``database.schema.object`` without assuming how many parts arrived."""
    database, _, rest = str(name).partition(".")
    schema, _, leaf = rest.partition(".")
    return database, schema, leaf or schema or database


def _schema_for(product_id: str) -> str:
    return product_id.replace("-", "_").upper()


def _product_for_object(object_schema: str, products: dict[str, str]) -> str | None:
    return products.get(object_schema.upper())


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _lookback(rubric: Rubric, pass_name: str) -> int:
    return int(rubric.number(f"lookback_days.{pass_name}"))


def _product_index(marketplace: psycopg.Connection[Any], tenant: str) -> dict[str, str]:
    """Platform schema name -> product id, for the products in scope."""
    with marketplace.cursor() as cursor:
        cursor.execute("SELECT product_id FROM data_product WHERE tenant_id = %s", (tenant,))
        return {_schema_for(row["product_id"]): row["product_id"] for row in cursor.fetchall()}


def harvest_metadata(
    session: Session, marketplace: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> HarvestResult:
    """M3.2 — columns, types, comments and classification tags."""
    del rubric  # the metadata pass reads current state; it has no window
    products = _product_index(marketplace, tenant)
    counts: dict[str, int] = defaultdict(int)

    for object_schema, product_id in sorted(products.items()):
        columns = session.query(queries.COLUMNS, (object_schema,))
        tags = session.query(queries.TAG_REFERENCES, (object_schema,))

        classification: dict[str, list[str]] = defaultdict(list)
        sensitivity: dict[str, str] = {}
        masking: dict[str, str] = {}
        for tag in tags:
            column = tag["column_name"]
            if tag["tag_name"] == CLASSIFICATION_TAG:
                classification[column].append(tag["tag_value"])
            elif tag["tag_name"] == SENSITIVITY_TAG:
                sensitivity[column] = tag["tag_value"]
            elif tag["tag_name"] == MASKING_POLICY_TAG:
                # Which policy is actually attached on the platform. A classified
                # column without one is a hard blocker on the product's score,
                # so this is observed rather than assumed from the manifest.
                masking[column] = tag["tag_value"]

        with marketplace.cursor() as cursor:
            for column in columns:
                name = column["column_name"]
                cursor.execute(
                    """
                    INSERT INTO data_product_column (
                      column_id, tenant_id, product_id, name, business_name, data_type,
                      nullable, classification, sensitivity_code, description,
                      masking_policy, ordinal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id, name) DO UPDATE SET
                      data_type = EXCLUDED.data_type,
                      nullable = EXCLUDED.nullable,
                      classification = EXCLUDED.classification,
                      sensitivity_code = EXCLUDED.sensitivity_code,
                      description = EXCLUDED.description,
                      masking_policy = EXCLUDED.masking_policy,
                      ordinal = EXCLUDED.ordinal
                    """,
                    (
                        f"COL-{product_id}-{name}", tenant, product_id, name,
                        name.replace("_", " ").title(),
                        SNOWFLAKE_TYPE_TO_MANIFEST.get(column["data_type"], "string"),
                        column["is_nullable"] == "YES",
                        sorted(classification.get(name, [])),
                        sensitivity.get(name, "internal"),
                        column["comment"] or f"Harvested column {name}.",
                        masking.get(name),
                        column["ordinal_position"],
                    ),
                )
                counts["data_product_column"] += 1

    return HarvestResult(dict(counts))


def harvest_lineage(
    session: Session, marketplace: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> HarvestResult:
    """M3.3 — declared dependencies and inferred access-history edges."""
    lookback_days = _lookback(rubric, "lineage")
    declared_confidence = rubric.number("confidence.declared_dependency")
    inferred_confidence = rubric.number("confidence.access_history_inference")
    products = _product_index(marketplace, tenant)
    counts: dict[str, int] = defaultdict(int)

    with marketplace.cursor() as cursor:
        cursor.execute("SELECT source_id FROM source_system WHERE tenant_id = %s", (tenant,))
        known_sources = {
            row["source_id"].replace("-", "_"): row["source_id"] for row in cursor.fetchall()
        }

    for object_schema, product_id in sorted(products.items()):
        declared = session.query(queries.OBJECT_DEPENDENCIES, (object_schema,))
        with marketplace.cursor() as cursor:
            for dependency in declared:
                referenced = dependency["referenced_object_name"]
                source_id = known_sources.get(referenced)
                if source_id is None:
                    continue
                cursor.execute(
                    """
                    INSERT INTO lineage_edge (
                      lineage_id, tenant_id, upstream_type, upstream_id, downstream_type,
                      downstream_id, relationship, harvested_from, confidence, rationale
                    ) VALUES (%s, %s, 'source_system', %s, 'data_product', %s,
                              'derives_from', %s, %s, %s)
                    ON CONFLICT (upstream_type, upstream_id, downstream_type, downstream_id,
                                 relationship)
                    DO UPDATE SET confidence = EXCLUDED.confidence,
                                  rationale = EXCLUDED.rationale,
                                  harvested_at = now()
                    """,
                    (
                        f"LIN-{source_id}-{product_id}", tenant, source_id, product_id,
                        f"{session.platform}:object_dependencies",
                        declared_confidence,
                        f"The platform's own dependency graph records {product_id} as "
                        f"referencing {source_id} by name.",
                    ),
                )
                counts["lineage_edge"] += 1

    # Access history is weaker evidence: it shows what a query touched, not what
    # the product is defined from, so its edges carry a lower confidence and say why.
    accesses = session.query(queries.ACCESS_HISTORY, (_since(lookback_days),))
    inferred: set[tuple[str, str]] = set()
    for access in accesses:
        direct = access["direct_objects_accessed"] or []
        base = access["base_objects_accessed"] or []
        touched_products = {
            product
            for entry in direct
            if (product := _product_for_object(_object_schema(entry), products)) is not None
        }
        touched_sources = {_object_leaf(entry) for entry in base}
        for product_id in sorted(touched_products):
            for source_name in sorted(touched_sources):
                inferred.add((source_name, product_id))

    with marketplace.cursor() as cursor:
        cursor.execute("SELECT source_id FROM source_system WHERE tenant_id = %s", (tenant,))
        sources = {
            row["source_id"].replace("-", "_"): row["source_id"] for row in cursor.fetchall()
        }
        for source_name, product_id in sorted(inferred):
            source_id = sources.get(source_name)
            if source_id is None:
                continue
            cursor.execute(
                """
                INSERT INTO lineage_edge (
                  lineage_id, tenant_id, upstream_type, upstream_id, downstream_type,
                  downstream_id, relationship, harvested_from, confidence, rationale
                ) VALUES (%s, %s, 'source_system', %s, 'data_product', %s, 'reads', %s, %s, %s)
                ON CONFLICT (upstream_type, upstream_id, downstream_type, downstream_id,
                             relationship) DO NOTHING
                """,
                (
                    f"LIN-ACC-{source_id}-{product_id}", tenant, source_id, product_id,
                    f"{session.platform}:access_history", inferred_confidence,
                    f"Queries reading {product_id} in the last {lookback_days} days also "
                    f"touched {source_id}. Inferred from access history, not declared.",
                ),
            )
            counts["lineage_edge"] += 1

    return HarvestResult(dict(counts))


def _object_schema(entry: dict[str, Any]) -> str:
    return _split_qualified(entry.get("objectName", ""))[1]


def _object_leaf(entry: dict[str, Any]) -> str:
    return _split_qualified(entry.get("objectName", ""))[2]


def harvest_usage(
    session: Session, marketplace: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> HarvestResult:
    """M3.4 — query history into usage_event and usage_daily_agg."""
    denied_prefix = rubric.text("denied_error_prefix")
    products = _product_index(marketplace, tenant)
    counts: dict[str, int] = defaultdict(int)
    since = _since(_lookback(rubric, "usage"))

    daily: dict[tuple[str, Any], dict[str, Any]] = {}

    for object_schema, product_id in sorted(products.items()):
        for row in session.query(queries.QUERY_HISTORY, (since, object_schema)):
            denied = str(row.get("error_code") or "").startswith(denied_prefix)
            outcome = "denied" if denied else (
                "ok" if row["execution_status"] == "SUCCESS" else "error"
            )
            purpose = _purpose_from_tag(row.get("query_tag"))
            with marketplace.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO usage_event (
                      event_id, tenant_id, asset_type, asset_id, principal_id, surface,
                      event_name, purpose_code, rows_returned, outcome, occurred_at
                    ) VALUES (%s, %s, 'data_product', %s, NULL, 'sql',
                              'data_product.queried', %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (f"UE-{row['query_id']}", tenant, product_id, purpose,
                     row["rows_produced"], outcome, row["query_start_time"]),
                )
                counts["usage_event"] += 1

            key = (product_id, row["query_start_time"].date())
            bucket = daily.setdefault(
                key,
                {"consumers": set(), "teams": set(), "queries": 0, "denied": 0, "rows": 0},
            )
            bucket["consumers"].add(row["user_name"])
            bucket["teams"].add(row["role_name"])
            bucket["queries"] += 1
            bucket["denied"] += 1 if denied else 0
            bucket["rows"] += row["bytes_scanned"] or 0

    with marketplace.cursor() as cursor:
        for (product_id, activity_date), bucket in sorted(daily.items()):
            cursor.execute(
                """
                INSERT INTO usage_daily_agg (
                  agg_id, tenant_id, asset_type, asset_id, activity_date, active_consumers,
                  distinct_teams, query_count, denied_count, rows_scanned
                ) VALUES (%s, %s, 'data_product', %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_type, asset_id, activity_date) DO UPDATE SET
                  active_consumers = EXCLUDED.active_consumers,
                  distinct_teams = EXCLUDED.distinct_teams,
                  query_count = EXCLUDED.query_count,
                  denied_count = EXCLUDED.denied_count,
                  rows_scanned = EXCLUDED.rows_scanned
                """,
                (f"AGG-{product_id}-{activity_date}", tenant, product_id, activity_date,
                 len(bucket["consumers"]), len(bucket["teams"]), bucket["queries"],
                 bucket["denied"], bucket["rows"]),
            )
            counts["usage_daily_agg"] += 1

    return HarvestResult(dict(counts))


def _purpose_from_tag(query_tag: str | None) -> str | None:
    for part in (query_tag or "").split(";"):
        key, _, value = part.partition("=")
        if key.strip() == "purpose" and value.strip():
            return value.strip()
    return None


def harvest_cost(
    session: Session, marketplace: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> HarvestResult:
    """M3.4 — warehouse credits apportioned to products by share of bytes scanned.

    Apportionment is stated rather than hidden: a product's share of a day's
    credits is its share of the bytes scanned on that warehouse that day. The
    ``source`` column records the method so a figure can be argued with.
    """
    counts: dict[str, int] = defaultdict(int)
    since = _since(_lookback(rubric, "cost"))
    credit_rate_usd = rubric.number("cost.credit_rate_usd")
    apportionment = rubric.text("cost.apportionment")

    metering = session.query(queries.WAREHOUSE_METERING, (since,))
    credits_by_day: dict[Any, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in metering:
        credits_by_day[row["start_time"].date()] += Decimal(str(row["credits_used"]))

    with marketplace.cursor() as cursor:
        cursor.execute(
            "SELECT asset_id, activity_date, rows_scanned FROM usage_daily_agg "
            "WHERE tenant_id = %s AND asset_type = 'data_product' AND activity_date >= %s",
            (tenant, since.date()),
        )
        usage = [dict(row) for row in cursor.fetchall()]

    scanned_by_day: dict[Any, int] = defaultdict(int)
    for row in usage:
        scanned_by_day[row["activity_date"]] += row["rows_scanned"] or 0

    with marketplace.cursor() as cursor:
        for row in usage:
            asset_id = row["asset_id"]
            activity_date = row["activity_date"]
            rows_scanned = row["rows_scanned"]
            total = scanned_by_day[activity_date]
            if total == 0:
                continue
            share = Decimal(rows_scanned or 0) / Decimal(total)
            credits = credits_by_day.get(activity_date, Decimal("0"))
            cursor.execute(
                """
                INSERT INTO cost_allocation (
                  allocation_id, tenant_id, asset_type, asset_id, cost_date, query_usd,
                  platform_usd, tier, source
                ) VALUES (%s, %s, 'data_product', %s, %s, %s, %s, 'live', %s)
                ON CONFLICT (asset_type, asset_id, cost_date, tier) DO UPDATE SET
                  query_usd = EXCLUDED.query_usd,
                  platform_usd = EXCLUDED.platform_usd,
                  source = EXCLUDED.source
                """,
                (f"CA-{asset_id}-{activity_date}", tenant, asset_id, activity_date,
                 # Rounded down: apportioned cost must never total above what
                 # the platform actually metered.
                 (credits * share * credit_rate_usd).quantize(
                     Decimal("0.000001"), rounding=ROUND_DOWN
                 ),
                 Decimal("0"),
                 f"{session.platform}:warehouse_metering_history "
                 f"apportioned by {apportionment}"),
            )
            counts["cost_allocation"] += 1

    return HarvestResult(dict(counts))


def harvest_quality(
    session: Session, marketplace: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> HarvestResult:
    """M3.5 — data metric function results into quality_result.

    A result is only recorded against a rule the product actually declares. A
    metric running on the platform that no manifest declares is skipped rather
    than invented: the manifest is the source of truth for what is measured.
    """
    products = _product_index(marketplace, tenant)
    counts: dict[str, int] = defaultdict(int)

    with marketplace.cursor() as cursor:
        cursor.execute(
            "SELECT rule_id, product_id, rule_type, threshold_pct, tolerance_minutes, "
            "       target_columns FROM quality_rule WHERE tenant_id = %s",
            (tenant,),
        )
        rules = [dict(row) for row in cursor.fetchall()]

    by_metric: dict[tuple[str, str], dict[str, Any]] = {}
    for declared in rules:
        metric = f"GOVERNANCE.DMF_{declared['rule_type'].upper()}"
        target = ",".join(declared["target_columns"] or [])
        by_metric[(declared["product_id"], f"{metric}|{target}")] = declared

    for row in session.query(queries.DMF_RESULTS, (_since(_lookback(rubric, "quality")),)):
        object_schema = _split_qualified(row["table_name"])[1]
        product_id = _product_for_object(object_schema, products)
        if product_id is None:
            continue
        key = (product_id, f"{row['metric_name']}|{row['argument_names'] or ''}")
        rule = by_metric.get(key)
        if rule is None:
            continue
        observed = Decimal(str(row["value"]))

        # A rule is either a percentage against a threshold, or a measure against
        # a tolerance where lower is better — freshness lag being the case that
        # matters here. Recording which one it was is what lets the scoring
        # engine normalise it correctly rather than assume.
        if rule["threshold_pct"] is not None:
            observed_pct: Decimal | None = observed
            observed_value: Decimal | None = None
            observed_unit: str | None = None
            passed = observed >= Decimal(str(rule["threshold_pct"]))
        elif rule["tolerance_minutes"] is not None:
            observed_pct = None
            observed_value = observed
            observed_unit = "minutes"
            passed = observed <= Decimal(str(rule["tolerance_minutes"]))
        else:
            observed_pct = None
            observed_value = observed
            observed_unit = None
            passed = True

        with marketplace.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO quality_result (
                  result_id, tenant_id, rule_id, product_id, observed_pct, observed_value,
                  observed_unit, passed, source, evaluated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'dmf', %s)
                ON CONFLICT (result_id) DO UPDATE SET
                  observed_pct = EXCLUDED.observed_pct,
                  observed_value = EXCLUDED.observed_value,
                  observed_unit = EXCLUDED.observed_unit,
                  passed = EXCLUDED.passed
                """,
                (f"QRES-{rule['rule_id']}-{row['measurement_time'].date()}", tenant,
                 rule["rule_id"], product_id, observed_pct, observed_value, observed_unit,
                 passed, row["measurement_time"]),
            )
            counts["quality_result"] += 1

    return HarvestResult(dict(counts))


def harvest_all(
    session: Session, marketplace: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> HarvestResult:
    """Every pass, in dependency order: cost apportionment needs usage first."""
    return (
        harvest_metadata(session, marketplace, tenant, rubric)
        + harvest_lineage(session, marketplace, tenant, rubric)
        + harvest_usage(session, marketplace, tenant, rubric)
        + harvest_cost(session, marketplace, tenant, rubric)
        + harvest_quality(session, marketplace, tenant, rubric)
    )
