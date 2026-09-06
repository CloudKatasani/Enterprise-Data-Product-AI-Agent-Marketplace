"""Does the estate already answer this? — supply assessment for new demand.

Duplicate detection (:mod:`services.workflow.demand`) asks whether a request
*reads like* something that already exists. That is a text question, and it is
the right one to ask at the moment somebody starts typing.

This asks a different and harder one: whether the estate can already *answer*
what is being asked. That is not a similarity — it is a coverage fact, and the
estate already holds every piece of it:

* a KPI names its ``source_of_record``, so the product that could answer it is
  known without asking anyone;
* ``agent_kpi_coverage`` says which agent answers which KPI, at which grains and
  slices, so "can anything answer this today" is a lookup rather than a guess;
* ``agent_product_binding`` says which agent reads which product, so the cost of
  extending one is knowable before anybody commits to it.

From those three the recommendation follows, and it is one of four:

``already_served``
    One existing agent already answers every KPI named. Building anything would
    add a second answer to a question that has one, which is the divergence the
    mesh exists to flag.
``enhance_agent``
    The data is published and certified, but no single agent covers all of it.
    The cheapest safe move is extending the agent that covers the most.
``enhance_product``
    A product is the right source of record for these measures but does not
    publish them yet. Extending it keeps one definition of the measure.
``build_new``
    Nothing in the estate is close. This is real new supply.

A recommendation that cannot be argued with is a recommendation that gets
ignored, so every one carries the evidence it was made from: which KPIs are
answered by what, which are not answered at all, and which questions the
estate could not place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric

ALREADY_SERVED_PATH = "supply_assessment.already_served_min"
ENHANCE_PATH = "supply_assessment.enhance_existing_min"
MIN_KPIS_PATH = "supply_assessment.min_kpis_for_recommendation"
CANDIDATES_PATH = "supply_assessment.candidates_shown"
PRECISION_PATH = "presentation.precision"

KIND_PRODUCT = "data_product"
KIND_AGENT = "agent"
KINDS = (KIND_PRODUCT, KIND_AGENT)

RECOMMEND_SERVED = "already_served"
RECOMMEND_ENHANCE_AGENT = "enhance_agent"
RECOMMEND_ENHANCE_PRODUCT = "enhance_product"
RECOMMEND_BUILD = "build_new"
RECOMMEND_INSUFFICIENT = "insufficient_evidence"

ZERO = 0.0
ONE = 1.0


@dataclass(frozen=True)
class KpiCoverage:
    """What the estate holds for one KPI the requester named."""

    kpi_id: str
    kpi_name: str | None
    known: bool
    source_product_id: str | None
    answered_by: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "kpi_id": self.kpi_id,
            "kpi_name": self.kpi_name,
            "known": self.known,
            "source_product_id": self.source_product_id,
            "answered_by": list(self.answered_by),
            "answered": bool(self.answered_by),
        }


@dataclass(frozen=True)
class Candidate:
    """An existing asset that could take the demand on, and how much of it."""

    asset_type: str
    asset_id: str
    name: str
    covered_kpis: tuple[str, ...]
    missing_kpis: tuple[str, ...]
    share: float
    precision: int

    def document(self) -> dict[str, Any]:
        return {
            "asset_type": self.asset_type,
            "asset_id": self.asset_id,
            "name": self.name,
            "covered_kpis": list(self.covered_kpis),
            "missing_kpis": list(self.missing_kpis),
            "share": round(self.share, self.precision),
        }


@dataclass(frozen=True)
class Assessment:
    kind: str
    recommendation: str
    headline: str
    rationale: str
    coverage: tuple[KpiCoverage, ...]
    candidates: tuple[Candidate, ...]
    unplaced_questions: tuple[str, ...]
    answered_share: float
    precision: int
    rubric_version_id: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def document(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "recommendation": self.recommendation,
            "headline": self.headline,
            "rationale": self.rationale,
            "answered_share": round(self.answered_share, self.precision),
            "coverage": [row.document() for row in self.coverage],
            "candidates": [row.document() for row in self.candidates],
            "unplaced_questions": list(self.unplaced_questions),
            "notes": list(self.notes),
            "rubric_version_id": self.rubric_version_id,
        }


def _kpi_rows(
    connection: psycopg.Connection[Any], kpi_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Each named KPI, its source of record, and every agent that answers it."""
    if not kpi_ids:
        return {}
    rows = fetch_all(
        connection,
        "SELECT k.kpi_id, k.kpi_name, k.source_of_record, "
        "       coalesce(array_agg(DISTINCT v.agent_id) "
        "                FILTER (WHERE v.agent_id IS NOT NULL), '{}') AS answered_by "
        "FROM kpi_definition k "
        "LEFT JOIN agent_kpi_coverage c ON c.kpi_id = k.kpi_id "
        "LEFT JOIN agent_version v ON v.agent_version_id = c.agent_version_id "
        "LEFT JOIN agent a ON a.current_version_id = v.agent_version_id "
        "WHERE k.kpi_id = ANY(%s) "
        "GROUP BY k.kpi_id, k.kpi_name, k.source_of_record",
        (kpi_ids,),
    )
    return {row["kpi_id"]: row for row in rows}


def _agent_candidates(
    connection: psycopg.Connection[Any], kpi_ids: list[str]
) -> list[dict[str, Any]]:
    """Published agents, with the asked KPIs each already answers."""
    if not kpi_ids:
        return []
    return fetch_all(
        connection,
        "SELECT a.agent_id AS asset_id, a.name, "
        "       coalesce(array_agg(DISTINCT c.kpi_id) "
        "                FILTER (WHERE c.kpi_id = ANY(%(kpis)s)), '{}') AS covered "
        "FROM agent a "
        "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "LEFT JOIN agent_kpi_coverage c ON c.agent_version_id = v.agent_version_id "
        "GROUP BY a.agent_id, a.name "
        "ORDER BY a.agent_id",
        {"kpis": kpi_ids},
    )


def _product_candidates(
    connection: psycopg.Connection[Any], kpi_ids: list[str]
) -> list[dict[str, Any]]:
    """Products, with the asked KPIs each is already the source of record for."""
    if not kpi_ids:
        return []
    return fetch_all(
        connection,
        "SELECT p.product_id AS asset_id, p.name, "
        "       coalesce(array_agg(DISTINCT k.kpi_id) "
        "                FILTER (WHERE k.kpi_id = ANY(%(kpis)s)), '{}') AS covered "
        "FROM data_product p "
        "LEFT JOIN kpi_definition k ON k.source_of_record = p.product_id "
        "GROUP BY p.product_id, p.name "
        "ORDER BY p.product_id",
        {"kpis": kpi_ids},
    )


def _rank(
    rows: list[dict[str, Any]], asset_type: str, asked: list[str], precision: int
) -> list[Candidate]:
    candidates = []
    for row in rows:
        covered = [kpi for kpi in asked if kpi in set(row["covered"])]
        if not covered:
            continue
        candidates.append(
            Candidate(
                asset_type=asset_type,
                asset_id=row["asset_id"],
                name=row["name"],
                covered_kpis=tuple(covered),
                missing_kpis=tuple(kpi for kpi in asked if kpi not in set(covered)),
                share=len(covered) / len(asked) if asked else ZERO,
                precision=precision,
            )
        )
    candidates.sort(key=lambda item: (-item.share, item.asset_id))
    return candidates


def _place_questions(
    connection: psycopg.Connection[Any], questions: list[str]
) -> list[str]:
    """Questions no published agent looks able to answer.

    Matched the way the analytic runtime matches one — against the KPI names and
    synonyms in an agent's coverage map — so a question this says is unplaceable
    is one the estate would actually refuse.

    Naming an answered KPI elsewhere in the demand does not place a question.
    It is tempting to let it, on the grounds that the question travels with the
    measure it was filed under; but almost every demand names at least one
    answered KPI, so that rule places everything and the signal disappears
    exactly when it is worth having. A question that names no certified measure
    is the evidence that something is genuinely missing, and it is reported as
    evidence rather than as a verdict.
    """
    if not questions:
        return []
    rows = fetch_all(
        connection,
        "SELECT DISTINCT lower(k.kpi_name) AS name, "
        "       coalesce(lower(s.term), '') AS synonym "
        "FROM agent_kpi_coverage c "
        "JOIN agent_version v ON v.agent_version_id = c.agent_version_id "
        "JOIN agent a ON a.current_version_id = v.agent_version_id "
        "JOIN kpi_definition k ON k.kpi_id = c.kpi_id "
        "LEFT JOIN kpi_synonym s ON s.kpi_id = k.kpi_id",
    )
    vocabulary = {row["name"] for row in rows} | {
        row["synonym"] for row in rows if row["synonym"]
    }

    unplaced = []
    for question in questions:
        lowered = question.lower()
        # A question naming a measure an agent already answers is placeable.
        if any(term and term in lowered for term in vocabulary):
            continue
        unplaced.append(question)
    return unplaced


def assess(
    connection: psycopg.Connection[Any],
    rubric: Rubric,
    *,
    kind: str,
    kpis: list[str] | None = None,
    questions: list[str] | None = None,
) -> Assessment:
    """Whether the estate already answers this, and what to do about it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")

    asked = [value.strip().upper() for value in (kpis or []) if value.strip()]
    asked = list(dict.fromkeys(asked))
    asked_questions = [value.strip() for value in (questions or []) if value.strip()]
    precision = int(rubric.number(PRECISION_PATH))
    served_min = float(rubric.number(ALREADY_SERVED_PATH))
    enhance_min = float(rubric.number(ENHANCE_PATH))
    shown = int(rubric.number(CANDIDATES_PATH))
    minimum_kpis = int(rubric.number(MIN_KPIS_PATH))

    known = _kpi_rows(connection, asked)
    coverage = tuple(
        KpiCoverage(
            kpi_id=kpi,
            kpi_name=known.get(kpi, {}).get("kpi_name"),
            known=kpi in known,
            source_product_id=known.get(kpi, {}).get("source_of_record"),
            answered_by=tuple(known.get(kpi, {}).get("answered_by") or ()),
        )
        for kpi in asked
    )
    unplaced = tuple(_place_questions(connection, asked_questions))

    if len(asked) < minimum_kpis:
        return Assessment(
            kind=kind,
            recommendation=RECOMMEND_INSUFFICIENT,
            headline="Not enough to assess this against the estate.",
            rationale=(
                "No certified KPI was named, so there is nothing to compare against "
                "coverage. Name the measures the answer would have to carry and this "
                "check can tell you whether anything already answers them."
            ),
            coverage=coverage,
            candidates=(),
            unplaced_questions=unplaced,
            answered_share=ZERO,
            precision=precision,
            rubric_version_id=rubric.rubric_version_id,
        )

    # Ranked, then cut to what the rubric says is worth reading. The cut lives
    # here rather than in the panel so the answer the API gives and the answer
    # the page shows are the same answer.
    agents = _rank(
        _agent_candidates(connection, asked), KIND_AGENT, asked, precision
    )[:shown]
    products = _rank(
        _product_candidates(connection, asked), KIND_PRODUCT, asked, precision
    )[:shown]
    answered = [row for row in coverage if row.answered_by]
    answered_share = len(answered) / len(asked)

    notes: list[str] = []
    unknown = [row.kpi_id for row in coverage if not row.known]
    if unknown:
        notes.append(
            "Not in the KPI register, so no product or agent can be measured against "
            "them: " + ", ".join(unknown)
        )

    best_agent = agents[0] if agents else None
    best_product = products[0] if products else None
    candidates = (*agents, *products)
    # The KPIs nothing answers today. This, not the gap in any one agent's
    # coverage map, is what new or extended supply would have to close: telling
    # somebody to add a measure another agent already answers is asking for the
    # divergence this whole assessment exists to prevent.
    #
    # The two kinds of gap take different work, so they are counted apart. A
    # certified measure nobody answers is a coverage gap, and an agent can close
    # it today. A measure that is not in the register is not a coverage gap at
    # all — there is no definition to answer against yet, and asking an agent to
    # answer it is asking it to invent one.
    unanswered = tuple(
        row.kpi_id for row in coverage if row.known and not row.answered_by
    )
    unregistered = tuple(row.kpi_id for row in coverage if not row.known)
    open_kpis = unanswered + unregistered

    if best_agent is not None and best_agent.share >= served_min:
        return Assessment(
            kind=kind,
            recommendation=RECOMMEND_SERVED,
            headline=f"{best_agent.name} already answers all of this.",
            rationale=(
                f"{best_agent.asset_id} covers every KPI named "
                f"({', '.join(best_agent.covered_kpis)}). A second asset answering the "
                "same certified measures is the divergence the agent mesh exists to "
                "flag, so this needs an entitlement rather than new supply."
            ),
            coverage=coverage, candidates=candidates, unplaced_questions=unplaced,
            answered_share=answered_share, precision=precision,
            rubric_version_id=rubric.rubric_version_id, notes=tuple(notes),
        )

    if not open_kpis and answered:
        answering = sorted({
            agent for row in coverage for agent in row.answered_by
        })
        return Assessment(
            kind=kind,
            recommendation=RECOMMEND_SERVED,
            headline=f"All of this is already answered, across {len(answering)} agents.",
            rationale=(
                "Every KPI named is answered today by "
                + ", ".join(answering)
                + ". No single agent covers the whole set, so asking one question "
                "across all of them means asking each in turn — but that is an "
                "entitlement and a composition problem, not missing supply. Building "
                "a new asset here would answer measures that already have an answer."
            ),
            coverage=coverage, candidates=candidates, unplaced_questions=unplaced,
            answered_share=answered_share, precision=precision,
            rubric_version_id=rubric.rubric_version_id, notes=tuple(notes),
        )

    if best_agent is not None and best_agent.share >= enhance_min:
        gap = [
            f"{best_agent.asset_id} already answers "
            f"{len(best_agent.covered_kpis)} of {len(asked)} KPIs named"
        ]
        if unanswered:
            one = len(unanswered) == 1
            gap.append(
                f", and {', '.join(unanswered)} {'is' if one else 'are'} answered by "
                f"nothing. Adding {'it' if one else 'them'} to that agent's coverage "
                "map keeps one agent answering the whole question, where a new one "
                "would answer part of it differently"
            )
        if unregistered:
            one = len(unregistered) == 1
            gap.append(
                f". {', '.join(unregistered)} "
                + ("is not a certified measure" if one else "are not certified measures")
                + f" yet, so {'it needs' if one else 'they need'} a definition and "
                "a source of record before that agent — or any other — can answer "
                f"{'it' if one else 'them'}"
            )
        return Assessment(
            kind=kind,
            recommendation=RECOMMEND_ENHANCE_AGENT,
            headline=f"Extend {best_agent.name} rather than build beside it.",
            rationale="".join(gap) + ".",
            coverage=coverage, candidates=candidates, unplaced_questions=unplaced,
            answered_share=answered_share, precision=precision,
            rubric_version_id=rubric.rubric_version_id, notes=tuple(notes),
        )

    if best_product is not None and best_product.share >= enhance_min:
        return Assessment(
            kind=kind,
            recommendation=RECOMMEND_ENHANCE_PRODUCT,
            headline=f"The data is already in {best_product.name}.",
            rationale=(
                f"{best_product.asset_id} is the source of record for "
                f"{len(best_product.covered_kpis)} of {len(asked)} KPIs named, and no "
                "agent answers them all. An agent over the product that already "
                "publishes them costs less than a new product, and keeps the measure "
                "defined once."
            ),
            coverage=coverage, candidates=candidates, unplaced_questions=unplaced,
            answered_share=answered_share, precision=precision,
            rubric_version_id=rubric.rubric_version_id, notes=tuple(notes),
        )

    return Assessment(
        kind=kind,
        recommendation=RECOMMEND_BUILD,
        headline="Nothing in the estate answers this.",
        rationale=(
            "No published agent answers a meaningful share of the KPIs named, and no "
            "product is their source of record. This is new supply, and the demand "
            "board is where it belongs."
        ),
        coverage=coverage, candidates=candidates, unplaced_questions=unplaced,
        answered_share=answered_share, precision=precision,
        rubric_version_id=rubric.rubric_version_id, notes=tuple(notes),
    )
