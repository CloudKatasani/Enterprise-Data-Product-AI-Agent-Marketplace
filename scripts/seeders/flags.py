"""M12.2 — the feature flags the code actually reads.

Only flags something branches on. A console listing switches that do nothing is
worse than no console: it invites an administrator to turn one off during an
incident and conclude the problem is elsewhere when nothing changes.
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.common import flags

# The canonical model allows release, experiment and operational. Both flags
# here are operational: neither gates an unfinished feature or an experiment, and
# both exist so somebody can turn a working thing off in a hurry.
TYPE_OPERATIONAL = "operational"

DEFINITIONS = (
    (
        flags.ACADEMY_PRE_APPROVED_ACCESS,
        TYPE_OPERATIONAL,
        True,
        "Whether an academy certification pre-approves access for its asset class. "
        "Off, a certification still records what someone learned and stops shortening "
        "their route to a grant.",
    ),
    (
        flags.LANDING_ANSWER_STREAM,
        TYPE_OPERATIONAL,
        True,
        "Whether the front-page hero streams answer pulses. Off, the constellation "
        "keeps its settled frame and the page loses nothing else.",
    ),
)


# Every flag has an owner. A flag nobody owns is a flag nobody retires, and the
# console shows the owner precisely so the question "whose is this?" has an
# answer before the flag is a year old. The role rather than a named person: the
# person changes, the accountability does not.
OWNER_ROLE = "administrator"


def _owner(connection: psycopg.Connection[Any]) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.party_id FROM party p "
            "JOIN role_assignment r ON r.party_id = p.party_id "
            "WHERE r.role_code = %s ORDER BY p.party_id LIMIT 1",
            (OWNER_ROLE,),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"no party holds the {OWNER_ROLE} role; a feature flag without an owner is a "
            "flag nobody retires"
        )
    return str(row["party_id"])


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    owner = _owner(connection)
    for code, flag_type, default, description in DEFINITIONS:
        with connection.cursor() as cursor:
            # The default applies on first write only. ``enabled`` is
            # deliberately absent from the update: a re-seed must never turn a
            # flag back on that an administrator turned off, and a deploy that
            # silently re-enabled a governance switch would make the console a
            # suggestion box.
            cursor.execute(
                "INSERT INTO feature_flag (flag_id, tenant_id, code, flag_type, enabled, "
                "  description, owner_party_id) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (flag_id) DO UPDATE SET "
                "  flag_type = EXCLUDED.flag_type, description = EXCLUDED.description, "
                "  owner_party_id = EXCLUDED.owner_party_id",
                (f"FLG-{tenant}-{code}", tenant, code, flag_type, default, description, owner),
            )
    return len(DEFINITIONS)
