"""A stand-in data platform for local runs and CI.

The Snowflake connector reads a fixed set of ACCOUNT_USAGE and INFORMATION_SCHEMA
views. This seeder materialises those *shapes* in a separate Postgres schema and
fills them from the product manifests, so the harvest path — the real statements,
the real read-only guard, the real mapping into the canonical model — runs end to
end without a Snowflake account.

It is a stand-in platform, not a stand-in connector. Nothing in ``connectors/``
knows it exists.

The schema is physically separate from the marketplace's own tables and holds no
row-level customer data: only object metadata, aggregated query history and
quality results (rule 5).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from scripts.seeders._base import load_directory

# The sandbox stands in for a platform, so its shapes are the platform's.
DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.sf_tables (
  table_catalog TEXT, table_schema TEXT, table_name TEXT, table_type TEXT,
  row_count BIGINT, comment TEXT, created TIMESTAMPTZ, last_altered TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS {schema}.sf_columns (
  table_catalog TEXT, table_schema TEXT, table_name TEXT, column_name TEXT,
  ordinal_position INT, data_type TEXT, is_nullable TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS {schema}.tag_references (
  object_database TEXT, object_schema TEXT, object_name TEXT, column_name TEXT,
  tag_name TEXT, tag_value TEXT
);
CREATE TABLE IF NOT EXISTS {schema}.object_dependencies (
  referencing_database TEXT, referencing_schema TEXT, referencing_object_name TEXT,
  referenced_database TEXT, referenced_schema TEXT, referenced_object_name TEXT,
  dependency_type TEXT
);
CREATE TABLE IF NOT EXISTS {schema}.access_history (
  query_id TEXT, query_start_time TIMESTAMPTZ, user_name TEXT,
  direct_objects_accessed JSONB, objects_modified JSONB, base_objects_accessed JSONB
);
CREATE TABLE IF NOT EXISTS {schema}.query_history (
  query_id TEXT, query_start_time TIMESTAMPTZ, user_name TEXT, role_name TEXT,
  warehouse_name TEXT, database_name TEXT, schema_name TEXT, query_type TEXT,
  execution_status TEXT, error_code TEXT, rows_produced BIGINT, bytes_scanned BIGINT,
  total_elapsed_time BIGINT, query_tag TEXT
);
CREATE TABLE IF NOT EXISTS {schema}.warehouse_metering_history (
  start_time TIMESTAMPTZ, end_time TIMESTAMPTZ, warehouse_name TEXT,
  credits_used NUMERIC, credits_used_compute NUMERIC, credits_used_cloud_services NUMERIC
);
CREATE TABLE IF NOT EXISTS {schema}.data_metric_function_references (
  metric_name TEXT, ref_entity_name TEXT, ref_entity_domain TEXT,
  ref_arguments TEXT, schedule TEXT
);
CREATE TABLE IF NOT EXISTS {schema}.data_quality_monitoring_results (
  measurement_time TIMESTAMPTZ, metric_name TEXT, table_name TEXT,
  argument_names TEXT, value NUMERIC
);
"""

TABLES = (
    "sf_tables", "sf_columns", "tag_references", "object_dependencies", "access_history",
    "query_history", "warehouse_metering_history", "data_metric_function_references",
    "data_quality_monitoring_results",
)

CATALOG = "MARKETPLACE"
WAREHOUSE = "MKT_HARVEST_WH"

# Deterministic pseudo-random draw: the sandbox must produce the same numbers on
# every run so a harvested figure is reproducible (I9 in spirit).
def _draw(seed: str, lower: int, upper: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    span = upper - lower + 1
    return lower + (int.from_bytes(digest[:8], "big") % span)


def _object_name(product_id: str) -> str:
    return f"T_{product_id.replace('-', '_').upper()}"


def _schema_name(product_id: str) -> str:
    return product_id.replace("-", "_").upper()


def _sql_type(manifest_type: str) -> str:
    return {
        "string": "TEXT", "integer": "NUMBER", "number": "NUMBER", "boolean": "BOOLEAN",
        "date": "DATE", "timestamp": "TIMESTAMP_NTZ", "array": "ARRAY",
    }[manifest_type]


def seed(connection: psycopg.Connection[Any], tenant: str, schema: str) -> int:
    products = load_directory("products")
    now = datetime.now(UTC).replace(microsecond=0)
    written = 0

    with connection.cursor() as cursor:
        cursor.execute(DDL.format(schema=schema))
        for table in TABLES:
            cursor.execute(f"TRUNCATE {schema}.{table}")

        for product in products:
            metadata = product["metadata"]
            spec = product["spec"]
            product_id = metadata["id"]
            object_schema = _schema_name(product_id)
            object_name = _object_name(product_id)
            rows = spec["demo_tier"]["rows_target"]

            cursor.execute(
                f"INSERT INTO {schema}.sf_tables VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (CATALOG, object_schema, object_name, "BASE TABLE", rows,
                 spec["purpose"], now - timedelta(days=_draw(product_id, 200, 900)), now),
            )
            written += 1

            for ordinal, column in enumerate(spec["columns"], start=1):
                cursor.execute(
                    f"INSERT INTO {schema}.sf_columns VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (CATALOG, object_schema, object_name, column["name"], ordinal,
                     _sql_type(column["type"]), "YES" if column["nullable"] else "NO",
                     column["description"]),
                )
                written += 1
                for classification in column.get("classification", []):
                    cursor.execute(
                        f"INSERT INTO {schema}.tag_references VALUES (%s,%s,%s,%s,%s,%s)",
                        (CATALOG, object_schema, object_name, column["name"],
                         "GOVERNANCE.CLASSIFICATION", classification),
                    )
                    written += 1
                cursor.execute(
                    f"INSERT INTO {schema}.tag_references VALUES (%s,%s,%s,%s,%s,%s)",
                    (CATALOG, object_schema, object_name, column["name"],
                     "GOVERNANCE.SENSITIVITY", column["sensitivity"]),
                )
                written += 1

            for source in spec["upstream_sources"]:
                cursor.execute(
                    f"INSERT INTO {schema}.object_dependencies VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (CATALOG, object_schema, object_name, CATALOG, "RAW",
                     source.replace("-", "_"), "BY_NAME"),
                )
                written += 1

            # Usage: a deterministic spread of consumers and queries per day.
            consumers = _draw(f"{product_id}-consumers", 4, 60)
            for day in range(30):
                day_start = now - timedelta(days=day)
                query_count = _draw(f"{product_id}-{day}-queries", 5, 400)
                for index in range(min(query_count, consumers)):
                    seed_key = f"{product_id}-{day}-{index}"
                    denied = _draw(seed_key + "-denied", 1, 100) <= 3
                    cursor.execute(
                        f"INSERT INTO {schema}.query_history "
                        f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (f"q-{seed_key}", day_start, f"USER_{index:03d}", "MKT_CONSUMER",
                         WAREHOUSE, CATALOG, object_schema, "SELECT",
                         "FAIL" if denied else "SUCCESS", "003001" if denied else None,
                         0 if denied else _draw(seed_key + "-rows", 10, 50000),
                         _draw(seed_key + "-bytes", 1000, 90000000),
                         _draw(seed_key + "-ms", 120, 9000),
                         f"purpose=analytics;product={product_id}"),
                    )
                    written += 1
                    cursor.execute(
                        f"INSERT INTO {schema}.access_history VALUES (%s,%s,%s,%s,%s,%s)",
                        (f"q-{seed_key}", day_start, f"USER_{index:03d}",
                         psycopg.types.json.Jsonb(
                             [{"objectName": f"{CATALOG}.{object_schema}.{object_name}"}]),
                         psycopg.types.json.Jsonb([]),
                         psycopg.types.json.Jsonb(
                             [{"objectName": f"{CATALOG}.RAW.{s.replace('-', '_')}"}
                              for s in spec["upstream_sources"]])),
                    )
                    written += 1

            # Quality: one DMF reference and one result per rule, per day.
            for rule in spec["quality_rules"]:
                target = rule.get("column") or ",".join(rule.get("columns", []))
                cursor.execute(
                    f"INSERT INTO {schema}.data_metric_function_references "
                    f"VALUES (%s,%s,%s,%s,%s)",
                    (f"GOVERNANCE.DMF_{rule['rule'].upper()}",
                     f"{CATALOG}.{object_schema}.{object_name}", "TABLE", target,
                     "USING CRON 0 6 * * * UTC"),
                )
                written += 1
                for day in range(7):
                    key = f"{product_id}-{rule['id']}-{day}"
                    ceiling = rule.get("threshold_pct") or 100
                    shortfall = _draw(key, 0, 300) / 100
                    cursor.execute(
                        f"INSERT INTO {schema}.data_quality_monitoring_results "
                        f"VALUES (%s,%s,%s,%s,%s)",
                        (now - timedelta(days=day),
                         f"GOVERNANCE.DMF_{rule['rule'].upper()}",
                         f"{CATALOG}.{object_schema}.{object_name}", target,
                         max(0.0, float(ceiling) - shortfall)),
                    )
                    written += 1

        for day in range(30):
            start = now - timedelta(days=day)
            cursor.execute(
                f"INSERT INTO {schema}.warehouse_metering_history VALUES (%s,%s,%s,%s,%s,%s)",
                (start, start + timedelta(hours=1), WAREHOUSE,
                 _draw(f"credits-{day}", 20, 400) / 10,
                 _draw(f"compute-{day}", 15, 380) / 10,
                 _draw(f"cloud-{day}", 1, 30) / 10),
            )
            written += 1

    del tenant  # the sandbox platform is not tenant-aware; the harvester is
    return written
