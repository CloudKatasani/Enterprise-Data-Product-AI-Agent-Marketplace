"""The agent runtime adapter interface (BUILD.md section 3, M6.3).

The marketplace catalogues and governs agents; it does not author them. What it
needs from a runtime is narrow and identical whichever one is configured:

    ask(request) -> Answer

An :class:`Answer` carries the four things the marketplace's guarantees are
built on — the answer body, the citations behind every number in it, the KPI
definitions it answered under, and the trace of what it actually did. A runtime
that cannot produce those cannot be adapted, because there would be nothing to
validate.

Two implementations ship: ``analytic`` (deterministic, executes real queries
against the demo tier, no model) and ``cortex`` (Snowflake Cortex Agents). The
runtime is chosen by ``AGENT_RUNTIME``; nothing above this module knows which
one answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol


class OutOfScope(Exception):
    """The question falls outside the agent's coverage map.

    Carries the agents that do cover it, so the refusal names a route rather
    than being a dead end (section 10.2).
    """

    def __init__(self, detail: str, suggested_agents: list[str] | None = None) -> None:
        self.detail = detail
        self.suggested_agents = suggested_agents or []
        super().__init__(detail)


class EntitlementShortfall(Exception):
    """The caller may not read what the question needs.

    Distinct from OutOfScope: the agent covers the question, the caller is not
    entitled to the answer. It names the asset and the scope to request, and
    never the columns that are missing — telling a caller which column they
    cannot see tells them the column exists.
    """

    def __init__(self, detail: str, *, asset_id: str, required_scope: str) -> None:
        self.detail = detail
        self.asset_id = asset_id
        self.required_scope = required_scope
        super().__init__(detail)


class RuntimeUnavailable(RuntimeError):
    """The configured runtime cannot answer. Never silently downgraded."""


@dataclass(frozen=True)
class AskRequest:
    agent_id: str
    agent_version_id: str
    question: str
    tier: str
    purpose: str
    session_id: str
    principal_id: str
    on_behalf_of: str | None = None
    exchange_id: str | None = None


@dataclass(frozen=True)
class Citation:
    """Where a number came from. Every numeric claim resolves to one of these."""

    product_id: str
    contract_version: str
    columns: tuple[str, ...]
    as_of: datetime | None

    def document(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "contract_version": self.contract_version,
            "columns": list(self.columns),
            "as_of": self.as_of.isoformat() if self.as_of else None,
        }


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation, with what it cost. Rendered in the trace rail (M7.2)."""

    tool: str
    arguments: dict[str, Any]
    rows_returned: int
    rows_scanned: int
    duration_ms: int
    cost_class: str

    def document(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "rows_returned": self.rows_returned,
            "rows_scanned": self.rows_scanned,
            "duration_ms": self.duration_ms,
            "cost_class": self.cost_class,
        }


@dataclass
class Answer:
    headline: str
    narrative: str
    visual: dict[str, Any]
    table: dict[str, Any]
    citations: list[Citation]
    kpi_definitions: list[str]
    tool_calls: list[ToolCall]
    rows_scanned: int
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    confidence: Decimal
    runtime: str
    # Numbers the answer asserts, keyed by the label they appear under. The
    # grounding validator checks each one against the citations (M7.3).
    claims: dict[str, Decimal] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # Display strings, formatted by the runtime from its rubric. The portal
    # carries no numeric literals, so a precision chosen in a component would be
    # a number nobody could find later; it is chosen here and travels with the
    # answer it describes.
    cost_display: str = ""
    confidence_display: str = ""

    def document(self) -> dict[str, Any]:
        return {
            "answer": {
                "headline": self.headline,
                "narrative": self.narrative,
                "visual": self.visual,
                "table": self.table,
            },
            "citations": [citation.document() for citation in self.citations],
            "kpi_definitions": list(self.kpi_definitions),
            "trace": {
                "runtime": self.runtime,
                "tool_calls": [call.document() for call in self.tool_calls],
                "rows_scanned": self.rows_scanned,
                "latency_ms": self.latency_ms,
                "tokens": {"in": self.tokens_in, "out": self.tokens_out},
                "cost_usd": float(self.cost_usd),
                "cost_display": self.cost_display,
            },
            "confidence": float(self.confidence),
            "confidence_display": self.confidence_display,
            "notes": list(self.notes),
        }


class AgentRuntime(Protocol):
    name: str

    def ask(self, connection: Any, request: AskRequest) -> Answer: ...
