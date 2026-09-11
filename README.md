# Enterprise Data Product & AI Agent Marketplace

A marketplace where **data products** and the **AI agents that run on them** are catalogued,
governed, requested, observed and demonstrated as one supply chain.

A business user can browse domain data products and agents in one catalog, see each asset's
quality score, freshness, owner, adoption and attached agents before clicking anything, watch
an agent answer curated questions live with citations, request access through governed rails,
explore the two meshes, and see a quantified value case for every asset.

Build specification: [`BUILD.md`](./BUILD.md). Where this README and `BUILD.md` disagree,
`BUILD.md` wins.

As-built specification and deployment reference:
[`docs/build-spec/`](./docs/build-spec/README.md) — what to hand an AI engineer and a data engineer
who have to build this on a client network and run it on AWS, Azure or GCP. Functional
specification, solution architecture, the 76-table canonical model, a per-table data loading
specification, three cloud reference architectures, the agent runtime, and a build plan with
acceptance criteria. It does not override `BUILD.md`; it answers what happens after it.

## Quick start

```bash
cp .env.example .env
npm install
npm run bootstrap        # python dependencies
npm run dev              # data plane + generate + migrate + seed + api + worker + portal
```

`npm run dev` produces a fully browsable marketplace with the seed catalog and a working demo
console with no manual setup steps beyond copying `.env`.

## Commands

| Command | Does |
|---|---|
| `npm run gen` | `manifests/` → `generated/` (ddl, sql, mcp, openapi, types, agent cards) |
| `npm run migrate` | apply `generated/ddl` migrations, forward-only |
| `npm run seed` | taxonomies, rubrics, KPIs, products, agents, synthetic demo data |
| `npm run verify` | lint + typecheck + unit + contract + golden + publish gate + security + a11y + perf |
| `npm run test:e2e` | signature journey: search → demo → request → approve → provision → query |
| `npm run test:perf` | landing budgets and motion frame-rate trace |
| `npm run test:security` | entitlement escalation, purpose bypass, injection, cross-tenant |
| `npm run test:kill` | connector write-attempt kill test (needs sandbox credentials) |
| `npm run observe` | signals, incidents, cost attribution and the value snapshot |
| `npm run rollback:drill` | rehearse an agent release and roll it back, in place |
| `npm run test:load` | the four latency budgets, at whatever concurrency you ask for |
| `npm run test:chaos` | data plane down, credential expiry, model outage, mid-approval restart |

## Rules that are enforced, not documented

- **No numeric threshold in application source.** Weights, bands, cutoffs and SLA targets live
  in `manifests/rubrics/` and are resolved by `rubric_version_id` at read time
  (`npm run lint:no-magic-numbers`).
- **No brand string or raw hex colour outside token files.** The display name is the
  `PRODUCT_NAME` token (`npm run lint:no-brand-strings`).
- **Only `transform` and `opacity` may be animated** (`npm run lint:animatable-props`).
- **Generated files are never hand-edited.** `npm run gen && git diff --exit-code generated/`.
- **Every inference carries `confidence` and `rationale`;** below 0.80 confidence a record is
  not displayed until a reviewer is recorded against it.
- **Append-only.** Quality snapshots, publication snapshots and audit events revoke `UPDATE`
  and `DELETE`. Grant history revokes `DELETE` and is policed by a trigger instead, because a
  grant is *ended* by stamping `revoked_at` on it rather than by writing a new row.
- **Row-level security applies to the application.** It connects as `APP_DATABASE_URL`, a
  member of `app_role` that is neither a superuser nor `BYPASSRLS` — PostgreSQL exempts both
  from RLS entirely, including `FORCE ROW LEVEL SECURITY`, and reports nothing when it does.
  `npm run migrate` creates that role; the security suite asserts the connection cannot bypass.
- **No physical direction property in the portal** (`npm run lint:logical-properties`), so
  serving the interface right-to-left is `PORTAL_LOCALE` and nothing else.
- **Fail closed.** Missing purpose, missing scope, unresolvable citation or unknown rubric
  version rejects the request.

## Two databases URLs, on purpose

`DATABASE_URL` owns the schema and is used by migrations. `APP_DATABASE_URL` is what the
application connects as. They are different roles because row-level security does not apply to
the owner of the tables it protects, and an estate that ran the application as its schema owner
would have tenant isolation switched off with every policy still in the DDL, still looking
correct, and nothing failing.

## Layout

```
manifests/    source of truth: products, agents, KPIs, rubrics, taxonomies
generated/    DO NOT EDIT — header-stamped output of npm run gen
services/     FastAPI services: catalog, search, mesh, quality, workflow, ...
connectors/   read-only platform connectors with published permission manifests
portal/       Next.js app
seed/         synthetic demo-tier generators, golden answers, evaluation cases
tests/        unit contract golden publish_gate kill security e2e perf a11y
docs/         DECISIONS.md, ADRs, runbooks
scripts/      generators, migrations, seeders, lint rules
```

## Contributing

Every pull request updates [`docs/DECISIONS.md`](./docs/DECISIONS.md) with any judgement call
made, and satisfies the Definition of Done in `BUILD.md` section 22.
