"""The Snowflake Cortex Agents runtime adapter.

This is the adapter, not the agent. Cortex plans and writes the prose; this
module's job is to make what comes back satisfy the marketplace's guarantees
before it is allowed to be an :class:`Answer`:

* every tool call Cortex reports is checked against the agent's tool bindings,
  and a call to a tool the version was not granted fails the answer rather than
  being trimmed from the trace;
* every citation is checked against the agent's product bindings and reduced to
  the columns the binding actually grants;
* the trace carries the tokens and cost Cortex reported, not an estimate.

It fails closed. Absent credentials, an absent driver, a malformed response or
a response that cites something the agent cannot read all raise
:class:`RuntimeUnavailable` or :class:`OutOfScope`. It never falls back to the
analytic runtime: an answer that silently came from somewhere else is exactly
the trace lie the whole design is built to prevent.
"""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal
from typing import Any

import psycopg

from services.agent_runtime.base import (
    Answer,
    AskRequest,
    Citation,
    OutOfScope,
    RuntimeUnavailable,
    ToolCall,
)
from services.common.db import fetch_all, fetch_one
from services.common.rubrics import Rubric
from services.common.timing import elapsed_ms

RUNTIME_NAME = "cortex"
CORTEX_PROVIDER = "snowflake"

CONFIDENCE_FULL_PATH = "answer_confidence.complete"
CONFIDENCE_THIN_PATH = "answer_confidence.thin_evidence"
THIN_EVIDENCE_ROWS_PATH = "answer_confidence.thin_evidence_rows"

REQUIRED_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_ROLE", "SNOWFLAKE_PRIVATE_KEY")

# The shape the adapter requires of a Cortex response. Anything missing is a
# malformed response, not a defaulted field.
REQUIRED_KEYS = ("headline", "narrative", "citations", "tool_calls", "usage")


class CortexResponseInvalid(RuntimeUnavailable):
    """Cortex answered, but not in a shape that can be validated.

    A subclass of RuntimeUnavailable because the effect is the same: this
    runtime cannot produce an answer the marketplace is allowed to show.
    """


class CortexRuntime:
    """Adapts Snowflake Cortex Agents to the marketplace's answer contract."""

    name = RUNTIME_NAME

    def __init__(self, rubric: Rubric, client: Any | None = None) -> None:
        self._rubric = rubric
        self._client = client if client is not None else _default_client()

    def ask(self, connection: psycopg.Connection[Any], request: AskRequest) -> Answer:
        started = time.perf_counter()

        version = fetch_one(
            connection,
            "SELECT v.agent_version_id, v.model_provider, v.model_id, p.body AS system_prompt "
            "FROM agent_version v "
            "LEFT JOIN prompt_artifact p ON p.prompt_hash = v.prompt_hash "
            "WHERE v.agent_version_id = %s",
            (request.agent_version_id,),
        )
        if version is None:
            raise OutOfScope(f"no agent version {request.agent_version_id}")
        if version["model_provider"] != CORTEX_PROVIDER:
            raise RuntimeUnavailable(
                f"{request.agent_version_id} is registered against the "
                f"{version['model_provider']!r} provider, not {CORTEX_PROVIDER!r}. A version is "
                "served by the provider it was evaluated under or it is not served."
            )
        if not version["system_prompt"]:
            raise RuntimeUnavailable(
                f"{request.agent_version_id} has no prompt artifact for its prompt_hash; the "
                "adapter will not send a prompt it cannot attribute"
            )

        granted_tools = {
            row["tool_name"]: row["cost_class"]
            for row in fetch_all(
                connection,
                "SELECT tool_name, cost_class FROM agent_tool_binding WHERE agent_version_id = %s",
                (request.agent_version_id,),
            )
        }
        granted_columns = {
            row["product_id"]: set(row["columns_allowed"])
            for row in fetch_all(
                connection,
                "SELECT product_id, columns_allowed FROM agent_product_binding "
                "WHERE agent_version_id = %s",
                (request.agent_version_id,),
            )
        }
        if not granted_tools or not granted_columns:
            raise OutOfScope(
                f"{request.agent_version_id} has no tool or product bindings; a version with "
                "nothing granted answers nothing"
            )

        payload = self._client.ask(
            agent_name=version["model_id"],
            question=request.question,
            system_prompt=version["system_prompt"],
            session_id=request.session_id,
        )
        _require_shape(payload)

        calls = [
            _tool_call(entry, granted_tools, request.agent_version_id)
            for entry in payload["tool_calls"]
        ]
        citations = [
            _citation(connection, entry, granted_columns) for entry in payload["citations"]
        ]
        if not citations:
            raise CortexResponseInvalid(
                "Cortex returned an answer with no citations; an uncited answer is not "
                "publishable at any confidence"
            )

        rows_scanned = sum(call.rows_scanned for call in calls)
        thin = int(self._rubric.number(THIN_EVIDENCE_ROWS_PATH))
        confidence = self._rubric.number(
            CONFIDENCE_THIN_PATH if rows_scanned < thin else CONFIDENCE_FULL_PATH
        )
        usage = payload["usage"]

        return Answer(
            headline=str(payload["headline"]),
            narrative=str(payload["narrative"]),
            visual=dict(payload.get("visual") or {}),
            table=dict(payload.get("table") or {}),
            citations=citations,
            kpi_definitions=list(payload.get("kpi_definitions") or []),
            tool_calls=calls,
            rows_scanned=rows_scanned,
            latency_ms=elapsed_ms(started),
            tokens_in=int(usage["tokens_in"]),
            tokens_out=int(usage["tokens_out"]),
            cost_usd=Decimal(str(usage["cost_usd"])),
            confidence=confidence,
            runtime=self.name,
            claims={key: Decimal(str(value)) for key, value in (payload.get("claims") or {}).items()},
            notes=list(payload.get("notes") or []),
        )


def _require_shape(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise CortexResponseInvalid(f"Cortex returned {type(payload).__name__}, not an object")
    missing = [key for key in REQUIRED_KEYS if key not in payload]
    if missing:
        raise CortexResponseInvalid(
            "Cortex response is missing " + ", ".join(missing) + "; the adapter does not "
            "supply defaults for a field the trace depends on"
        )
    usage = payload["usage"]
    if not isinstance(usage, dict) or not {"tokens_in", "tokens_out", "cost_usd"} <= set(usage):
        raise CortexResponseInvalid("Cortex response carries no usable token or cost usage")


def _tool_call(entry: Any, granted: dict[str, str], version_id: str) -> ToolCall:
    if not isinstance(entry, dict) or "tool" not in entry:
        raise CortexResponseInvalid("a reported tool call names no tool")
    tool = str(entry["tool"])
    if tool not in granted:
        raise OutOfScope(
            f"Cortex reported a call to {tool!r}, which {version_id} is not bound to. "
            "The answer is refused rather than served with the call removed from its trace."
        )
    return ToolCall(
        tool=tool,
        arguments=dict(entry.get("arguments") or {}),
        rows_returned=int(entry.get("rows_returned") or 0),
        rows_scanned=int(entry.get("rows_scanned") or 0),
        duration_ms=int(entry.get("duration_ms") or 0),
        cost_class=granted[tool],
    )


def _citation(
    connection: psycopg.Connection[Any], entry: Any, granted: dict[str, set[str]]
) -> Citation:
    if not isinstance(entry, dict) or "product_id" not in entry:
        raise CortexResponseInvalid("a citation names no product")
    product_id = str(entry["product_id"])
    allowed = granted.get(product_id)
    if allowed is None:
        raise OutOfScope(
            f"Cortex cited {product_id}, which this agent version is not bound to"
        )
    cited = [str(name) for name in (entry.get("columns") or [])]
    ungranted = [name for name in cited if name not in allowed]
    if ungranted:
        raise OutOfScope(
            f"Cortex cited columns on {product_id} the binding does not grant: "
            + ", ".join(sorted(ungranted))
        )

    contract = fetch_one(
        connection,
        "SELECT semver FROM data_contract_version WHERE product_id = %s AND status = 'active'",
        (product_id,),
    )
    if contract is None:
        raise OutOfScope(f"{product_id} has no active contract to cite")

    return Citation(
        product_id=product_id,
        contract_version=str(contract["semver"]),
        columns=tuple(cited),
        as_of=entry.get("as_of"),
    )


class _RestClient:
    """The real client. Constructed only when credentials are present."""

    def __init__(self) -> None:
        try:
            import snowflake.connector  # noqa: F401
        except ImportError as error:  # pragma: no cover - needs the driver installed
            raise RuntimeUnavailable(
                "snowflake-connector-python is not installed; the cortex runtime cannot "
                "reach Cortex Agents"
            ) from error
        self._account = os.environ["SNOWFLAKE_ACCOUNT"]

    def ask(
        self, *, agent_name: str, question: str, system_prompt: str, session_id: str
    ) -> dict[str, Any]:  # pragma: no cover - needs a Snowflake account
        import snowflake.connector

        connection = snowflake.connector.connect(
            account=self._account,
            user=os.environ["SNOWFLAKE_USER"],
            role=os.environ["SNOWFLAKE_ROLE"],
            private_key=os.environ["SNOWFLAKE_PRIVATE_KEY"].encode("utf-8"),
            session_parameters={"QUERY_TAG": f"marketplace-agent:{session_id}"},
        )
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT SNOWFLAKE.CORTEX.AGENT_RUN(%s, %s, %s) AS response",
                (agent_name, question, system_prompt),
            )
            row = cursor.fetchone()
        finally:
            cursor.close()
            connection.close()
        if row is None:
            raise CortexResponseInvalid("Cortex returned no rows")
        return json.loads(row[0])


def _default_client() -> Any:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeUnavailable(
            "the cortex runtime needs " + ", ".join(missing) + ". Set AGENT_RUNTIME=analytic "
            "to serve answers from the demo tier instead; the adapter will not silently "
            "answer from somewhere other than where it says it did."
        )
    return _RestClient()
