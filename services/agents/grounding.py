"""Grounding validation, in the API layer, before serialisation.

BUILD.md section 10.2 states the rule as a hard one: grounding is validated
after the runtime returns and before the response is serialised, and an
ungrounded answer is never sent to a client. That placement is the point. A
runtime can be wrong — the whole reason the marketplace adapts runtimes rather
than authoring agents is that it does not control what one of them will say —
so the check has to sit where every answer must pass, whichever runtime produced
it, and it has to withhold rather than annotate.

What "grounded" means here, precisely:

* every number the prose asserts appears in the answer's claims, and
* every claim resolves to a citation the caller was entitled to read.

Numbers inside labels are not claims. ``DP-TEL-001`` and ``2026-08-31`` name
things; demanding a citation for the ``001`` in a product id would make the
check noise, and a check that cries wolf gets turned off. So label-shaped tokens
are removed before any number is read out of the text.

A measure's own name is a label too. "30+ Delinquency Rate" and "30-Day
Readmission Rate" carry a number that describes the definition rather than the
data, and an answer that mentions the measure it computed has not thereby made
a claim about thirty. The names the answer names are removed first.

The failure mode this guards against is specific and worth naming: a model that
writes a fluent sentence containing a figure it did not compute. That sentence
is the most dangerous output the system can produce, because it is the most
believable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.agent_runtime.base import Answer

NUMERIC = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
HAS_LETTER = re.compile(r"[A-Za-z]")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TRIM = ".,;:!?%$()[]\"'"


@dataclass(frozen=True)
class Verdict:
    """Why an answer is or is not groundable, in terms a caller can act on."""

    grounded: bool
    uncited_numbers: tuple[str, ...]
    unsupported_claims: tuple[str, ...]

    @property
    def uncited_count(self) -> int:
        return len(self.uncited_numbers) + len(self.unsupported_claims)

    def reason(self) -> str:
        parts = []
        if self.uncited_numbers:
            parts.append(
                "the narrative states " + ", ".join(self.uncited_numbers)
                + " with no matching claim"
            )
        if self.unsupported_claims:
            parts.append(
                "these claims resolve to no citation: " + ", ".join(self.unsupported_claims)
            )
        return "; ".join(parts)


def numbers_in(text: str) -> set[str]:
    """Numbers the text asserts, with label-shaped tokens removed first."""
    kept = []
    for token in text.split():
        bare = token.strip(TRIM)
        if not bare or HAS_LETTER.search(bare) or ISO_DATE.fullmatch(bare):
            continue
        kept.append(bare)
    return {match.replace(",", "") for token in kept for match in NUMERIC.findall(token)}


def _renderings(value: Decimal) -> set[str]:
    """Every way a claim could legitimately appear in prose.

    Compared as strings rather than parsed, because what the reader sees is the
    string: a claim of 1.360 does not ground a sentence saying 1.36 unless the
    composer chose to write 1.36.
    """
    plain = f"{value:,}".replace(",", "")
    return {
        plain,
        str(value),
        str(abs(value)),
        plain.rstrip("0").rstrip(".") if "." in plain else plain,
    }


def _label_numbers(names: list[str]) -> set[str]:
    """Numbers that belong to a measure's name rather than to its value.

    Taken from the names rather than cut out of the prose. Cutting a name out
    of the text splits the identifiers it appears inside — ``KPI-SAIDI-061``
    becomes ``KPI- -061`` — and hands the scanner a number that was never
    written. Subtracting the name's own digits from what the prose states
    cannot do that.
    """
    return {
        match.replace(",", "")
        for name in names
        for match in NUMERIC.findall(name)
    }


def check(answer: Answer) -> Verdict:
    claimed: set[str] = set()
    for value in answer.claims.values():
        claimed |= _renderings(value)

    stated = numbers_in(answer.headline) | numbers_in(answer.narrative)
    stated -= _label_numbers(answer.measure_names)
    uncited = sorted(
        number
        for number in stated
        if number not in claimed
        and (number.rstrip("0").rstrip(".") if "." in number else number) not in claimed
    )

    # A claim with no citation behind it is ungrounded even if the prose is
    # silent about it, because the table and the visual carry it too.
    unsupported = sorted(answer.claims) if answer.claims and not answer.citations else []

    return Verdict(
        grounded=not uncited and not unsupported,
        uncited_numbers=tuple(uncited),
        unsupported_claims=tuple(unsupported),
    )
