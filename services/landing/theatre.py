"""Recorded traces for the front-page answer theatre (M11.4, section 13.4).

Provenance is the whole point of this band. An unauthenticated visitor watches
a replay of a real execution — the tokens the runtime produced, the tools it
called, the rows it scanned, what it cost and how long it took — stamped with
the date it ran. An authenticated user gets a live execution against the demo
tier instead. There is no third mode, and in particular there is no mode in
which the page composes an answer: a fabricated answer on a page arguing for
grounded answers would discredit everything else on it.

Two ages guard the replay, and both must pass:

* The exchange must still be validating against its golden answer inside the
  governance rubric's window (:mod:`services.agents.theatre`). A recorded pass
  from three weeks ago says the answer was right three weeks ago.
* The trace file must itself be recent. The nightly job rewrites it on every
  passing run, so a trace that has stopped being rewritten is one whose
  exchange has stopped passing — and it drops out here rather than lingering.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from services.agents import theatre as eligibility
from services.common.config import REPO_ROOT
from services.common.rubrics import Rubric
from services.common.timing import seconds_in

TRACE_DIR = REPO_ROOT / "seed" / "theatre"

MODE_RECORDED = "recorded"
MODE_LIVE = "live"


@dataclass(frozen=True)
class Trace:
    """One replayable exchange, with the stamp that says what it is."""

    exchange_id: str
    agent_id: str
    agent_name: str
    question: str
    analysis_type: str
    recorded_at: datetime
    body: dict[str, Any]

    def document(self) -> dict[str, Any]:
        return {
            **self.body,
            "exchange_id": self.exchange_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "question": self.question,
            "analysis_type": self.analysis_type,
            "mode": MODE_RECORDED,
            # Shown on the panel, not buried in a tooltip. A visitor should
            # never have to ask whether what they are watching happened.
            "recorded_at": self.recorded_at.isoformat(),
        }


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A missing or unreadable trace is one fewer exchange on the loop, not
        # an error page. The band collapses if none survive.
        return None


def traces(
    connection: psycopg.Connection[Any],
    governance: Rubric,
    landing: Rubric,
    *,
    agent_id: str | None = None,
) -> list[Trace]:
    maximum = int(landing.number("theatre.exchanges_offered"))
    oldest = datetime.now(UTC).timestamp() - seconds_in(
        float(landing.number("theatre.max_trace_age_days"))
    )

    found: list[Trace] = []
    for exchange in eligibility.eligible(connection, governance, agent_id=agent_id):
        body = _read(TRACE_DIR / exchange["agent_id"] / f"{exchange['exchange_id']}.json")
        if body is None:
            continue
        stamp = body.get("recorded_at")
        if not stamp:
            continue
        recorded = datetime.fromisoformat(stamp)
        if recorded.timestamp() < oldest:
            continue
        found.append(
            Trace(
                exchange_id=exchange["exchange_id"],
                agent_id=exchange["agent_id"],
                agent_name=exchange["agent_name"],
                question=exchange["question"],
                analysis_type=exchange["analysis_type"],
                recorded_at=recorded,
                body=body,
            )
        )

    # One exchange per agent before a second from any of them: the picker should
    # show the breadth of the estate, not five questions from whichever agent
    # happens to sort first.
    by_agent: dict[str, list[Trace]] = {}
    for trace in found:
        by_agent.setdefault(trace.agent_id, []).append(trace)

    ordered: list[Trace] = []
    while len(ordered) < maximum and any(by_agent.values()):
        for agent in sorted(by_agent):
            queue = by_agent[agent]
            if queue and len(ordered) < maximum:
                ordered.append(queue.pop(0))
    return ordered
