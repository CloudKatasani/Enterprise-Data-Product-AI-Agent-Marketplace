# 01 — Functional specification

What the system does, for whom, and by what rules. Documents 02–04 say how it is constructed.

Counts in this document are the **as-built estate**, read from `manifests/` rather than from the
brief: 23 data products, 30 agents, 112 KPIs, 150 curated demo exchanges.

---

## 1. Mission and scope

An enterprise marketplace where data products and the AI agents that run on them are catalogued,
governed, requested, observed and demonstrated **as one supply chain**.

A business user must be able to:

- browse domain data products and AI agents in one catalogue;
- see — before clicking anything — each asset's quality score, freshness, owner, adoption and the
  agents attached to it;
- watch an agent answer five curated questions live, with citations, before requesting access;
- request access, an enhancement, or entirely new supply through governed rails;
- see two meshes: data products linked by shared upstream sources, agents linked by shared KPIs and
  products;
- see usage, adoption and a quantified value case for every asset.

**Out of scope, deliberately.** Building pipelines. Being an identity provider. Being the data
catalogue of record. Authoring agents — the marketplace catalogues and governs agents authored
elsewhere. A client asking for any of these is asking for a different product; integrate, do not
absorb.

**The name is not in the source.** `PRODUCT_NAME` is a deployment value and a CI lint
(`lint:no-brand-strings`) fails the build on any brand string or raw hex colour outside token files
(I13).

---

## 2. The fourteen invariants

Implemented as database constraints, publish-gate tests and CI checks — not as documentation.

| # | Invariant | Enforced by | Status |
|---|---|---|---|
| I1 | Exactly one active `kpi_definition` per (tenant, kpi_name) | Partial unique index + publish gate | **[BUILT]** |
| I2 | A `quality_score_snapshot` without `rubric_version` is invalid | NOT NULL + write-path test | **[BUILT]** |
| I3 | An `agent_version` cannot publish with fewer than five `demo_exchange` rows | Publish gate | **[BUILT]** |
| I4 | Every `agent_kpi_coverage` row cites an existing `kpi_definition` | FK + gate | **[BUILT]** |
| I5 | `data_product.sensitivity_tier` is derived from columns, never written directly | `derive_sensitivity()` + trigger | **[BUILT]** |
| I6 | Every `mesh_edge_*` row has `confidence` and a non-empty `rationale` | NOT NULL + render filter | **[BUILT]** |
| I7 | `known_limitations` and agent `out_of_scope` are non-empty and not "none" | CHECK constraint + gate | **[BUILT]** |
| I8 | Connectors cannot write to any customer platform | Kill test (`tests/kill/`) | **[BUILT]** |
| I9 | Regenerating artifacts from manifests produces no diff | `npm run gen:diff` in CI | **[BUILT]** |
| I10 | No numeric threshold in application source | `lint:no-magic-numbers` | **[BUILT]** |
| I11 | Every agent numeric claim carries a resolvable citation | Groundedness eval, blocking at 100% | **[BUILT]** |
| I12 | Effective agent access = intersection(agent scope, user entitlement) | Security suite | **[BUILT]** |
| I13 | No brand string or raw hex colour outside token files | `lint:no-brand-strings` | **[BUILT]** |
| I14 | Landing CLS = 0 and ambient motion holds ≥58 fps throttled | Lighthouse + Playwright trace | **[BUILT]** |

Five rules of engagement sit alongside them and are equally binding:

- **Nothing numeric lives in application source.** Every weight, threshold, band, SLA target and
  coefficient lives in a rubric, seeded from YAML and versioned (14 rubrics today).
- **Generated files are never hand-edited.** Everything under `generated/` is header-stamped and
  regenerated from `manifests/` plus the canonical model.
- **Every inference carries `confidence` and `rationale`** — mesh edges, duplicate matches, value
  estimates. Below the rubric's confidence floor a record is not displayed until `reviewed_by` is
  set.
- **No row-level customer data in the default build.** Metadata, contracts and aggregate telemetry
  only.
- **Fail closed.** Missing purpose, missing scope, unresolvable citation, unknown rubric version →
  reject. Never degrade to a permissive default.

---

## 3. The two supplies

### 3.1 Data products — 23 in the estate

A governed, contracted, owned dataset published for consumption. Authored as a manifest
(`manifests/products/DP-*.yaml`) and seeded into the canonical model.

| What a product carries | As-built total |
|---|---|
| Columns with classification and sensitivity | 420 |
| Quality rules | 120 |
| Upstream sources | 83 |
| Business entities | 92 |
| Contract guarantees (freshness, availability, completeness, accuracy) | 92 |
| Endpoints (SQL, REST, MCP, stream, share) | 59 |
| Certified KPIs | 112 |

Each product declares a grain, history depth, a **non-empty** `known_limitations` (I7), a tier
(tier1–3) that weights it in estate scoring, an archetype, an industry and a domain. Sensitivity is
**derived** from its columns, never written (I5).

### 3.2 AI agents — 30 in the estate

A catalogued assistant with an owner, a coverage map, a scope and a value case.

| What an agent carries | As-built total |
|---|---|
| KPI coverage rows (which measure, at which grains and slices, how deep) | 113 |
| Tool bindings (with scope, row limit and cost class) | 98 |
| Product bindings (which product columns it may read — the scope half of I12) | 38 |
| Curated demo exchanges (five per agent minimum, I3) | 150 |

An `agent_version` is an **immutable bundle**: model, parameters, prompt hash, tool bindings,
coverage map, guardrails, budgets and the evaluation run that judged it. Prompts are
content-addressed in `prompt_artifact`; a version pins the hash, never the text.

### 3.3 KPI registry — 112 definitions

Exactly one authoritative definition per measure per tenant (I1), with business definition,
numerator and denominator expressions, supported grains and slices, inclusions and exclusions,
unit, direction, target, steward, source of record and a review cadence. Divergence detection runs
nightly: two agents giving different numbers for the same certified KPI is the failure the registry
exists to prevent.

---

## 4. Catalogue, search and discovery

- **Hybrid search:** pgvector semantic similarity fused with Postgres full-text lexical search by
  reciprocal rank fusion, over products, KPIs, agents and glossary terms. The fusion constants live
  in the `search` and `ranking` rubrics.
- **Faceting:** industry, domain, archetype, certification, autonomy, KPI and product. Each facet is
  counted with every other selection applied **but not its own**, so choosing an industry never
  collapses the industry list to one row.
- **Ranking:** the `ranking` rubric governs fusion weights, facet ordering and the featured band.
- **Detail pages** assemble contract, schema, quality, lineage, mesh, consumption, endpoints and
  value from the canonical model — nothing on a card is typed by hand.

---

## 5. Engines

| Engine | What it computes | Rubric | Writes |
|---|---|---|---|
| **Quality** | Composite score per product from rule results across six dimensions — completeness, accuracy, freshness, consistency, validity, uniqueness — with severity weights, archetype overrides and tier weights. Five bands from Exemplary (≥90) to Not Fit for Consumption. Two hard blockers cap the composite: a failed critical rule at 39, an unprotected classified column at 49 | `quality` | `quality_score_snapshot` (append-only, cites its rubric version — I2) |
| **Mesh — data** | Edges between products computed from shared upstream sources, shared columns and semantic similarity, each with confidence and rationale (I6) | `mesh` | `mesh_edge_data` |
| **Mesh — agents** | Edges between agents computed from shared KPIs and shared products, plus divergence detection | `mesh` | `mesh_edge_agent` |
| **Demand** | Scores a new-supply request and assesses it against **coverage**, not just wording: already_served, enhance_agent, enhance_product, build_new or insufficient_evidence, each carrying its evidence | `demand` | `demand_item`, `demand_theme` |
| **Value** | Deflected hours, value, cost and ratio per asset per period, with named assumptions and sample sizes displayed beside every figure | `value` | `value_measurement` |
| **FinOps** | Cost attributed per asset per day across inference, retrieval, query, platform and stewardship | `finops` | `cost_allocation` |
| **Observability** | Watches signals, raises incidents with severity **computed from blast radius**, and notifies every affected consumer within the rubric's deadline | `observability` | `incident`, `incident_impact` |
| **Academy** | Six learning paths, 31 modules, certifications that pre-approve an access tier for an asset class | `academy` | `enrollment`, `assessment_result`, `certification` |

---

## 6. Governed rails (workflow)

| Rail | Path | Key rules |
|---|---|---|
| **Access request** | Requester states purpose and scope → policy resolves the approval path → approval steps with their own SLA clocks → decision → grant | Purpose is mandatory above Internal. A request may be **partially approved** (`request_item`). Every decision records the policy version in force. A grant is never wider than its scope rows |
| **Enhancement** | Raised against an existing asset, voted on, advanced or declined | **Declines are public and reasoned** |
| **New supply (demand)** | Intake form (kind, need, KPIs, questions) → duplicate check → coverage assessment → public demand board with voting | A vote requires a one-line use case; a vote without context is not counted. Five distinct requesting teams auto-escalates a theme |

Durable workflow state lives in `workflow_instance` / `workflow_event` — a Postgres-backed job
runner rather than Temporal (D-003), so an approval survives a process restart.

---

## 7. Security and entitlement model

- **Effective agent access = intersection(agent scope, user entitlement)** (I12), enforced
  server-side and covered by the security suite.
- **Row-level security on 71 of 76 tables**, forced, with the policy written against
  `current_setting('app.tenant_id')`. The application connects as `app_role` —
  `NOSUPERUSER NOBYPASSRLS` — because PostgreSQL exempts superusers from RLS entirely, including
  `FORCE ROW LEVEL SECURITY`. An application connecting as its own schema owner has isolation
  switched off and nothing reports it (02 §6).
- **Fail closed**: missing purpose, missing scope, unresolvable citation or unknown rubric version
  rejects the request.
- **Append-only** history: `quality_score_snapshot`, `audit_event`, `publication_snapshot`,
  `workflow_event` and `entitlement_grant` (the last *stamped in place* — a grant is closed by
  writing `revoked_at` beside it, policed by a trigger).
- **7-year retention** on `audit_event`.

---

## 8. Surfaces

### 8.1 API — 73 endpoints under `/api/v1`

| Group | Endpoints | Notable |
|---|---|---|
| Catalogue | `/products`, `/products/{id}` + schema, contract, quality, lineage, mesh, endpoints, consumption, value | Detail is assembled, never authored |
| Agents | `/agents`, `/agents/{id}` + coverage, demo, evaluation, release, `POST /ask`, `POST /feedback`, `POST /rollback` | `/ask` is the live answer path |
| Search | `/discover` | Hybrid, faceted |
| KPIs | `/kpis`, `/kpis/{id}` | Version history endpoint reads `kpi_definition_version` — **[GAP]**, nothing writes it |
| Requests | access (+ evaluate, submit, decide), enhancement (+ advance), backlog, entitlements, `audit.ndjson` | The audit export is the evidence trail |
| Demand | `GET/POST /demand`, `/demand/check`, `/demand/assess`, `/demand/{id}/vote` | Assessment against coverage |
| Mesh | `/mesh/data`, `/mesh/agents`, `/mesh/sources`, `/mesh/divergence`, `/mesh/data/blast-radius` | |
| Quality & observability | `/quality/estate`, `/observability`, `/observability/banners`, `/observability/scan`, incident context and resolve | |
| Landing | `/landing/hero`, `/counters`, `/featured`, `/industries`, `/proof`, `/theatre` | Feeds the motion layer |
| Academy | paths, modules, enrolments, assessments, `/academy/contextual`, `/academy/me` | Contextual module is scoped to the asset class |
| Admin | rubrics (+ publish version), flags, taxonomies, tenancy, connectors | Configuration only; never records |
| Platform | `/health`, `/events/stream` | |

OpenAPI 3.1 is **generated from source** into `generated/openapi/openapi.json`, with a TypeScript
client beside it.

### 8.2 Portal — 18 routes

`/` · `/discover` · `/data-products` · `/data-products/[id]` · `/agents` · `/agents/[id]` ·
`/agents/[id]/demo` · `/mesh/data` · `/mesh/agents` · `/observability` · `/demand` · `/requests` ·
`/requests/new/access` · `/requests/new/supply` · `/academy` · `/academy/[moduleId]` · `/admin` ·
`/admin/rubrics/[code]`

The portal is an **ordinary client of the API** with no privileged path (`API_BASE_URL`).

### 8.3 MCP

One MCP server definition generated per data product from its manifest, into `generated/mcp/`.

---

## 9. The front page

Ten bands driven by the `landing` rubric, with a motion budget enforced in CI (I14): CLS = 0 and
ambient motion holding ≥58 fps throttled. The living product ribbon, the agent constellation, the
live answer theatre, counters and an activity ticker all read real estate data — the counters band
returns **null rather than zero** when a count is not known, because "Browse all 0 data products" is
a claim about the size of the estate made from a failed fetch.

---

## 10. Non-functional requirements

| Area | Requirement |
|---|---|
| **Accessibility** | Keyboard navigable, labelled, visible focus, WCAG AA; `tests/a11y` in the pipeline |
| **Internationalisation** | Every style written in logical properties; `lint:logical-properties` fails the build on any physical direction property, so serving right-to-left is one environment variable (`PORTAL_LOCALE`) |
| **Performance** | Lighthouse and a motion frame-rate trace are CI gates; `test:perf` |
| **Load** | Quarterly load gate reporting what it measured — at 200 concurrent sessions it reports refusals and why, and names the estate size it ran against |
| **Chaos** | Four scenarios, quarterly; a scenario that passes for the wrong reason says so |
| **Observability** | OpenTelemetry traces, metrics and logs |
| **Residency** | `tenant.residency_regions` is carried per tenant; all storage and inference in the client's region |
| **Retention** | `audit_event` 7 years; snapshots and workflow events for the life of the engagement |
