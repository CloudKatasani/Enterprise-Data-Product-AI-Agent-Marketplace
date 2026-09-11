# Marketplace Build Specification

**Enterprise Data Product & AI Agent Marketplace — as-built specification and enterprise deployment
reference.**

This is what you hand an AI engineer and a data engineer who have to build this system on a client
network and run it on AWS, Azure or GCP. It specifies what the application is, how it is
constructed, every table in its canonical model, what data goes into each one, three cloud
reference architectures, the agent runtime, and a build plan with acceptance criteria.

---

## How this relates to `BUILD.md`

[`BUILD.md`](../../BUILD.md) is the **build input** — the brief that was executed, milestone by
milestone, to produce this repository. It says what to build. Where it and any other document
disagree, **BUILD.md still wins**; nothing here overrides it.

These documents are the **as-built specification and the deployment reference**, and they exist to
answer questions BUILD.md does not:

| Question | Answered by |
|---|---|
| What was actually built, and where does it differ from the brief? | 01, and the **[GAP]** markers throughout |
| How do the pieces fit together at runtime, on a client's network? | 02 |
| What does the physical model look like — all 76 tables, RLS, append-only, indexes? | 03 |
| What data goes in each table, who is allowed to write it, and how do I prove it landed? | **04** |
| How do I run this on AWS / Azure / GCP with their managed services? | 05, 06, 07 |
| What does the agent runtime do, and what does a client's AI review board need? | 08 |
| How would a team rebuild this, and what does "done" mean? | 09 |

---

## Who this is for

| Reader | Read in this order | What you own |
|---|---|---|
| **AI / application engineer** | 01 → 02 → 08 → 09 | API, engines, agent runtime, portal |
| **Data engineer** | 03 → 04 → 05/06/07 → 09 | Canonical model, migrations, manifests, seeding, harvest, demo tier, reconciliation |
| **Cloud / platform engineer** | 02 → 05/06/07 | Network, identity, Postgres, Redis, containers, secrets, observability |
| **Architect / reviewer** | 01 §2 → 02 §6 → 09 §5 | The fourteen invariants and how they are enforced |
| **Client stakeholder** | 01 §1, 09 §2 | What this is and what it takes to stand it up |

---

## Contents

| # | Document | What it specifies |
|---|---|---|
| 01 | [Functional specification](01-functional-spec.md) | Mission, scope boundary, the fourteen invariants, the two supplies, catalogue and search, quality engine, agent registry and publish gate, demo console, workflow rails, the two meshes, observability, value and FinOps, academy, admin, the 73-endpoint API and 18 portal routes |
| 02 | [Solution architecture](02-architecture.md) | Stack, process topology, the generator pipeline, request path, client-network deployment, identity, the RLS security model, multi-tenancy, NFRs, CI/CD, observability |
| 03 | [Canonical data model](03-data-model.md) | 76 tables in 13 groups, how the DDL is generated, the RLS and append-only patterns, invariants in the schema, indexes, growth model, migrations, retention |
| 04 | [Data loading specification](04-data-loading.md) | **Per-table specification for all 76 tables** — phase, legitimate writer, source, volume, rules, validation — plus the seeder order, the demo tier, the harvest, the engine runs, and reconciliation queries |
| 05 | [AWS reference architecture](05-cloud-aws.md) | ECS Fargate / Aurora PostgreSQL + pgvector / ElastiCache / Bedrock / PrivateLink to Snowflake |
| 06 | [Azure reference architecture](06-cloud-azure.md) | Container Apps / PostgreSQL Flexible Server / Azure Cache / Entra ID / AI Foundry |
| 07 | [GCP reference architecture](07-cloud-gcp.md) | Cloud Run / Cloud SQL / Memorystore / IAP / Vertex AI |
| 08 | [Agent runtime and LLM engineering](08-agents-llm.md) | Runtime adapters, the planner, grounding and citations, the eight publish-gate checks, evaluation harness, guardrails and budgets, per-cloud model access, the AI governance pack |
| 09 | [Build plan and acceptance](09-build-plan.md) | M0–M12 with what each delivered, test strategy across ten suites, acceptance per invariant, risk register, open items |

---

## The one-paragraph product

An enterprise marketplace where **data products** and the **AI agents that run on them** are
catalogued, governed, requested, observed and demonstrated as one supply chain. A business user
browses both in one catalogue, sees quality, freshness, owner, adoption and attached agents before
clicking anything, watches an agent answer curated questions live with citations, and then requests
access, an enhancement or entirely new supply through governed rails. Two meshes show what shares
upstream sources and what answers the same measures. Every asset carries a quantified value case.

**Out of scope, by design:** building pipelines, being an identity provider, being the catalogue of
record, and authoring agents. The marketplace catalogues and governs agents authored elsewhere.

---

## Status and honesty markers

The repository is a complete M0–M12 build with a real 23-product, 30-agent, 112-KPI estate, and it
has gaps a client deployment must close. Throughout these documents:

| Marker | Meaning |
|---|---|
| **[BUILT]** | Exists and is exercised by tests in this repository. The named file is the reference. |
| **[GAP]** | Declared, specified or expected but not implemented. Must be built or consciously dropped before a client deployment. |
| **[VERIFY]** | Depends on a cloud service, region, licence or tenant setting that must be confirmed in the client's own account. Never assume from this document. |

The largest **[GAP]** items, stated once here so nobody finds them in week six:

- **Seven canonical tables are migrated but never written by any code path** — `decision`,
  `purpose_binding`, `revocation`, `entitlement_drift`, `duplicate_match`, `publication_snapshot`
  and `kpi_definition_version`. Three matter for claims the product makes: entitlement drift is the
  nightly reconciliation BUILD.md §15.6 describes, `publication_snapshot` is the bundle a rollback
  is supposed to replay, and `decision` is the typed approval record — the reason and outcome are
  captured on the request and in the audit log instead, so the trail exists but not in the shape
  the model declares. See [03 §9](03-data-model.md) and [04](04-data-loading.md).
- **OIDC sign-in is not wired.** The portal calls the API as the seeded party named by
  `PORTAL_DEV_SUBJECT`. Every role check downstream is therefore exercised but not authenticated
  (02 §5).
- **The Snowflake path is written against a documented account but the reference deployment runs
  the local sandbox platform.** The kill test and the harvest both run; what has not been proven is
  a live client account (03 §7, 05–07 §6).
- **`docs/ADR/` contains a template and no decisions**, and `docs/RUNBOOKS/` contains one runbook.
  `docs/DECISIONS.md` carries 42 judgement calls (D-001…D-041) and is the real record.
- **Cloud costs, service availability and model availability in 05–08 are design-time estimates.**
  Price and confirm them in the client's own account and region.
