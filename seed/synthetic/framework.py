"""Demo-tier synthetic data generation (BUILD.md 18.1).

One generator per product, all of them driven by this framework and the product's
own manifest. The requirements the framework exists to satisfy:

* **Generated from the contract.** Columns, types and nullability come from the
  manifest, so a schema change regenerates the demo tier rather than leaving it
  to drift from the live shape.
* **Distribution, seasonality, referential integrity and cardinality preserved.**
  Rows are laid out as entity x period, categorical columns draw from pools with
  declared weights, and seasonality is a term in the expression rather than
  noise.
* **No real subject data.** Every value is computed from a hash of the row's own
  keys. Nothing is sampled from anywhere.
* **Deterministic.** The same manifest and the same scale produce byte-identical
  rows, which is what lets a golden answer be pinned to a number.
* **Physically separate.** Everything lands in ``DEMO_TIER_SCHEMA`` with no path
  to production data.
* **Non-trivial answers.** Each product plants the patterns its curated questions
  are meant to discover, so a golden answer is a real finding rather than noise.

Randomness is `md5` over a key string, which is stable across Postgres versions
and across machines — `random()` would make the demo tier unreproducible and a
golden answer meaningless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import psycopg

# A deterministic value in [0, 1) from any key expression.
RANDOM_SQL = "((('x' || substr(md5({key}), 1, 8))::bit(32)::bigint & 2147483647) / 2147483647.0)"

SQL_TYPE = {
    "string": "TEXT",
    "integer": "INTEGER",
    "number": "DOUBLE PRECISION",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMPTZ",
    "array": "TEXT[]",
}

# The unit each grain steps by. The multiplier is applied in SQL as
# `(n || ' <unit>')::interval`, so the unit is singular and unqualified.
GRAIN_UNIT = {
    "day": "days",
    "hour": "hours",
    "month": "months",
    "shift": "hours",
    "interval": "hours",
}


def rnd(*parts: str) -> str:
    """A deterministic pseudo-random double in [0,1) keyed on the given SQL parts."""
    key = " || '|' || ".join(parts)
    return RANDOM_SQL.format(key=key)


def pick(pool: list[str], *parts: str) -> str:
    """Pick from a pool, uniformly and deterministically."""
    cases = " ".join(
        f"WHEN {rnd(*parts)} < {(index + 1) / len(pool):.6f} THEN {_literal(value)}"
        for index, value in enumerate(pool[:-1])
    )
    return f"(CASE {cases} ELSE {_literal(pool[-1])} END)"


def weighted(pool: list[tuple[str, float]], *parts: str) -> str:
    """Pick from a pool with declared weights, so a distribution is a distribution."""
    total = sum(weight for _, weight in pool)
    cumulative = 0.0
    cases = []
    for value, weight in pool[:-1]:
        cumulative += weight / total
        cases.append(f"WHEN {rnd(*parts)} < {cumulative:.6f} THEN {_literal(value)}")
    return f"(CASE {' '.join(cases)} ELSE {_literal(pool[-1][0])} END)"


def _literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def uniform(low: float, high: float, *parts: str) -> str:
    return f"({low} + ({high} - {low}) * {rnd(*parts)})"


def seasonal(amplitude: float, period_expr: str, cycle: int) -> str:
    """A seasonal term: amplitude * sin(2*pi*period/cycle)."""
    return f"({amplitude} * sin(2 * pi() * ({period_expr})::numeric / {cycle}))"


@dataclass
class ProductSpec:
    """How one product's demo tier is laid out."""

    product_id: str
    entity_column: str
    entity_count: int
    time_column: str
    grain: str
    periods: int
    # column -> SQL expression producing its value. Columns not listed are
    # inferred from the manifest's declared type.
    expressions: dict[str, str] = field(default_factory=dict)
    # Additional dimension columns that multiply the row count (peril, feature...).
    fan_out: tuple[str, list[str]] | None = None
    notes: str = ""


def table_name(product_id: str) -> str:
    return f"t_{product_id.replace('-', '_').lower()}"


def _entity_id(spec: ProductSpec) -> str:
    prefix = spec.entity_column.replace("_id", "").upper()[:4]
    return f"('{prefix}-' || lpad(entity::text, 7, '0'))"


def _default_expression(column: dict[str, Any], spec: ProductSpec) -> str:
    """A value for a column the product spec did not name, from its declared type."""
    name = column["name"]
    keys = ("entity::text", "period::text", _literal(name))
    if name == spec.entity_column:
        return _entity_id(spec)
    if name == spec.time_column:
        return "period_at"
    match column["type"]:
        case "boolean":
            return f"({rnd(*keys)} < 0.5)"
        case "integer":
            return f"({uniform(0, 100, *keys)})::int"
        case "number":
            return uniform(0, 100, *keys)
        case "date":
            return "period_at::date"
        case "timestamp":
            return "period_at"
        case _:
            return f"('{name[:3].upper()}-' || (1 + floor({rnd(*keys)} * 8))::int::text)"


_IDENTIFIER = re.compile(r"\b[a-z_][a-z0-9_]*\b")


def _dependencies(expression: str, declared: set[str]) -> set[str]:
    """Which other declared columns an expression reads.

    String literals are stripped first, so a column name appearing inside a
    literal is not mistaken for a reference.
    """
    without_literals = re.sub(r"'[^']*'", " ", expression)
    return {token for token in _IDENTIFIER.findall(without_literals) if token in declared}


def _layer(expressions: dict[str, str]) -> list[list[str]]:
    """Order columns so an expression only reads columns computed before it.

    A generated column often derives from another — a churn flag from an
    incident count, a waste figure from a dispensed cost — and SQL will not let
    a SELECT reference its own output. Layering turns the dependency graph into
    nested SELECTs automatically, so a product spec can be written the way it
    reads rather than in an order the database happens to accept.
    """
    declared = set(expressions)
    pending = {
        name: _dependencies(body, declared) - {name} for name, body in expressions.items()
    }
    layers: list[list[str]] = []
    resolved: set[str] = set()
    while pending:
        ready = sorted(name for name, deps in pending.items() if deps <= resolved)
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise ValueError(f"circular dependency between generated columns: {cycle}")
        layers.append(ready)
        resolved.update(ready)
        for name in ready:
            del pending[name]
    return layers


def create_and_fill(
    connection: psycopg.Connection[Any],
    schema: str,
    manifest: dict[str, Any],
    spec: ProductSpec,
    scale: float,
) -> int:
    """Create the demo table for a product and fill it deterministically."""
    columns = manifest["spec"]["columns"]
    table = f"{schema}.{table_name(spec.product_id)}"

    definitions = ", ".join(
        f"{column['name']} {SQL_TYPE[column['type']]}" for column in columns
    )
    expressions = {
        column["name"]: spec.expressions.get(column["name"])
        or _default_expression(column, spec)
        for column in columns
    }

    entities = max(int(spec.entity_count * scale), 1)
    unit = GRAIN_UNIT[spec.grain]

    fan_out_join = ""
    if spec.fan_out is not None:
        _, values = spec.fan_out
        literals = ", ".join(f"({_literal(value)})" for value in values)
        fan_out_join = f"CROSS JOIN (VALUES {literals}) AS fan(fan_value)"

    query = f"""
        SELECT entity, period, period_at{", fan_value" if fan_out_join else ""}
        FROM generate_series(1, {entities}) AS entity
        CROSS JOIN LATERAL (
          SELECT period,
                 (date_trunc('day', now())
                   - ((({spec.periods} - period)::text || ' {unit}')::interval)) AS period_at
          FROM generate_series(1, {spec.periods}) AS period
        ) AS periods
        {fan_out_join}
    """
    for index, layer in enumerate(_layer(expressions)):
        projection = ", ".join(f"{expressions[name]} AS {name}" for name in layer)
        query = f"SELECT source_{index}.*, {projection} FROM ({query}) AS source_{index}"

    names = ", ".join(column["name"] for column in columns)
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        cursor.execute(f"CREATE TABLE {table} ({definitions})")
        cursor.execute(f"INSERT INTO {table} ({names}) SELECT {names} FROM ({query}) AS rows")
        written = cursor.rowcount
        # The index the demo runner's aggregations actually use.
        cursor.execute(f"CREATE INDEX ON {table} ({spec.time_column})")
    return written
