"""Rubric resolution.

Every weight, threshold, band and target in the system is a row in
``rubric_criterion``, addressed by a dotted path inside a ``rubric_version``.
Consumers resolve a rubric by version id at read time and record that id with
anything they produce, so a score can be replayed exactly (BUILD.md section 8).

This module contains no numbers. That is the point of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one


class RubricNotFound(LookupError):
    """A rubric or version that does not exist. Never falls back to a default."""


class CriterionNotFound(LookupError):
    """A path that no criterion answers to.

    Raised rather than returning a default: rule 7 is to fail closed, and a
    silently defaulted weight is the exact failure the no-magic-numbers rule
    exists to prevent.
    """


@dataclass(frozen=True)
class Band:
    code: str
    label: str
    minimum: Decimal


@dataclass(frozen=True)
class Rubric:
    """A resolved rubric version. Immutable, and it knows its own identity."""

    rubric_version_id: str
    code: str
    semver: str
    source_hash: str
    payload: dict[str, Any]
    _numeric: dict[tuple[str, str | None], Decimal]
    _text: dict[tuple[str, str | None], str]

    def number(self, path: str, *, scope: str | None = None) -> Decimal:
        key = (path, scope)
        if key in self._numeric:
            return self._numeric[key]
        if scope is not None and (path, None) in self._numeric:
            return self._numeric[(path, None)]
        raise CriterionNotFound(
            f"rubric {self.code}@{self.semver} has no numeric criterion at {path!r}"
            + (f" for scope {scope!r}" if scope else "")
        )

    def text(self, path: str, *, scope: str | None = None) -> str:
        key = (path, scope)
        if key in self._text:
            return self._text[key]
        if scope is not None and (path, None) in self._text:
            return self._text[(path, None)]
        raise CriterionNotFound(
            f"rubric {self.code}@{self.semver} has no text criterion at {path!r}"
        )

    def flag(self, path: str, *, scope: str | None = None) -> bool:
        return self.text(path, scope=scope) == "true"

    def has(self, path: str, *, scope: str | None = None) -> bool:
        key = (path, scope)
        return key in self._numeric or key in self._text

    def weights(self, prefix: str, *, scope: str | None = None) -> dict[str, Decimal]:
        """Every numeric criterion directly under ``prefix``, keyed by its last segment."""
        collected: dict[str, Decimal] = {}
        for (path, criterion_scope), value in self._numeric.items():
            if criterion_scope not in (None, scope):
                continue
            if not path.startswith(f"{prefix}."):
                continue
            remainder = path[len(prefix) + 1 :]
            if "." in remainder:
                continue
            collected[remainder] = value
        overrides = {
            path[len(prefix) + 1 :]: value
            for (path, criterion_scope), value in self._numeric.items()
            if criterion_scope == scope
            and scope is not None
            and path.startswith(f"{prefix}.")
            and "." not in path[len(prefix) + 1 :]
        }
        collected.update(overrides)
        if not collected:
            raise CriterionNotFound(
                f"rubric {self.code}@{self.semver} has no criteria under {prefix!r}"
            )
        return collected

    def bands(self) -> list[Band]:
        """Bands ordered highest minimum first, which is resolution order."""
        codes = sorted(
            {
                path.split(".")[1]
                for (path, _), _ in self._numeric.items()
                if path.startswith("bands.") and path.endswith(".min")
            }
        )
        resolved = [
            Band(
                code=code,
                label=self.text(f"bands.{code}.label"),
                minimum=self.number(f"bands.{code}.min"),
            )
            for code in codes
        ]
        return sorted(resolved, key=lambda band: band.minimum, reverse=True)

    def resolve_band(self, score: Decimal) -> Band:
        for band in self.bands():
            if score >= band.minimum:
                return band
        raise CriterionNotFound(
            f"rubric {self.code}@{self.semver} has no band covering a score of {score}"
        )


def rubric_from_rows(version: dict[str, Any], criteria: list[dict[str, Any]]) -> Rubric:
    """Build a resolved rubric from rows that came from anywhere.

    Used by the golden suite, which pins a rubric version to a fixture file so a
    historical score can be replayed without a database — and therefore without
    the possibility of the rubric having moved underneath it.
    """
    return _rows_to_rubric(version, criteria)


def _rows_to_rubric(version: dict[str, Any], criteria: list[dict[str, Any]]) -> Rubric:
    numeric: dict[tuple[str, str | None], Decimal] = {}
    text: dict[tuple[str, str | None], str] = {}
    for row in criteria:
        key = (row["path"], row["scope"])
        if row["numeric_value"] is not None:
            numeric[key] = Decimal(str(row["numeric_value"]))
        if row["text_value"] is not None:
            text[key] = row["text_value"]
    return Rubric(
        rubric_version_id=version["rubric_version_id"],
        code=version["code"],
        semver=version["semver"],
        source_hash=version["source_hash"],
        payload=version["payload"],
        _numeric=numeric,
        _text=text,
    )


_CURRENT_SQL = """
SELECT rv.rubric_version_id, rv.semver, rv.source_hash, rv.payload, r.code
FROM rubric_version rv
JOIN rubric r ON r.rubric_id = rv.rubric_id
WHERE r.code = %s AND rv.superseded_at IS NULL
ORDER BY rv.effective_from DESC
LIMIT 1
"""

_BY_ID_SQL = """
SELECT rv.rubric_version_id, rv.semver, rv.source_hash, rv.payload, r.code
FROM rubric_version rv
JOIN rubric r ON r.rubric_id = rv.rubric_id
WHERE rv.rubric_version_id = %s
"""

_CRITERIA_SQL = """
SELECT path, kind, numeric_value, text_value, scope
FROM rubric_criterion
WHERE rubric_version_id = %s
ORDER BY path, scope NULLS FIRST
"""


def load_current(connection: psycopg.Connection[Any], code: str) -> Rubric:
    """The rubric version in force now. Used when producing a new score."""
    version = fetch_one(connection, _CURRENT_SQL, (code,))
    if version is None:
        raise RubricNotFound(f"no active version of rubric {code!r}")
    criteria = fetch_all(connection, _CRITERIA_SQL, (version["rubric_version_id"],))
    return _rows_to_rubric(version, criteria)


def load_version(connection: psycopg.Connection[Any], rubric_version_id: str) -> Rubric:
    """A specific historical version. Used when replaying a score (I9, M5.4)."""
    version = fetch_one(connection, _BY_ID_SQL, (rubric_version_id,))
    if version is None:
        raise RubricNotFound(f"no rubric version {rubric_version_id!r}")
    criteria = fetch_all(connection, _CRITERIA_SQL, (rubric_version_id,))
    return _rows_to_rubric(version, criteria)
