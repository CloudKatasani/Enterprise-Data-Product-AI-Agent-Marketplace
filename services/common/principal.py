"""The calling principal, and what it is entitled to.

Effective permission is never cached (section 23): every request resolves the
caller's grants from the entitlement register, and every data-plane call is
enforced by the platform on top of that. This module answers two questions —
who is calling, and which scopes do they hold right now — and nothing else.

Delegated calls (an agent acting for a user) carry both identities, and the
effective scope is the **intersection** of the two (I12). The intersection is
computed here so no route can accidentally take the union.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import Header, Request

from services.common import http_status
from services.common.db import fetch_all
from services.common.problem import Problem

# Scope granted to every authenticated caller: the catalog is browsable, which
# is what makes "see it before you can query it" possible (section 12).
METADATA_SCOPE_SUFFIX = "read_metadata"


@dataclass(frozen=True)
class Principal:
    party_id: str
    display_name: str
    roles: frozenset[str]
    on_behalf_of: str | None = None
    agent_identity: str | None = None

    @property
    def is_delegated(self) -> bool:
        return self.agent_identity is not None

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))


class Unauthenticated(Problem):
    def __init__(self) -> None:
        super().__init__(
            http_status.UNAUTHORIZED,
            "unauthenticated",
            "the request carries no verifiable identity",
        )


def _load_party(connection: psycopg.Connection[Any], party_id: str) -> dict[str, Any] | None:
    rows = fetch_all(
        connection,
        "SELECT p.party_id, p.display_name, p.active, "
        "       coalesce(array_agg(r.role_code) FILTER (WHERE r.role_code IS NOT NULL), "
        "                '{}') AS roles "
        "FROM party p LEFT JOIN role_assignment r ON r.party_id = p.party_id "
        "WHERE p.party_id = %s GROUP BY p.party_id, p.display_name, p.active",
        (party_id,),
    )
    return rows[0] if rows else None


def resolve_principal(
    connection: psycopg.Connection[Any],
    party_id: str | None,
    *,
    agent_identity: str | None = None,
) -> Principal:
    """Resolve a verified subject into a principal, or refuse.

    Identity verification (OIDC signature, audience, expiry) happens in the
    dependency that calls this; by the time a party id arrives here it has been
    verified. An unknown or deactivated party is refused rather than treated as
    an anonymous caller.
    """
    if not party_id:
        raise Unauthenticated()
    party = _load_party(connection, party_id)
    if party is None or not party["active"]:
        raise Unauthenticated()
    return Principal(
        party_id=party["party_id"],
        display_name=party["display_name"],
        roles=frozenset(party["roles"]),
        on_behalf_of=party_id if agent_identity else None,
        agent_identity=agent_identity,
    )


# The visitor nobody has identified. Named rather than improvised at each call
# site, so "unauthenticated" is one object with no roles and no party, and a
# surface that serves it cannot accidentally be handed a real principal's
# identity by a refactor. Its party id matches no row, so `held_scopes` returns
# the empty set and every asset presents as request-required — which is the
# truth for a caller nobody has identified.
ANONYMOUS = Principal(
    party_id="", display_name="a visitor", roles=frozenset(), on_behalf_of=None,
    agent_identity=None,
)


def held_scopes(connection: psycopg.Connection[Any], party_id: str) -> frozenset[str]:
    if not party_id:
        return frozenset()
    """OAuth scopes carried by the caller's live grants.

    Read fresh on every call. A grant that expired a second ago is not in the
    result, which is the point of not caching effective permission.
    """
    rows = fetch_all(
        connection,
        "SELECT unnest(oauth_scopes) AS scope FROM entitlement_grant "
        "WHERE principal_id = %s AND revoked_at IS NULL AND expires_at > now()",
        (party_id,),
    )
    return frozenset(row["scope"] for row in rows)


def effective_scopes(
    connection: psycopg.Connection[Any], principal: Principal
) -> frozenset[str]:
    """I12 — effective access is the intersection, never the union.

    An agent can never widen a user's access: where a call is delegated, a scope
    counts only if both the agent's machine identity and the user on whose
    behalf it acts hold it.
    """
    user_scopes = held_scopes(connection, principal.party_id)
    if not principal.is_delegated or principal.agent_identity is None:
        return user_scopes
    agent_scopes = held_scopes(connection, principal.agent_identity)
    return user_scopes & agent_scopes


def require_scope(
    connection: psycopg.Connection[Any], principal: Principal, scope: str, *, asset_id: str,
    surface: str,
) -> None:
    """Fail closed with the 403 contract when the caller lacks a scope."""
    from services.common.problem import entitlement_missing

    if scope not in effective_scopes(connection, principal):
        raise entitlement_missing(scope, asset_id=asset_id, surface=surface)


async def current_principal(
    request: Request,
    x_marketplace_subject: str | None = Header(default=None),
    x_marketplace_agent: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency resolving the caller.

    In a deployment the subject comes from a validated OIDC token; the header is
    the development and test path and is only honoured when the issuer is a
    local one, so a production deployment cannot be impersonated by a header.
    """
    from services.api.auth import subject_from_request

    connection = request.state.connection
    subject, agent = subject_from_request(request, x_marketplace_subject, x_marketplace_agent)
    return resolve_principal(connection, subject, agent_identity=agent)
