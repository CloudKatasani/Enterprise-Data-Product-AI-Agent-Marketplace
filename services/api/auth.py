"""Identity verification.

Production path: an OIDC bearer token, verified for signature, issuer, audience
and expiry, whose subject maps to a ``party.external_subject``.

Development path: an ``X-Marketplace-Subject`` header naming a seeded party.
This is honoured only when the configured issuer is a local one — a deployment
pointed at a real identity provider ignores the header entirely, so there is no
build in which a header can impersonate a user.
"""

from __future__ import annotations

from fastapi import Request

from services.common.config import get_settings

# Issuer hosts treated as local. A deployment against a real IdP has none of
# these in OIDC_ISSUER and therefore never trusts a header.
LOCAL_ISSUER_MARKERS = ("localhost", "127.0.0.1", ".local", ".invalid", "oidc.local")

BEARER_PREFIX = "bearer "


def _issuer_is_local() -> bool:
    issuer = get_settings().oidc_issuer.lower()
    return any(marker in issuer for marker in LOCAL_ISSUER_MARKERS)


def _subject_from_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith(BEARER_PREFIX):
        return None
    token = header[len(BEARER_PREFIX):].strip()
    if not token:
        return None

    from jose import jwt  # imported lazily so a dev run needs no crypto stack

    settings = get_settings()
    claims = jwt.get_unverified_claims(token) if _issuer_is_local() else jwt.decode(
        token,
        key=settings.oidc_client_secret,
        audience=settings.oidc_client_id,
        issuer=settings.oidc_issuer,
    )
    subject = claims.get("sub")
    return str(subject) if subject else None


def subject_from_request(
    request: Request, header_subject: str | None, header_agent: str | None
) -> tuple[str | None, str | None]:
    """Return ``(party_id, agent_identity)`` for the caller.

    The agent identity is only accepted alongside a user subject: an agent
    acting on nobody's behalf has no user entitlement to intersect with, and
    I12 would have nothing to constrain it.
    """
    subject = _subject_from_bearer(request)
    if subject is None and _issuer_is_local():
        subject = header_subject
    agent = header_agent if subject is not None else None
    return subject, agent
