// AUTO-GENERATED FROM services/api/main.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 7fc085a9fc5801095d41f469f80bea2627d253a40b4b9672723b7b41e693ec79  generated_at: 2026-09-04T02:52:34+00:00

/* eslint-disable */
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
  const url = new URL(baseUrl.replace(/\/+$/, '') + path);
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

export class MarketplaceClient {
  constructor(private readonly baseUrl: string) {}

  /** Health */
  getHealth(options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/health`, undefined, undefined, options);
  }

}
