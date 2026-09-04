import 'server-only';

import { apiBaseUrl } from '@/lib/env';
import { SERVICE_UNAVAILABLE } from '@/lib/http-status';

/**
 * Server-side API client.
 *
 * The portal is an ordinary client of the API with no privileged path
 * (BUILD.md section 10), so every server component fetches through here and
 * gets exactly what an external client would get — including the 403 contract
 * and the partial-permission shapes.
 */

export interface Problem {
  type: string;
  status: number;
  detail: string;
  required_scope?: string;
  request_access_url?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  constructor(readonly problem: Problem) {
    super(problem.detail);
    this.name = 'ApiError';
  }
}

function callerHeaders(): Record<string, string> {
  const subject = process.env.PORTAL_DEV_SUBJECT;
  return subject ? { 'X-Marketplace-Subject': subject } : {};
}

type QueryValue = string | number | boolean | readonly string[] | undefined | null;

function toSearchParams(query: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
    } else {
      params.set(key, String(value));
    }
  }
  const rendered = params.toString();
  return rendered ? `?${rendered}` : '';
}

export async function apiGet<T>(
  path: string,
  query: Record<string, QueryValue> = {},
): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}${toSearchParams(query)}`, {
    headers: { accept: 'application/json', ...callerHeaders() },
    cache: 'no-store',
  });

  if (!response.ok) {
    const problem = (await response.json().catch(() => ({
      type: 'about:blank',
      status: response.status,
      detail: response.statusText,
    }))) as Problem;
    throw new ApiError(problem);
  }
  return (await response.json()) as T;
}

/**
 * Fetch that turns an API failure into a value rather than an exception, so a
 * surface can render its error state instead of collapsing the whole page.
 * Every component ships five states; this is what feeds the error one.
 */
export async function apiTry<T>(
  path: string,
  query: Record<string, QueryValue> = {},
): Promise<{ ok: true; data: T } | { ok: false; problem: Problem }> {
  try {
    return { ok: true, data: await apiGet<T>(path, query) };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, problem: error.problem };
    return {
      ok: false,
      problem: {
        type: 'unreachable',
        status: SERVICE_UNAVAILABLE,
        detail: error instanceof Error ? error.message : 'the API is unreachable',
      },
    };
  }
}

/**
 * POST that returns the problem rather than raising it.
 *
 * The agent invocation contract has four outcomes and three of them are
 * problems (403, 422, 424). Treating those as exceptions would push the demo
 * console into an error boundary, when in fact a refusal is a first-class thing
 * to render — often the most interesting thing on the page.
 */
export async function apiPost<T>(
  path: string,
  body: unknown,
): Promise<{ ok: true; data: T } | { ok: false; problem: Problem }> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method: 'POST',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
        ...callerHeaders(),
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });

    const payload = (await response.json().catch(() => ({
      type: 'about:blank',
      status: response.status,
      detail: response.statusText,
    }))) as unknown;

    if (!response.ok) return { ok: false, problem: payload as Problem };
    return { ok: true, data: payload as T };
  } catch (error) {
    return {
      ok: false,
      problem: {
        type: 'unreachable',
        status: SERVICE_UNAVAILABLE,
        detail: error instanceof Error ? error.message : 'the API is unreachable',
      },
    };
  }
}
