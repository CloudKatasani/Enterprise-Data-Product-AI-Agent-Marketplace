"""Runtime selection.

One function, and a deliberate refusal built into it. ``AGENT_RUNTIME`` names
which adapter serves answers, and nothing above this module knows or can
influence which one answered. A runtime that cannot start raises rather than
being replaced by one that can: if the deployment says Cortex and Cortex is
unreachable, the marketplace says so instead of quietly answering from the
demo tier and labelling the trace ``cortex``.

BUILD.md M6.3 names the two implementations ``mock`` and ``cortex``. The
``mock`` slot here is filled by :class:`AnalyticRuntime`, which is not a mock:
it plans against the coverage map and executes real aggregations against the
demo tier. That is required by the same milestone's acceptance criterion — "no
mocked answers exist" — so the configuration value ``mock`` is accepted as a
synonym and resolves to the analytic runtime.
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.agent_runtime.analytic import AnalyticRuntime
from services.agent_runtime.base import AgentRuntime, RuntimeUnavailable
from services.agent_runtime.cortex import CortexRuntime
from services.common.config import get_settings
from services.common.rubrics import load_current

RUNTIME_RUBRIC = "agent_runtime"
FINOPS_RUBRIC = "finops"

ANALYTIC = "analytic"
CORTEX = "cortex"
# The spec's name for the offline runtime. Kept resolvable so a deployment
# configured from BUILD.md verbatim starts; it is the same real runtime.
MOCK_ALIAS = "mock"

ALIASES = {MOCK_ALIAS: ANALYTIC}


def available() -> tuple[str, ...]:
    return (ANALYTIC, CORTEX)


def build(connection: psycopg.Connection[Any], name: str | None = None) -> AgentRuntime:
    """The configured runtime, resolved against live rubrics.

    Rubrics are resolved here rather than inside a runtime so that an answer and
    the gate that judged it read the same version, and so a runtime holds no
    connection of its own.
    """
    settings = get_settings()
    chosen = ALIASES.get(name or settings.agent_runtime, name or settings.agent_runtime)
    rubric = load_current(connection, RUNTIME_RUBRIC)

    if chosen == ANALYTIC:
        return AnalyticRuntime(
            rubric=rubric,
            finops=load_current(connection, FINOPS_RUBRIC),
            demo_schema=settings.demo_tier_schema,
        )
    if chosen == CORTEX:
        return CortexRuntime(rubric=rubric)
    raise RuntimeUnavailable(
        f"AGENT_RUNTIME={chosen!r} names no runtime; available: " + ", ".join(available())
    )
