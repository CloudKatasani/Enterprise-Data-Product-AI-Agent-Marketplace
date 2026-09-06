"""Demand intake, duplicate-supply detection and scoring (section 14.3).

The duplicate check is the interesting part and the reason this is not just a
form. Somebody about to ask the estate to build a new data product is, more
often than not, asking for something that already exists under a name they did
not search for. Catching that at submission is worth more than any amount of
catalogue browsing, because it happens at the moment they are motivated.

Four signals, weighted from `demand.yaml`:

    0.40 embedding match against the product's purpose and its certified KPIs
    0.25 entity overlap
    0.20 source-system overlap
    0.15 KPI overlap

At or above the blocking threshold the request stops for owner review with the
candidate shown side by side. Between advisory and blocking the requester is
shown the candidate and may proceed. Below, it goes to scoring.

Every match stores its contributing factors, its confidence and a rationale,
because a duplicate call that cannot explain itself gets overridden on the first
disagreement and then ignored on every one after.

Confidence is not the similarity. Similarity says how alike two things look;
confidence says how much evidence the comparison had. A 0.90 similarity computed
from a one-line request against a product with no KPIs is a coincidence, and the
rubric sends matches below its confidence floor to architect review rather than
showing them to the requester as blocking.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric
from services.search import embedding
from services.workflow import engine

WEIGHT_EMBEDDING = "duplicate_detection.weights.embedding_match"
WEIGHT_ENTITY = "duplicate_detection.weights.entity_overlap"
WEIGHT_SOURCE = "duplicate_detection.weights.source_overlap"
WEIGHT_KPI = "duplicate_detection.weights.kpi_overlap"
BLOCKING_PATH = "duplicate_detection.blocking_threshold"
ADVISORY_PATH = "duplicate_detection.advisory_threshold"
CONFIDENCE_FLOOR_PATH = "duplicate_detection.architect_review_below_confidence"
THEME_TEAMS_PATH = "theme_escalation.distinct_teams_min"
LABEL_WORDS_PATH = "clustering.label_words"
PRECISION_PATH = "presentation.precision"

# What a demand is asking for, and so what it is compared against.
KIND_PRODUCT = "data_product"
KIND_AGENT = "agent"
KINDS = (KIND_PRODUCT, KIND_AGENT)

VERDICT_BLOCKING = "blocking"
VERDICT_ADVISORY = "advisory"
VERDICT_CLEAR = "clear"
VERDICT_ARCHITECT_REVIEW = "architect_review"

CRITERIA = (
    "business_value",
    "consumer_breadth",
    "strategic_alignment",
    "feasibility",
    "reuse_leverage",
    "risk_urgency",
)

DECLINE_REASONS = frozenset(
    {"out_of_scope", "source_unavailable", "cost_prohibitive", "duplicate",
     "superseded", "security_constraint"}
)

WORD = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is",
    "it", "of", "on", "or", "our", "that", "the", "their", "this", "to", "we", "what",
    "which", "with", "want", "need", "would", "like", "data", "report", "dashboard",
})

ZERO = 0.0
ONE = 1.0


class DemandRefusedError(RuntimeError):
    """The demand item cannot proceed as submitted."""


@dataclass(frozen=True)
class Match:
    """One duplicate candidate, with everything needed to argue about it."""

    candidate_id: str
    candidate_name: str
    similarity: float
    contributing_factors: dict[str, float]
    confidence: float
    rationale: str
    # Carried on the match rather than chosen when rendering, so the number a
    # reviewer argues about is the number that was recorded.
    precision: int

    def document(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "similarity": round(self.similarity, self.precision),
            "contributing_factors": {
                key: round(value, self.precision)
                for key, value in self.contributing_factors.items()
            },
            "confidence": round(self.confidence, self.precision),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class DuplicateCheck:
    verdict: str
    matches: tuple[Match, ...]
    rubric_version_id: str

    @property
    def blocking(self) -> bool:
        return self.verdict == VERDICT_BLOCKING

    def document(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "blocking": self.blocking,
            "matches": [match.document() for match in self.matches],
            "rubric_version_id": self.rubric_version_id,
        }


def _words(text: str) -> set[str]:
    return {word for word in WORD.findall(text.lower()) if word not in STOPWORDS}


def _covered(asked: set[str], published: set[str]) -> float:
    """How much of what was asked for the candidate already publishes.

    Containment, not Jaccard, and the difference decides whether this check
    works at all. The question a duplicate call answers is "does something in
    the estate already cover what you are asking for?" — so a request naming
    four columns against a product publishing those four among twenty is a
    complete match. Jaccard scores that 0.2 and lets an exact restatement of an
    existing product through as novel demand, because it penalises the
    candidate for being richer than the request.

    An empty ask scores zero rather than one: no evidence is not agreement.
    """
    if not asked or not published:
        return ZERO
    return len(asked & published) / len(asked)


def _candidates(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return fetch_all(
        connection,
        # The KPIs a product serves are the ones that name it as their source of
        # record, and its sources are the upstream lineage edges the harvest
        # found. Both are read from the register rather than from a join table
        # kept in step by hand.
        "SELECT p.product_id AS candidate_id, p.name, p.purpose, "
        "       coalesce(array_agg(DISTINCT k.kpi_id) FILTER (WHERE k.kpi_id IS NOT NULL), "
        "                '{}') AS kpis, "
        "       coalesce(array_agg(DISTINCT k.kpi_name) FILTER (WHERE k.kpi_name IS NOT NULL),"
        "                '{}') AS kpi_names, "
        "       coalesce(array_agg(DISTINCT e.upstream_id) "
        "                FILTER (WHERE e.upstream_id IS NOT NULL), '{}') AS sources, "
        "       coalesce(array_agg(DISTINCT col.name) FILTER (WHERE col.name IS NOT NULL), "
        "                '{}') AS columns "
        "FROM data_product p "
        "LEFT JOIN kpi_definition k ON k.source_of_record = p.product_id "
        "LEFT JOIN lineage_edge e ON e.downstream_id = p.product_id "
        "  AND e.downstream_type = 'data_product' AND e.upstream_type = 'source_system' "
        "LEFT JOIN data_product_column col ON col.product_id = p.product_id "
        "GROUP BY p.product_id, p.name, p.purpose "
        "ORDER BY p.product_id",
    )


def _agent_candidates(connection: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """The same comparison surface as a product, read off an agent.

    An agent's capability statement is its purpose, the KPIs in its coverage map
    are the measures it serves, the products it binds are what it reads, and the
    columns those bindings allow are the entities it can speak about. Shaping it
    identically to a product is what lets one similarity calculation answer for
    both — a demand for an agent is compared against agents, and the weights,
    thresholds and rationale stay the ones the rubric published.
    """
    return fetch_all(
        connection,
        "SELECT a.agent_id AS candidate_id, a.name, "
        "       v.capability_statement AS purpose, "
        "       coalesce(array_agg(DISTINCT c.kpi_id) "
        "                FILTER (WHERE c.kpi_id IS NOT NULL), '{}') AS kpis, "
        "       coalesce(array_agg(DISTINCT k.kpi_name) "
        "                FILTER (WHERE k.kpi_name IS NOT NULL), '{}') AS kpi_names, "
        "       coalesce(array_agg(DISTINCT b.product_id) "
        "                FILTER (WHERE b.product_id IS NOT NULL), '{}') AS sources, "
        "       coalesce(array_agg(DISTINCT col.value) "
        "                FILTER (WHERE col.value IS NOT NULL), '{}') AS columns "
        "FROM agent a "
        "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "LEFT JOIN agent_kpi_coverage c ON c.agent_version_id = v.agent_version_id "
        "LEFT JOIN kpi_definition k ON k.kpi_id = c.kpi_id "
        "LEFT JOIN agent_product_binding b ON b.agent_version_id = v.agent_version_id "
        "LEFT JOIN LATERAL unnest(b.columns_allowed) AS col(value) ON true "
        "GROUP BY a.agent_id, a.name, v.capability_statement "
        "ORDER BY a.agent_id",
    )


def check_duplicates(
    connection: psycopg.Connection[Any],
    rubric: Rubric,
    *,
    request_text: str,
    entities: list[str] | None = None,
    sources: list[str] | None = None,
    kpis: list[str] | None = None,
    kind: str = KIND_PRODUCT,
) -> DuplicateCheck:
    """Whether this demand reads like something the estate already publishes.

    ``kind`` chooses what it is compared against: a demand for an agent is
    compared against agents, not products, because "we already have one of
    these" is a claim about the same sort of asset. It defaults to products so
    the submission path, which has always meant products, is unchanged.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    weights = {
        "embedding_match": float(rubric.number(WEIGHT_EMBEDDING)),
        "entity_overlap": float(rubric.number(WEIGHT_ENTITY)),
        "source_overlap": float(rubric.number(WEIGHT_SOURCE)),
        "kpi_overlap": float(rubric.number(WEIGHT_KPI)),
    }
    blocking = float(rubric.number(BLOCKING_PATH))
    advisory = float(rubric.number(ADVISORY_PATH))
    confidence_floor = float(rubric.number(CONFIDENCE_FLOOR_PATH))
    precision = int(rubric.number(PRECISION_PATH))

    asked_entities = {value.lower() for value in (entities or [])} or _words(request_text)
    asked_sources = {value.upper() for value in (sources or [])}
    asked_kpis = {value.upper() for value in (kpis or [])}
    embedder = embedding.active_embedder()
    request_vector = embedder.embed(request_text)

    matches: list[Match] = []
    pool = _agent_candidates(connection) if kind == KIND_AGENT else _candidates(
        connection
    )
    for candidate in pool:
        subject = " ".join(
            [candidate["purpose"], candidate["name"], *candidate["kpi_names"]]
        )
        factors = {
            # The same similarity the catalog's semantic search uses, so a
            # duplicate call and a search result agree about what "alike" means.
            "embedding_match": max(
                ZERO, min(ONE, embedding.cosine(request_vector, embedder.embed(subject)))
            ),
            "entity_overlap": _covered(
                asked_entities, {name.lower() for name in candidate["columns"]}
            ),
            "source_overlap": _covered(asked_sources, set(candidate["sources"])),
            "kpi_overlap": _covered(asked_kpis, set(candidate["kpis"])),
        }
        similarity = sum(weights[key] * value for key, value in factors.items())

        # Confidence is how much evidence the comparison had, not how alike the
        # two texts look. A signal the requester supplied nothing for cannot
        # support a verdict.
        supplied = [
            bool(request_text.strip()),
            bool(entities),
            bool(sources),
            bool(kpis),
        ]
        confidence = sum(ONE for value in supplied if value) / len(supplied)

        if similarity < advisory:
            continue
        matches.append(
            Match(
                candidate_id=candidate["candidate_id"],
                candidate_name=candidate["name"],
                similarity=similarity,
                contributing_factors=factors,
                confidence=confidence,
                rationale=_rationale(factors, weights, candidate),
                precision=precision,
            )
        )

    matches.sort(key=lambda match: match.similarity, reverse=True)
    verdict = VERDICT_CLEAR
    if matches:
        best = matches[0]
        if best.similarity >= blocking:
            verdict = (
                VERDICT_BLOCKING
                if best.confidence >= confidence_floor
                else VERDICT_ARCHITECT_REVIEW
            )
        elif best.similarity >= advisory:
            verdict = VERDICT_ADVISORY

    return DuplicateCheck(
        verdict=verdict, matches=tuple(matches), rubric_version_id=rubric.rubric_version_id
    )


def _rationale(
    factors: dict[str, float], weights: dict[str, float], candidate: dict[str, Any]
) -> str:
    """Which signal drove the match, named so a reviewer can disagree with it."""
    contributions = {key: weights[key] * value for key, value in factors.items()}
    leading = max(contributions, key=lambda key: contributions[key])
    asset = candidate["candidate_id"]
    readable = {
        "embedding_match": f"its stated purpose reads like {candidate['name']}",
        "entity_overlap": f"it asks for entities {asset} already covers",
        "source_overlap": f"it names sources {asset} already reads",
        "kpi_overlap": f"it names KPIs {asset} already serves",
    }
    return readable[leading]


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def submit(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    demand_id: str,
    request_id: str,
    requester_party_id: str,
    title: str,
    body: str,
    entities: list[str] | None = None,
    sources: list[str] | None = None,
    kpis: list[str] | None = None,
) -> dict[str, Any]:
    check = check_duplicates(
        connection, rubric, request_text=f"{title}. {body}",
        entities=entities, sources=sources, kpis=kpis,
    )

    connection.execute(
        "INSERT INTO request (request_id, tenant_id, request_type, state, requester_party_id, "
        "  title, body, submitted_at) VALUES (%s, %s, 'supply', %s, %s, %s, %s, now()) "
        "ON CONFLICT (request_id) DO NOTHING",
        (request_id, tenant, engine.DEM_SUBMITTED, requester_party_id, title, body),
    )
    connection.execute(
        "INSERT INTO demand_item (demand_id, tenant_id, request_id, state, rubric_version_id) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (demand_id) DO NOTHING",
        (demand_id, tenant, request_id, engine.DEM_SUBMITTED, rubric.rubric_version_id),
    )
    engine.start(
        connection, tenant, workflow_type=engine.TYPE_DEMAND, subject_id=demand_id,
        actor=requester_party_id, payload={"duplicate_check": check.document()},
    )

    if check.verdict in {VERDICT_BLOCKING, VERDICT_ARCHITECT_REVIEW}:
        engine.transition(
            connection, tenant, workflow_type=engine.TYPE_DEMAND, subject_id=demand_id,
            to_state=engine.DEM_DUPLICATE_REVIEW, actor=requester_party_id,
            detail=check.document(),
        )
        connection.execute(
            "UPDATE demand_item SET state = %s WHERE demand_id = %s",
            (engine.DEM_DUPLICATE_REVIEW, demand_id),
        )
    else:
        engine.transition(
            connection, tenant, workflow_type=engine.TYPE_DEMAND, subject_id=demand_id,
            to_state=engine.DEM_TRIAGED, actor=requester_party_id,
            detail=check.document(),
        )
        connection.execute(
            "UPDATE demand_item SET state = %s WHERE demand_id = %s",
            (engine.DEM_TRIAGED, demand_id),
        )

    return {"demand_id": demand_id, "duplicate_check": check.document()}


def vote(
    connection: psycopg.Connection[Any],
    tenant: str,
    *,
    demand_id: str,
    voter_party_id: str,
    use_case: str,
) -> dict[str, Any]:
    """A vote, with the use case that makes it countable.

    Section 14.3: a vote without context is not counted. The use case is what
    lets votes cluster into a theme, and a theme is what turns fifty individual
    asks into one thing worth building.
    """
    if not use_case.strip():
        raise DemandRefusedError(
            "a vote needs a one-line use case; without it the vote cannot be clustered "
            "and is not counted"
        )
    org = fetch_one(
        connection, "SELECT org_unit_id FROM party WHERE party_id = %s", (voter_party_id,)
    )
    connection.execute(
        "INSERT INTO demand_vote (vote_id, tenant_id, demand_id, voter_party_id, use_case, "
        "  org_unit_id) VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (demand_id, voter_party_id) DO UPDATE SET use_case = EXCLUDED.use_case",
        (f"DVT-{demand_id}-{voter_party_id}", tenant, demand_id, voter_party_id, use_case,
         org["org_unit_id"] if org else None),
    )
    counts = fetch_one(
        connection,
        "SELECT count(*) AS votes, count(DISTINCT org_unit_id) AS teams "
        "FROM demand_vote WHERE demand_id = %s",
        (demand_id,),
    )
    # count(*) always returns a row, so None here means the query did not run;
    # reporting zero votes would be a quieter kind of wrong than saying so.
    if counts is None:
        raise DemandRefusedError(f"could not count votes on {demand_id}")
    return {"votes": int(counts["votes"]), "distinct_teams": int(counts["teams"])}


def score(
    connection: psycopg.Connection[Any],
    tenant: str,
    rubric: Rubric,
    *,
    demand_id: str,
    actor: str,
    assessments: dict[str, float],
) -> dict[str, Any]:
    """Score against the rubric's criteria and record the breakdown.

    The breakdown travels with the score. A demand board that shows a number
    without saying which criterion produced it invites everyone to assume the
    number means whatever suits them.
    """
    missing = set(CRITERIA) - set(assessments)
    if missing:
        raise DemandRefusedError(
            "every criterion must be assessed; missing " + ", ".join(sorted(missing))
        )

    precision = int(rubric.number(PRECISION_PATH))
    breakdown = {}
    total = ZERO
    for code in CRITERIA:
        weight = float(rubric.number(f"criteria.{code}"))
        value = float(assessments[code])
        contribution = weight * value
        breakdown[code] = {"weight": weight, "assessment": value,
                           "contribution": round(contribution, precision)}
        total += contribution

    connection.execute(
        "UPDATE demand_item SET state = %s, score = %s, score_breakdown = %s, "
        "  rubric_version_id = %s WHERE demand_id = %s",
        (engine.DEM_SCORED, round(total, precision), json.dumps(breakdown),
         rubric.rubric_version_id, demand_id),
    )
    engine.transition(
        connection, tenant, workflow_type=engine.TYPE_DEMAND, subject_id=demand_id,
        to_state=engine.DEM_SCORED, actor=actor,
        detail={"score": round(total, precision),
                "rubric_version_id": rubric.rubric_version_id},
    )
    return {"score": round(total, precision), "breakdown": breakdown}


def cluster(
    connection: psycopg.Connection[Any], tenant: str, rubric: Rubric
) -> list[dict[str, Any]]:
    """Group open demand into themes, and escalate the ones with real breadth.

    Themes are formed from the words the requesters used, not from a taxonomy
    somebody maintains: the point is to surface what people are asking for in
    their own terms, including the asks that do not fit the taxonomy.
    """
    minimum_teams = int(rubric.number(THEME_TEAMS_PATH))
    label_words = int(rubric.number(LABEL_WORDS_PATH))
    precision = int(rubric.number(PRECISION_PATH))
    items = fetch_all(
        connection,
        "SELECT d.demand_id, r.title, r.body, "
        "       count(v.vote_id) AS votes, "
        "       count(DISTINCT v.org_unit_id) AS teams "
        "FROM demand_item d JOIN request r ON r.request_id = d.request_id "
        "LEFT JOIN demand_vote v ON v.demand_id = d.demand_id "
        "WHERE d.state NOT IN (%s, %s) "
        "GROUP BY d.demand_id, r.title, r.body ORDER BY d.demand_id",
        (engine.DEM_DELIVERED, engine.DEM_DECLINED),
    )

    themes: dict[str, dict[str, Any]] = {}
    for item in items:
        words = _words(f"{item['title']} {item['body']}")
        if not words:
            continue
        label = " ".join(sorted(words)[:label_words])
        theme = themes.setdefault(
            label, {"label": label, "demand_ids": [], "votes": 0, "teams": set()}
        )
        theme["demand_ids"].append(item["demand_id"])
        theme["votes"] += int(item["votes"])
        theme["teams"].add(item["demand_id"] if item["teams"] else None)

    written = []
    for label, theme in themes.items():
        teams = fetch_one(
            connection,
            "SELECT count(DISTINCT org_unit_id) AS teams FROM demand_vote "
            "WHERE demand_id = ANY(%s)",
            (theme["demand_ids"],),
        )
        distinct_teams = int(teams["teams"]) if teams else 0
        # sha256 of the label, not Python's hash(): hash() is salted per process,
        # so the same theme would get a different id on every run and the board
        # would lose its history at each restart.
        theme_id = "DTH-" + hashlib.sha256(label.encode("utf-8")).hexdigest()
        escalated = distinct_teams >= minimum_teams
        connection.execute(
            "INSERT INTO demand_theme (theme_id, tenant_id, label, summary, "
            "  distinct_team_count, escalated_at, confidence, rationale) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (theme_id) DO UPDATE SET distinct_team_count = EXCLUDED."
            "  distinct_team_count, escalated_at = EXCLUDED.escalated_at",
            (
                theme_id, tenant, label,
                f"{len(theme['demand_ids'])} request(s), {theme['votes']} vote(s)",
                distinct_teams,
                datetime.now(UTC) if escalated else None,
                _theme_confidence(
                    theme["demand_ids"], distinct_teams, minimum_teams, precision
                ),
                f"grouped on shared terms: {label}",
            ),
        )
        connection.execute(
            "UPDATE demand_item SET theme_id = %s WHERE demand_id = ANY(%s)",
            (theme_id, theme["demand_ids"]),
        )
        written.append(
            {
                "theme_id": theme_id,
                "label": label,
                "demand_ids": theme["demand_ids"],
                "distinct_teams": distinct_teams,
                "escalated": escalated,
            }
        )
    return written


def _theme_confidence(
    demand_ids: list[str], teams: int, minimum: int, precision: int
) -> float:
    """How much a theme is worth trusting: more requests and more teams, more trust."""
    breadth = min(ONE, teams / minimum) if minimum else ZERO
    depth = min(ONE, len(demand_ids) / minimum) if minimum else ZERO
    return round(fmean([breadth, depth]), precision)
