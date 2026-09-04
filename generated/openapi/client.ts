// AUTO-GENERATED FROM services/api/main.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: f40e68c6735073adc5ae1f4c25783b86f7515564d2c4f6a3e698d00ac523c89d  generated_at: 2026-09-04T03:30:50+00:00

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

  /** Hybrid search across products, agents and KPIs */
  getDiscover(query?: { q?: unknown, asset_type?: unknown, limit?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/discover`, query, undefined, options);
  }

  /** Liveness probe */
  getHealth(options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/health`, undefined, undefined, options);
  }

  /** Certified KPI register with synonyms */
  getKpis(query?: { domain?: unknown, status?: unknown, cursor?: unknown, limit?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/kpis`, query, undefined, options);
  }

  /** Definition, versions and every consumer of a KPI */
  getKpisKpi_id(kpi_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/kpis/${kpi_id}`, undefined, undefined, options);
  }

  /** Search, filter and page the product catalog */
  getProducts(query?: { industry?: unknown, domain?: unknown, archetype?: unknown, certification?: unknown, sensitivity?: unknown, tier?: unknown, owner?: unknown, endpoint?: unknown, kpi?: unknown, quality_band?: unknown, sort?: unknown, cursor?: unknown, limit?: unknown, featured?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products`, query, undefined, options);
  }

  /** Full product listing */
  getProductsProduct_id(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}`, undefined, undefined, options);
  }

  /** Usage and adoption within the caller's scope */
  getProductsProduct_idConsumption(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/consumption`, undefined, undefined, options);
  }

  /** Contract source, conformance history and version list */
  getProductsProduct_idContract(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/contract`, undefined, undefined, options);
  }

  /** Consumption surfaces and whether the caller may use them */
  getProductsProduct_idEndpoints(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/endpoints`, undefined, undefined, options);
  }

  /** Upstream and downstream lineage */
  getProductsProduct_idLineage(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/lineage`, undefined, undefined, options);
  }

  /** Mesh neighbourhood with strength, confidence and rationale */
  getProductsProduct_idMesh(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/mesh`, undefined, undefined, options);
  }

  /** Current composite, history and contributing rule results */
  getProductsProduct_idQuality(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/quality`, undefined, undefined, options);
  }

  /** Column list with classification and masking state */
  getProductsProduct_idSchema(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/schema`, undefined, undefined, options);
  }

  /** Value case, assumptions with sample sizes, and measurements */
  getProductsProduct_idValue(product_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/products/${product_id}/value`, undefined, undefined, options);
  }

}
