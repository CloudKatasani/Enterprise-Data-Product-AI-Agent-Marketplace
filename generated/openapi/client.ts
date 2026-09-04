// AUTO-GENERATED FROM services/api/main.py BY scripts/gen.py — DO NOT EDIT
// generator_version: 1.0.0  manifest_hash: 749cb34dd1230363b0f9b6dc1580c591486ab3ef16fd345aca42b6d10aafba5c  generated_at: 2026-09-04T06:38:41+00:00

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

  /** Filter and page the agent catalog */
  getAgents(query?: { industry?: unknown, domain?: unknown, autonomy?: unknown, certification?: unknown, kpi?: unknown, product?: unknown, sort?: unknown, cursor?: unknown, limit?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/agents`, query, undefined, options);
  }

  /** Full agent listing */
  getAgentsAgent_id(agent_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/agents/${agent_id}`, undefined, undefined, options);
  }

  /** Ask the agent a question and receive an answer with its trace */
  postAgentsAgent_idAsk(agent_id: string, body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/agents/${agent_id}/ask`, undefined, body, options);
  }

  /** KPI coverage with evaluation accuracy and sample size */
  getAgentsAgent_idCoverage(agent_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/agents/${agent_id}/coverage`, undefined, undefined, options);
  }

  /** Curated exchanges and their validation state */
  getAgentsAgent_idDemo(agent_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/agents/${agent_id}/demo`, undefined, undefined, options);
  }

  /** Suite results, pass rate and regression history */
  getAgentsAgent_idEvaluation(agent_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/agents/${agent_id}/evaluation`, undefined, undefined, options);
  }

  /** Accept or reject an answer; a rejected defect becomes an evaluation case */
  postAgentsAgent_idFeedback(agent_id: string, body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/agents/${agent_id}/feedback`, undefined, body, options);
  }

  /** The public demand board */
  getDemand(options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/demand`, undefined, undefined, options);
  }

  /** File new-supply demand */
  postDemand(body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/demand`, undefined, body, options);
  }

  /** Does the estate already supply this? Run before submitting. */
  postDemandCheck(body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/demand/check`, undefined, body, options);
  }

  /** Vote, with the one-line use case that makes it countable */
  postDemandDemand_idVote(demand_id: string, body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/demand/${demand_id}/vote`, undefined, body, options);
  }

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

  /** The agent mesh */
  getMeshAgents(query?: { mode?: unknown, domain?: unknown, min_strength?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/mesh/agents`, query, undefined, options);
  }

  /** The data product mesh */
  getMeshData(query?: { mode?: unknown, scope?: unknown, domain?: unknown, min_strength?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/mesh/data`, query, undefined, options);
  }

  /** Everything downstream of one source system */
  getMeshDataBlast_radius(query?: { source?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/mesh/data/blast-radius`, query, undefined, options);
  }

  /** KPIs more than one agent answers on, and whether they agree */
  getMeshDivergence(options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/mesh/divergence`, undefined, undefined, options);
  }

  /** Source systems, for the source-anchored layout */
  getMeshSources(options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/mesh/sources`, undefined, undefined, options);
  }

  /** The health plane */
  getObservability(options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/observability`, undefined, undefined, options);
  }

  /** What must be shown on this listing right now */
  getObservabilityBanners(query?: { asset_type?: unknown, asset_id?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/observability/banners`, query, undefined, options);
  }

  /** Add owner context. It cannot suppress consumer notification. */
  postObservabilityIncidentsIncident_idContext(incident_id: string, body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/observability/incidents/${incident_id}/context`, undefined, body, options);
  }

  /** Resolve with a root cause. The cause is required. */
  postObservabilityIncidentsIncident_idResolve(incident_id: string, body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/observability/incidents/${incident_id}/resolve`, undefined, body, options);
  }

  /** Run the detectors and raise incidents for what they find */
  postObservabilityScan(query?: { only?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/observability/scan`, query, undefined, options);
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

  /** Tier-weighted estate quality with its breakdown */
  getQualityEstate(options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/quality/estate`, undefined, undefined, options);
  }

  /** Draft an access request; it is evaluated on creation */
  postRequestsAccess(body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/requests/access`, undefined, body, options);
  }

  /** What will happen to this request, before it is submitted */
  postRequestsAccessEvaluate(body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/requests/access/evaluate`, undefined, body, options);
  }

  /** Record one approver's decision */
  postRequestsAccessRequest_idDecide(request_id: string, body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/requests/access/${request_id}/decide`, undefined, body, options);
  }

  /** Submit an evaluated request; a blocked one is refused */
  postRequestsAccessRequest_idSubmit(request_id: string, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/requests/access/${request_id}/submit`, undefined, undefined, options);
  }

  /** The audit trail as newline-delimited JSON */
  getRequestsAudit.ndjson(query?: { event?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/requests/audit.ndjson`, query, undefined, options);
  }

  /** The public backlog, declines included with their reasons */
  getRequestsBacklog(query?: { asset_id?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/requests/backlog`, query, undefined, options);
  }

  /** Raise an enhancement request against an asset */
  postRequestsEnhancement(body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/requests/enhancement`, undefined, body, options);
  }

  /** Move an enhancement request along its lifecycle */
  postRequestsEnhancementRequest_idAdvance(request_id: string, body?: unknown, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/requests/enhancement/${request_id}/advance`, undefined, body, options);
  }

  /** The entitlement register: who holds what, for what, until when */
  getRequestsEntitlements(query?: { principal_id?: unknown, mine?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/requests/entitlements`, query, undefined, options);
  }

  /** Every transition, in order, with its actor */
  getRequestsRequest_idHistory(request_id: string, query?: { workflow?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/requests/${request_id}/history`, query, undefined, options);
  }

  /** The value plane */
  getValue(query?: { days?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/value`, query, undefined, options);
  }

  /** The board pack, read from the stored snapshot and never recomputed */
  getValueBoard_packSnapshot_ref(snapshot_ref: string, query?: { fmt?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'GET', `/api/v1/value/board-pack/${snapshot_ref}`, query, undefined, options);
  }

  /** Compute the portfolio once and record it */
  postValueSnapshot(query?: { days?: unknown }, options: RequestOptions = {}): Promise<unknown> {
    return request(this.baseUrl, 'POST', `/api/v1/value/snapshot`, query, undefined, options);
  }

}
