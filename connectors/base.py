"""Connector foundations.

Two guarantees are structural here rather than left to the implementation:

**I8 — connectors cannot write to any customer platform.** Every statement goes
through :func:`assert_read_only`, which parses the leading keyword and rejects
anything that is not a read. The check happens in this process, before a
statement reaches a driver, so the guarantee holds even against a platform whose
role grants were misconfigured. ``npm run test:kill`` proves it from the other
side by attempting a write on a real sandbox.

**Published permission manifest.** Each connector ships
``permissions.yaml`` naming every privilege its service principal needs and why.
The manifest is loaded and asserted against in tests, so a connector cannot
quietly start needing a privilege nobody reviewed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

CONNECTORS_ROOT = Path(__file__).resolve().parent

# Statement verbs a connector may issue. Anything outside this set is a write,
# a privilege change or a side effect, and is refused.
READ_VERBS = frozenset({"select", "with", "show", "describe", "desc", "explain", "list"})

# Verbs that are refused with a specific message, because seeing one of these
# means a code path is trying to change the customer's platform.
MUTATING_VERBS = frozenset(
    {
        "insert", "update", "delete", "merge", "truncate", "create", "drop", "alter",
        "grant", "revoke", "copy", "put", "remove", "call", "execute", "use", "set",
        "begin", "commit", "rollback", "comment", "rename", "undrop", "unset",
    }
)

_LEADING_COMMENTS = re.compile(r"(?s)^\s*(?:(?:--[^\n]*\n)|(?:/\*.*?\*/)|\s)+")
_STATEMENT_SPLIT = re.compile(r";\s*(?=\S)")


class ReadOnlyViolation(RuntimeError):
    """A connector attempted something other than a read (I8)."""


def _first_verb(statement: str) -> str:
    stripped = _LEADING_COMMENTS.sub("", statement).strip()
    if not stripped:
        return ""
    return stripped.split(maxsplit=1)[0].lower().strip("(")


def assert_read_only(statement: str) -> None:
    """Raise :class:`ReadOnlyViolation` unless every statement given is a read.

    Multiple statements in one string are rejected outright: a batch is how a
    write hides behind a read.
    """
    if _STATEMENT_SPLIT.search(statement.strip().rstrip(";")):
        raise ReadOnlyViolation(
            "connectors submit one statement at a time; a multi-statement batch is refused"
        )

    verb = _first_verb(statement)
    if verb in READ_VERBS:
        return
    if verb in MUTATING_VERBS:
        raise ReadOnlyViolation(
            f"connector attempted a {verb.upper()} statement; connectors are read-only (I8). "
            "Writing to a customer platform is done by the provisioning connector under an "
            "explicitly granted role, never by a harvester."
        )
    raise ReadOnlyViolation(
        f"connector attempted an unrecognised statement starting {verb.upper()!r}; "
        "only SELECT, WITH, SHOW, DESCRIBE, EXPLAIN and LIST are permitted (I8)"
    )


@dataclass(frozen=True)
class Privilege:
    """One privilege the connector's service principal requires."""

    privilege: str
    # "object", not "on": YAML 1.1 resolves a bare `on:` key to the boolean true,
    # which would silently drop the field the privilege applies to.
    object: str
    reason: str
    write: bool


@dataclass(frozen=True)
class PermissionManifest:
    connector: str
    principal: str
    role: str
    privileges: tuple[Privilege, ...]
    refuses: tuple[str, ...]

    @property
    def write_privileges(self) -> tuple[Privilege, ...]:
        return tuple(privilege for privilege in self.privileges if privilege.write)


def load_permission_manifest(connector: str) -> PermissionManifest:
    path = CONNECTORS_ROOT / connector / "permissions.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"connector {connector!r} ships no permissions.yaml; a connector must publish "
            "the privileges it needs before it can be enabled"
        )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PermissionManifest(
        connector=document["connector"],
        principal=document["principal"],
        role=document["role"],
        privileges=tuple(
            Privilege(
                privilege=entry["privilege"],
                object=entry["object"],
                reason=entry["reason"],
                write=bool(entry.get("write", False)),
            )
            for entry in document["privileges"]
        ),
        refuses=tuple(document.get("refuses", [])),
    )


class Session(Protocol):
    """A read-only session against a data platform."""

    platform: str

    def query(self, statement: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
        """Run one read statement and return its rows."""

    def close(self) -> None: ...


@dataclass
class HarvestResult:
    """What a harvest pass wrote, per canonical table."""

    counts: dict[str, int]

    def __add__(self, other: HarvestResult) -> HarvestResult:
        merged = dict(self.counts)
        for table, count in other.counts.items():
            merged[table] = merged.get(table, 0) + count
        return HarvestResult(merged)

    def total(self) -> int:
        return sum(self.counts.values())

    def render(self) -> Iterator[str]:
        for table in sorted(self.counts):
            yield f"{table}: {self.counts[table]}"
