"""gen:types — the canonical model to TypeScript types shared with the portal.

The portal imports these rather than declaring its own shapes, so a column added
to the model reaches the UI as a type error rather than as a runtime undefined.
Enumerations come from the CHECK constraints on the model, which is what keeps a
status string in the portal from drifting from the status the database accepts.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.generators import canonical_model as model
from scripts.generators.header import content_digest, write_generated
from scripts.generators.model import Column, Table

SOURCE = "scripts/generators/canonical_model.py"
VERSION = "1.0.0"

SQL_TO_TS = {
    "TEXT": "string",
    "BOOLEAN": "boolean",
    "INT": "number",
    "BIGINT": "number",
    "NUMERIC": "number",
    "DATE": "string",
    "TIMESTAMPTZ": "string",
    "JSONB": "unknown",
    "TEXT[]": "string[]",
    "tsvector": "string",
}

IN_LIST = re.compile(r"\bIN\s*\((?P<values>(?:\s*'[^']*'\s*,?)+)\)", re.IGNORECASE)
QUOTED = re.compile(r"'([^']*)'")


def _pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _ts_type(column: Column) -> str:
    base = column.type.split("(")[0].strip()
    if base.startswith("vector"):
        return "number[]"
    if column.check:
        match = IN_LIST.search(column.check)
        if match and column.check.strip().startswith(column.name):
            values = QUOTED.findall(match.group("values"))
            if values:
                return " | ".join(f"'{value}'" for value in values)
    return SQL_TO_TS.get(base, "string")


def _interface(table: Table) -> str:
    lines = [f"/** {table.purpose} */"]
    if table.invariants:
        lines.append(f"/* invariants: {', '.join(table.invariants)} */")
    lines.append(f"export interface {_pascal(table.name)} {{")
    for column in table.all_columns():
        optional = "?" if column.null and not column.primary_key else ""
        rendered = _ts_type(column)
        if column.null and not column.primary_key:
            rendered = f"{rendered} | null"
        comment = f" // {column.comment}" if column.comment else ""
        lines.append(f"  {_camel(column.name)}{optional}: {rendered};{comment}")
    lines.append("}")
    return "\n".join(lines)


def _enums() -> str:
    """Column CHECK ... IN lists become named unions the portal can switch on."""
    seen: dict[str, str] = {}
    for table in model.ALL_TABLES:
        for column in table.all_columns():
            if not column.check:
                continue
            match = IN_LIST.search(column.check)
            if not match or not column.check.strip().startswith(column.name):
                continue
            values = QUOTED.findall(match.group("values"))
            if not values:
                continue
            name = _pascal(f"{table.name}_{column.name}")
            seen[name] = " | ".join(f"'{value}'" for value in values)
    lines = ["/** Enumerations, taken from the CHECK constraints on the canonical model. */"]
    for name in sorted(seen):
        lines.append(f"export type {name} = {seen[name]};")
    return "\n".join(lines)


PY_CONSTANTS_TEMPLATE = """\
\"\"\"Constants that are properties of the canonical model rather than configuration.

A service that needs the embedding dimension must agree with the column type, so
the value is emitted from the model rather than written twice.
\"\"\"

EMBEDDING_DIMENSIONS = {dimensions}
"""

VECTOR_COLUMN = re.compile(r"vector\((?P<dimensions>\d+)\)")


def _embedding_dimensions() -> int:
    for table in model.ALL_TABLES:
        for column in table.all_columns():
            match = VECTOR_COLUMN.match(column.type)
            if match:
                return int(match.group("dimensions"))
    raise RuntimeError("the canonical model declares no vector column")


def generate(output_root: Path) -> list[Path]:
    groups: dict[str, list[Table]] = {}
    for table in model.ALL_TABLES:
        groups.setdefault(table.group, []).append(table)

    bodies = {
        group: "\n\n".join(_interface(table) for table in tables)
        for group, tables in groups.items()
    }
    enums = _enums()
    digest = content_digest(enums, *[bodies[group] for group in sorted(bodies)])

    written: list[Path] = []
    for group in sorted(bodies):
        path = output_root / "types" / f"{group}.ts"
        write_generated(
            path, bodies[group], source=SOURCE, version=VERSION, digest=digest
        )
        written.append(path)

    enum_path = output_root / "types" / "enums.ts"
    write_generated(enum_path, enums, source=SOURCE, version=VERSION, digest=digest)
    written.append(enum_path)

    index = "\n".join(
        [f"export * from './{group}';" for group in sorted(bodies)] + ["export * from './enums';"]
    )
    index_path = output_root / "types" / "index.ts"
    write_generated(index_path, index, source=SOURCE, version=VERSION, digest=digest)
    written.append(index_path)

    constants_path = output_root / "types" / "model_constants.py"
    write_generated(
        constants_path,
        PY_CONSTANTS_TEMPLATE.format(dimensions=_embedding_dimensions()),
        source=SOURCE,
        version=VERSION,
        digest=digest,
    )
    written.append(constants_path)

    return written
