"""Feature flags, read from the database and never cached.

Two rules, both learned the same way.

**Fail closed.** A flag that cannot be read is off, not on. A missing row, an
unreachable database, a typo in the code — every one of those resolves to the
conservative answer, so a flag that gates a permission cannot be turned on by an
outage.

**Never cached.** The same reason effective permissions are never cached: a flag
turned off during an incident has to take effect on the next request, not on the
next deploy or the next cache expiry. These are single-row primary-key lookups
on a table with a handful of rows.
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.common.db import fetch_one

# The academy's access benefit. Off, a certification still means the person
# learned something; it stops meaning a faster path to a grant. A governance
# feature that hands out access needs a switch somebody can reach in a hurry.
ACADEMY_PRE_APPROVED_ACCESS = "academy_pre_approved_access"

# The hero's answer stream. Off, the constellation keeps its settled frame and
# the page loses nothing but the pulses.
LANDING_ANSWER_STREAM = "landing_answer_stream"


def enabled(connection: psycopg.Connection[Any], code: str) -> bool:
    try:
        row = fetch_one(
            connection,
            "SELECT enabled, expires_at FROM feature_flag WHERE code = %s",
            (code,),
        )
    except psycopg.Error:
        return False
    if row is None:
        return False
    # An expired flag is off whatever its switch says. That is what an expiry
    # date is for, and a flag that outlives it is a permanent branch somebody
    # described as temporary.
    if row["expires_at"] is not None:
        expired = fetch_one(
            connection, "SELECT %s < now() AS expired", (row["expires_at"],)
        )
        if expired and expired["expired"]:
            return False
    return bool(row["enabled"])
