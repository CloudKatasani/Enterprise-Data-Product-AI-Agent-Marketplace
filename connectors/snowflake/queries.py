"""The read statements the Snowflake connector issues.

Each is a module-level constant so the whole read surface of the connector can
be reviewed in one file, and so ``tests/kill`` can assert that every statement
the connector can issue passes the read-only guard.
"""

from __future__ import annotations

# --- M3.2 metadata -------------------------------------------------------
COLUMNS = """
SELECT table_catalog, table_schema, table_name, column_name, ordinal_position,
       data_type, is_nullable, comment
FROM information_schema.columns
WHERE table_schema = %s
ORDER BY table_name, ordinal_position
"""

TABLES = """
SELECT table_catalog, table_schema, table_name, table_type, row_count, comment,
       created, last_altered
FROM information_schema.tables
WHERE table_schema = %s
ORDER BY table_name
"""

TAG_REFERENCES = """
SELECT object_database, object_schema, object_name, column_name, tag_name, tag_value
FROM snowflake.account_usage.tag_references
WHERE object_schema = %s AND column_name IS NOT NULL
ORDER BY object_name, column_name, tag_name
"""

# --- M3.3 lineage --------------------------------------------------------
OBJECT_DEPENDENCIES = """
SELECT referencing_database, referencing_schema, referencing_object_name,
       referenced_database, referenced_schema, referenced_object_name,
       dependency_type
FROM snowflake.account_usage.object_dependencies
WHERE referencing_schema = %s
ORDER BY referencing_object_name, referenced_object_name
"""

ACCESS_HISTORY = """
SELECT query_id, query_start_time, user_name,
       direct_objects_accessed, objects_modified, base_objects_accessed
FROM snowflake.account_usage.access_history
WHERE query_start_time >= %s
ORDER BY query_start_time
"""

# --- M3.4 usage and cost -------------------------------------------------
QUERY_HISTORY = """
SELECT query_id, query_start_time, user_name, role_name, warehouse_name,
       database_name, schema_name, query_type, execution_status, error_code,
       rows_produced, bytes_scanned, total_elapsed_time, query_tag
FROM snowflake.account_usage.query_history
WHERE query_start_time >= %s AND schema_name = %s
ORDER BY query_start_time
"""

WAREHOUSE_METERING = """
SELECT start_time, end_time, warehouse_name, credits_used, credits_used_compute,
       credits_used_cloud_services
FROM snowflake.account_usage.warehouse_metering_history
WHERE start_time >= %s
ORDER BY start_time
"""

# --- M3.5 quality --------------------------------------------------------
DMF_REFERENCES = """
SELECT metric_name, ref_entity_name, ref_entity_domain, ref_arguments, schedule
FROM snowflake.account_usage.data_metric_function_references
WHERE ref_entity_name IS NOT NULL
ORDER BY ref_entity_name, metric_name
"""

DMF_RESULTS = """
SELECT measurement_time, metric_name, table_name, argument_names, value
FROM snowflake.local.data_quality_monitoring_results
WHERE measurement_time >= %s
ORDER BY measurement_time
"""

ALL_STATEMENTS = (
    COLUMNS,
    TABLES,
    TAG_REFERENCES,
    OBJECT_DEPENDENCIES,
    ACCESS_HISTORY,
    QUERY_HISTORY,
    WAREHOUSE_METERING,
    DMF_REFERENCES,
    DMF_RESULTS,
)
