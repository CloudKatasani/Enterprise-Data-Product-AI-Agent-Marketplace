"""gen:openapi — the FastAPI application to an OpenAPI 3.1 document and a TS client.

The document is generated from the routes themselves rather than written by
hand, so the contract test in ``tests/contract`` compares two views of the same
source and a route that drifts from its schema fails the build.

The TypeScript client is what the portal calls. It is generated so the portal
cannot invent a path or a query parameter that the API does not serve.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from scripts.generators.header import content_digest, write_generated

VERSION = "1.0.0"
SOURCE = "services/api/main.py"

# The generator boots the app, so it needs a valid environment. These are
# placeholders used only to satisfy validation during generation; nothing
# connects to them.
GENERATION_ENV = {
    "PRODUCT_NAME": "Marketplace",
    "TENANT_ID": "TEN-GEN",
    "DATABASE_URL": "postgresql://generation/none",
    "REDIS_URL": "redis://generation/0",
    "OIDC_ISSUER": "https://generation.invalid",
    "OIDC_CLIENT_ID": "generation",
    "OIDC_CLIENT_SECRET": "generation",
    "SNOWFLAKE_ACCOUNT": "generation",
    "SNOWFLAKE_USER": "generation",
    "SNOWFLAKE_ROLE": "MKT_READONLY",
    "SNOWFLAKE_PRIVATE_KEY": "",
    "AGENT_RUNTIME": "analytic",
    "MODEL_PROVIDER": "generation",
    "MODEL_ID": "generation",
    "MODEL_MAX_TOKENS": "2000",
    "DEMO_TIER_SCHEMA": "MARKETPLACE_DEMO",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://generation.invalid",
    "FEATURE_FLAG_SOURCE": "env",
    "WORKER_POLL_SECONDS": "5",
    "API_BASE_URL": "http://generation.invalid/api/v1",
    "PORTAL_BASE_URL": "http://generation.invalid",
}

TS_HEADER = """/* eslint-disable */
/**
 * Generated API client. The portal is an ordinary client of the API with no
 * privileged path, so every call the portal makes goes through this file.
 */

export interface RequestOptions {
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Record<string, unknown>,
  ) {
    super(typeof problem.detail === 'string' ? problem.detail : `request failed (${status})`);
    this.name = 'ApiError';
  }
}

async function request<T>(
  baseUrl: string,
  method: string,
  path: string,
  query: Record<string, unknown> | undefined,
  body: unknown,
  options: RequestOptions,
): Promise<T> {
  const url = new URL(baseUrl.replace(/\\/+$/, '') + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) url.searchParams.append(key, String(item));
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  const response = await fetch(url, {
    method,
    headers: { 'content-type': 'application/json', ...(options.headers ?? {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
    ...(options.signal ? { signal: options.signal } : {}),
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new ApiError(response.status, problem as Record<string, unknown>);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
"""


def _operation_name(path: str, method: str) -> str:
    segments = [
        segment.strip("{}").replace("-", "_")
        for segment in path.replace("/api/v1", "").split("/")
        if segment
    ]
    prefix = {"get": "get", "post": "post", "delete": "delete", "put": "put"}[method]
    parts = [prefix, *segments]
    head, *tail = parts
    return head + "".join(part.capitalize() for part in tail)


def _client(document: dict[str, Any]) -> str:
    lines = [TS_HEADER, "export class MarketplaceClient {", "  constructor(private readonly baseUrl: string) {}", ""]
    for path in sorted(document.get("paths", {})):
        operations = document["paths"][path]
        for method in sorted(operations):
            if method not in {"get", "post", "delete", "put"}:
                continue
            operation = operations[method]
            name = _operation_name(path, method)
            parameters = operation.get("parameters", [])
            path_params = [p for p in parameters if p.get("in") == "path"]
            query_params = [p for p in parameters if p.get("in") == "query"]
            has_body = "requestBody" in operation

            args = [f"{p['name'].replace('-', '_')}: string" for p in path_params]
            if query_params:
                fields = ", ".join(f"{p['name']}?: unknown" for p in query_params)
                args.append(f"query?: {{ {fields} }}")
            if has_body:
                args.append("body?: unknown")
            args.append("options: RequestOptions = {}")

            template = path
            for parameter in path_params:
                template = template.replace(
                    "{" + parameter["name"] + "}",
                    "${" + parameter["name"].replace("-", "_") + "}",
                )
            summary = operation.get("summary") or operation.get("description") or name
            lines.append(f"  /** {summary} */")
            lines.append(f"  {name}({', '.join(args)}): Promise<unknown> {{")
            lines.append(
                f"    return request(this.baseUrl, '{method.upper()}', `{template}`, "
                f"{'query' if query_params else 'undefined'}, "
                f"{'body' if has_body else 'undefined'}, options);"
            )
            lines.append("  }")
            lines.append("")
    lines.append("}")
    return "\n".join(lines)


def generate(output_root: Path) -> list[Path]:
    previous = {key: os.environ.get(key) for key in GENERATION_ENV}
    for key, value in GENERATION_ENV.items():
        os.environ.setdefault(key, value)
    try:
        from services.api.main import create_app

        document = create_app().openapi()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)

    # The document describes the API contract, which is deployment-independent.
    # The running app titles itself with the deployment's PRODUCT_NAME, so the
    # generator replaces the title with a fixed one — otherwise the artifact
    # would differ between two machines that generate the same code (I9), and a
    # deployment's brand would leak into a committed file (I13).
    document["info"]["title"] = "Data Product and AI Agent Marketplace API"

    # The version string is the API's, not the run's, so a rebuild of the same
    # code produces the same document. The provenance marker lives under info as
    # an OpenAPI extension, the only place the specification allows an unknown key.
    digest = content_digest(json.dumps(document, indent=2, sort_keys=True))
    document.setdefault("info", {})["x-generated"] = {
        "from": SOURCE,
        "by": "scripts/gen.py",
        "generator_version": VERSION,
        "manifest_hash": digest,
        "warning": "DO NOT EDIT",
    }
    body = json.dumps(document, indent=2, sort_keys=True)

    written: list[Path] = []
    document_path = output_root / "openapi" / "openapi.json"
    write_generated(
        document_path, body, source=SOURCE, version=VERSION, digest=digest, json_style=True
    )
    written.append(document_path)

    client_path = output_root / "openapi" / "client.ts"
    write_generated(client_path, _client(document), source=SOURCE, version=VERSION, digest=digest)
    written.append(client_path)
    return written
