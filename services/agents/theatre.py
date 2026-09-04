"""What the front page is allowed to show.

The demo theatre plays curated exchanges. An exchange qualifies only while it is
passing against its golden answer *and* has been re-validated recently: a
recorded pass from three weeks ago says the answer was right three weeks ago,
and silence since is not evidence. Both conditions come from the governance
rubric, and the query is here rather than in the page so that every surface
showing a curated answer applies the same test.

M6.5 marks a drifted exchange stale; this is what "removes it from the
front-page theatre" means in practice.
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.common.db import fetch_all
from services.common.rubrics import Rubric

MAX_AGE_PATH = "demo_theatre.max_validation_age_days"
STATE_PASSING = "passing"

_ELIGIBLE = """
SELECT e.exchange_id, e.agent_version_id, v.agent_id, a.name AS agent_name,
       e.ordinal, e.question, e.kpi_class, e.analysis_type, e.expected_shape,
       e.last_validated
FROM demo_exchange e
JOIN agent_version v ON v.agent_version_id = e.agent_version_id
JOIN agent a ON a.agent_id = v.agent_id
WHERE e.validation_state = %s
  AND e.last_validated IS NOT NULL
  AND e.last_validated > now() - %s::interval
ORDER BY a.agent_id, e.ordinal
"""


def eligible(
    connection: psycopg.Connection[Any], rubric: Rubric, *, agent_id: str | None = None
) -> list[dict[str, Any]]:
    days = int(rubric.number(MAX_AGE_PATH))
    rows = fetch_all(connection, _ELIGIBLE, (STATE_PASSING, f"{days} days"))
    if agent_id is None:
        return rows
    return [row for row in rows if row["agent_id"] == agent_id]
