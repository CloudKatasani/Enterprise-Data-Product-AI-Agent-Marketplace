"""The generator registry. ``npm run gen`` runs every generator, in this order."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from scripts._paths import GENERATED
from scripts.generators import agentcard, ddl, mcp, openapi, sql, types

Generator = Callable[[Path], list[Path]]

GENERATORS: list[tuple[str, Generator]] = [
    ("gen:ddl", ddl.generate),
    ("gen:sql", sql.generate),
    ("gen:mcp", mcp.generate),
    ("gen:types", types.generate),
    ("gen:openapi", openapi.generate),
    ("gen:agentcard", agentcard.generate),
]


def run_all(argv: list[str]) -> int:
    only = set(argv)
    for name, generator in GENERATORS:
        if only and name not in only:
            continue
        written = generator(GENERATED)
        print(f"{name}: {len(written)} file(s)")
    return 0
