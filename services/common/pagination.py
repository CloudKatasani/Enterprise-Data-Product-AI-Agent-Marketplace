"""Cursor pagination.

Offset pagination drifts when rows are inserted between pages, which for a
catalog means an asset can be shown twice or missed entirely. A cursor encodes
the last row's sort key and id, so the next page continues from a position
rather than from a count.

The cursor is opaque to clients but not secret: it is base64 of the sort tuple,
and a malformed one is a 400 rather than a silent restart from the beginning.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from services.common.problem import bad_request


@dataclass(frozen=True)
class Cursor:
    sort_value: Any
    identifier: str

    def encode(self) -> str:
        # Padding is kept rather than stripped: it makes decoding a plain
        # round trip, with no arithmetic to get wrong.
        payload = json.dumps([self.sort_value, self.identifier], separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")

    @classmethod
    def decode(cls, raw: str) -> Cursor:
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
            sort_value, identifier = payload
        except (ValueError, binascii.Error, TypeError) as error:
            raise bad_request(
                "cursor is malformed; omit it to start from the first page", cursor=raw
            ) from error
        return cls(sort_value=sort_value, identifier=str(identifier))


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    next_cursor: str | None
    total: int | None

    def document(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "next_cursor": self.next_cursor,
            "total": self.total,
        }
