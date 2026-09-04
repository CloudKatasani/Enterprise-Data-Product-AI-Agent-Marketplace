"""A small declarative DSL for the canonical model.

BUILD.md section 9 feeds ``gen:ddl`` from "canonical model definition +
manifests". The canonical model definition is *this* DSL plus
``canonical_model.py``; it is generator input, not application source, so the
numeric-literal rule does not apply to it (it is not under ``services/``).

The DSL exists so three things are structural rather than remembered:

  * ``tenant_scoped`` adds ``tenant_id`` and emits RLS enable + policy, so a
    table cannot silently ship without one (section 6.2);
  * ``append_only`` emits the ``REVOKE UPDATE, DELETE`` grant (``DELETE`` only
    where ``stamped_in_place`` says a trigger polices the updates), so
    immutability is
    a property of the declaration rather than of reviewer attention (rule 6);
  * column and constraint order is fixed by declaration order, which is what
    makes regeneration byte-identical (I9).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The application role the API connects as. Append-only tables revoke write
# verbs from it; RLS policies are written against it.
APP_ROLE = "app_role"

# Session setting that carries the caller's tenant into RLS policy evaluation.
TENANT_SETTING = "app.tenant_id"


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    null: bool = True
    primary_key: bool = False
    default: str | None = None
    references: str | None = None
    on_delete: str | None = None
    check: str | None = None
    unique: bool = False
    comment: str | None = None

    def render(self) -> str:
        parts = [self.name, self.type]
        if self.primary_key:
            parts.append("PRIMARY KEY")
        if not self.null and not self.primary_key:
            parts.append("NOT NULL")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        if self.references is not None:
            parts.append(f"REFERENCES {self.references}")
            if self.on_delete is not None:
                parts.append(f"ON DELETE {self.on_delete}")
        if self.unique:
            parts.append("UNIQUE")
        if self.check is not None:
            parts.append(f"CHECK ({self.check})")
        return " ".join(parts)


@dataclass(frozen=True)
class Index:
    columns: str
    unique: bool = False
    where: str | None = None
    name: str | None = None
    using: str | None = None

    def render(self, table: str, ordinal: int) -> str:
        name = self.name or f"{table}_idx_{ordinal}"
        unique = "UNIQUE " if self.unique else ""
        using = f" USING {self.using}" if self.using else ""
        where = f" WHERE {self.where}" if self.where else ""
        return f"CREATE {unique}INDEX {name} ON {table}{using} ({self.columns}){where};"


@dataclass(frozen=True)
class Table:
    name: str
    group: str
    purpose: str
    columns: list[Column]
    tenant_scoped: bool = True
    append_only: bool = False
    # A table whose rows are history but whose *ending* is stamped in place: a
    # grant is closed by writing `revoked_at` beside it rather than by a new
    # row, and a trigger polices exactly which columns may move. DELETE stays
    # revoked either way. Without this distinction the table-level revoke of
    # UPDATE would make the trigger unreachable — the grant could never be
    # revoked at all, which is the opposite of what append-only is for.
    stamped_in_place: bool = False
    table_checks: list[str] = field(default_factory=list)
    unique_together: list[tuple[str, ...]] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)

    def all_columns(self) -> list[Column]:
        """Declared columns, with ``tenant_id`` inserted after the primary key."""
        if not self.tenant_scoped:
            return list(self.columns)
        if any(column.name == "tenant_id" for column in self.columns):
            return list(self.columns)
        result: list[Column] = []
        inserted = False
        for column in self.columns:
            result.append(column)
            if column.primary_key and not inserted:
                result.append(
                    Column(
                        "tenant_id",
                        "TEXT",
                        null=False,
                        references="tenant(tenant_id)",
                        comment="Tenant that owns this row; carried into every RLS policy.",
                    )
                )
                inserted = True
        if not inserted:
            result.insert(
                0, Column("tenant_id", "TEXT", null=False, references="tenant(tenant_id)")
            )
        return result


@dataclass(frozen=True)
class RawBlock:
    """A hand-written SQL block (function, trigger, view) carried by the model."""

    name: str
    group: str
    purpose: str
    sql: str
    invariants: list[str] = field(default_factory=list)
