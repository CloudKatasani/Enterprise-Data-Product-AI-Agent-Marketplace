"""Live counters and the activity ticker (M11.5, section 13.5).

Both read the platform. A counter that is hardcoded is a claim the product
cannot support, and a marketing surface making one is the fastest way to lose
the argument the rest of the system spends its time winning.

The ticker is where a marketing surface most easily becomes a leak. Three rules
hold it closed, and all three are enforced here rather than by whoever writes
the copy:

* **Never a person.** No actor, no requester, no owner. Events are stated as
  what happened to an asset class, never who did it.
* **Never above the sensitivity ceiling.** A confidential asset does not appear
  on an unauthenticated page even by name.
* **Never fewer than the rubric's occurrence floor.** An event derived from one
  underlying occurrence is a side channel onto one team's activity: a visitor
  watching the ticker would learn that a specific thing happened to a specific
  team today. Aggregation below the floor is suppressed entirely rather than
  rounded, because a rounded count of one is still a count of one.

If the channel is unavailable the ticker hides. A frozen stale ticker is worse
than none: it claims liveness it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric

SYSTEM_SESSION_PREFIX = "SES-SYS-"


@dataclass(frozen=True)
class Counter:
    """One number on the trust strip, and where clicking it goes."""

    code: str
    label: str
    value: int
    href: str

    def document(self) -> dict[str, Any]:
        return {"code": self.code, "label": self.label, "value": self.value, "href": self.href}


@dataclass(frozen=True)
class TickerEvent:
    """One anonymised statement about the estate.

    ``occurrences`` is carried so the suppression rule is visible in the
    payload: a reader of the API can check that nothing below the floor was
    served, rather than trusting that it was not.
    """

    code: str
    text: str
    occurrences: int

    def document(self) -> dict[str, Any]:
        return {"code": self.code, "text": self.text, "occurrences": self.occurrences}


COUNTERS = (
    (
        "products",
        "Data products published",
        "/data-products",
        "SELECT count(*) AS value FROM data_product WHERE certification <> 'deprecated'",
    ),
    (
        "agents",
        "AI agents live",
        "/agents",
        "SELECT count(*) AS value FROM agent a "
        "JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "WHERE v.status = 'published'",
    ),
    (
        "kpis",
        "Certified KPIs",
        "/discover?kind=kpi",
        "SELECT count(*) AS value FROM kpi_definition WHERE status = 'certified'",
    ),
    (
        "answers",
        "Questions answered this month",
        "/agents",
        "SELECT count(*) AS value FROM agent_interaction "
        "WHERE occurred_at > now() - %(window)s::int * interval '1 day' "
        "  AND session_id NOT LIKE %(system)s",
    ),
)


def counters(connection: psycopg.Connection[Any], rubric: Rubric) -> list[Counter]:
    window = int(rubric.number("counters.answers_window_days"))
    params = {"window": window, "system": f"{SYSTEM_SESSION_PREFIX}%"}
    result: list[Counter] = []
    for code, label, href, sql in COUNTERS:
        row = fetch_one(connection, sql, params if "%(" in sql else None)
        result.append(Counter(code, label, int(row["value"]) if row else 0, href))
    return result


# Each entry is one class of event, phrased without an actor. The count is what
# the suppression rule is applied to; the phrasing takes the count so a ticker
# never says "a" when it means "eleven".
TICKER_SOURCES = (
    # Estate-wide, deliberately. Splitting these by industry would put a count
    # of two beside a named vertical, which is the side channel the occurrence
    # floor exists to close — and suppressing it afterwards would leave the
    # strip empty rather than honest.
    (
        "certified",
        "SELECT 'products' AS subject, count(*) AS occurrences "
        "FROM data_product WHERE certification = 'certified'",
        "{count} data products are certified against a published contract",
    ),
    # The one statement that describes assets rather than counting the estate,
    # so the sensitivity ceiling applies to it. Everything above the ceiling is
    # absent from the sentence, not summarised in it.
    (
        "browsable",
        "SELECT 'browsable' AS subject, count(*) AS occurrences "
        "FROM data_product p JOIN sensitivity_tier s ON s.code = p.sensitivity_tier "
        "WHERE p.certification <> 'deprecated' AND s.rank_order <= %(ceiling)s",
        "{count} data products can be browsed in full without filing a request",
    ),
    (
        "provisioned",
        "SELECT 'access' AS subject, count(*) AS occurrences "
        "FROM request WHERE request_type = 'access' AND state = 'approved' "
        "  AND created_at > now() - %(window)s::int * interval '1 day'",
        "{count} access requests were provisioned in the last {window} days",
    ),
    (
        "answered",
        "SELECT question_class AS subject, count(*) AS occurrences "
        "FROM agent_interaction "
        "WHERE outcome = 'answered' AND grounded "
        "  AND occurred_at > now() - %(window)s::int * interval '1 day' "
        "  AND session_id NOT LIKE %(system)s "
        "GROUP BY question_class ORDER BY count(*) DESC",
        "{count} {subject} questions were answered with citations",
    ),
    (
        "published",
        "SELECT 'agents' AS subject, count(*) AS occurrences "
        "FROM agent a JOIN agent_version v ON v.agent_version_id = a.current_version_id "
        "WHERE v.status = 'published'",
        "{count} agents passed their publish gate with every numeric claim cited",
    ),
    (
        "refused",
        "SELECT 'refusals' AS subject, count(*) AS occurrences "
        "FROM agent_interaction "
        "WHERE outcome <> 'answered' "
        "  AND occurred_at > now() - %(window)s::int * interval '1 day' "
        "  AND session_id NOT LIKE %(system)s",
        "{count} questions were refused rather than answered without evidence",
    ),
)


def ticker(connection: psycopg.Connection[Any], rubric: Rubric) -> list[TickerEvent]:
    floor = int(rubric.number("ticker.min_occurrences"))
    ceiling = int(rubric.number("ticker.max_sensitivity_rank"))
    window = int(rubric.number("ticker.window_days"))
    maximum = int(rubric.number("ticker.max_events"))
    params = {
        "ceiling": ceiling, "window": window, "system": f"{SYSTEM_SESSION_PREFIX}%",
    }

    events: list[TickerEvent] = []
    for code, sql, template in TICKER_SOURCES:
        for row in fetch_all(connection, sql, params):
            occurrences = int(row["occurrences"])
            if occurrences < floor:
                continue
            subject = str(row["subject"]).replace("_", " ")
            events.append(
                TickerEvent(
                    code=code,
                    text=template.format(count=occurrences, subject=subject, window=window),
                    occurrences=occurrences,
                )
            )

    return _interleave(events, maximum)


def _interleave(events: list[TickerEvent], maximum: int) -> list[TickerEvent]:
    """Round-robin across event classes, strongest first within each.

    Sorting purely by occurrence count hands the whole crawl to whichever class
    happens to be busiest, and a ticker that says the same kind of thing twelve
    times has told the reader one thing. Taking one from each class in turn
    keeps the strip a summary of the estate rather than a report on its
    loudest corner.
    """
    by_code: dict[str, list[TickerEvent]] = {}
    for event in sorted(events, key=lambda item: (-item.occurrences, item.text)):
        by_code.setdefault(event.code, []).append(event)

    ordered: list[TickerEvent] = []
    while len(ordered) < maximum and any(by_code.values()):
        for code in sorted(by_code):
            queue = by_code[code]
            if queue and len(ordered) < maximum:
                ordered.append(queue.pop(0))
    return ordered
