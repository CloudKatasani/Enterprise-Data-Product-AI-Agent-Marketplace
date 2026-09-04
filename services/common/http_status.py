"""HTTP status codes.

The only module in ``services/`` allowed to carry bare numeric literals
(see ``scripts/lint/no_magic_numbers.py``). Everything else imports from here so
status codes never look like thresholds.
"""

from __future__ import annotations

from http import HTTPStatus

OK = int(HTTPStatus.OK)
CREATED = int(HTTPStatus.CREATED)
ACCEPTED = int(HTTPStatus.ACCEPTED)
NO_CONTENT = int(HTTPStatus.NO_CONTENT)
BAD_REQUEST = int(HTTPStatus.BAD_REQUEST)
UNAUTHORIZED = int(HTTPStatus.UNAUTHORIZED)
FORBIDDEN = int(HTTPStatus.FORBIDDEN)
NOT_FOUND = int(HTTPStatus.NOT_FOUND)
CONFLICT = int(HTTPStatus.CONFLICT)
UNPROCESSABLE_ENTITY = int(HTTPStatus.UNPROCESSABLE_ENTITY)
FAILED_DEPENDENCY = int(HTTPStatus.FAILED_DEPENDENCY)
TOO_MANY_REQUESTS = int(HTTPStatus.TOO_MANY_REQUESTS)
INTERNAL_SERVER_ERROR = int(HTTPStatus.INTERNAL_SERVER_ERROR)
SERVICE_UNAVAILABLE = int(HTTPStatus.SERVICE_UNAVAILABLE)
