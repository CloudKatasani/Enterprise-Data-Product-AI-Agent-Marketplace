# Enterprise Data Product & AI Agent Marketplace

A marketplace where **data products** and the **AI agents that run on them** are catalogued,
governed, requested, observed and demonstrated as one supply chain.

A business user can browse domain data products and agents in one catalog, see each asset's
quality score, freshness, owner, adoption and attached agents before clicking anything, watch
an agent answer curated questions live with citations, request access through governed rails,
explore the two meshes, and see a quantified value case for every asset.

Build specification: [`BUILD.md`](./BUILD.md). Where this README and `BUILD.md` disagree,
`BUILD.md` wins.

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
| `npm run verify` | lint + typecheck + unit + contract + golden + publish gate + a11y |
| `npm run test:e2e` | signature journey: search → demo → request → approve → provision → query |
| `npm run test:perf` | landing budgets and motion frame-rate trace |
| `npm run test:kill` | connector write-attempt kill test (needs sandbox credentials) |

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
- **Append-only.** Quality snapshots, publication snapshots, audit events and grant history
  revoke `UPDATE` and `DELETE`.
- **Fail closed.** Missing purpose, missing scope, unresolvable citation or unknown rubric
  version rejects the request.

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
