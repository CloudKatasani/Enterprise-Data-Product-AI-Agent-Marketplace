# 09 — Build plan and acceptance

What each milestone delivered, how the system is tested, what "done" means per invariant, and what
is genuinely unresolved.

---

## 1. Team shape

| Role | Owns | Share |
|---|---|---|
| **AI / application engineer** | API, engines, agent runtime, publish gate, portal | ~55% |
| **Data engineer** | Canonical model, generators, manifests, seeders, harvest, demo tier, reconciliation | ~30% |
| **Cloud / platform engineer** (part-time) | Network, identity, Postgres + pgvector, Redis, containers, jobs, observability | ~15% |

Both engineers need the fourteen invariants ([01 §2](01-functional-spec.md)) before writing
anything. In a system like this, most defects are invariant violations that look like features.

---

## 2. Milestones, as executed

M0–M12 are complete in this repository. Durations are an estimate for rebuilding from scratch with
the team above; halve them when starting from this code.

| # | Milestone | What it delivers | Est. |
|---|---|---|---|
| **M0** | Scaffold | Repo, pinned stack, Compose, CI skeleton, the four lint rules that keep the rest honest | 3 d |
| **M1** | Canonical model, rubrics, manifests | The DSL, 76 tables, RLS, taxonomies, rubrics as data, manifest schemas and the validator | 2 w |
| **M2** | Generators | `gen` → ddl, sql, mcp, openapi, types, agent cards; byte-identical regeneration (I9) | 1 w |
| **M3** | Snowflake connector | Session, queries, harvest passes, **and the kill test** (I8) | 1 w |
| **M4** | Catalog, search, product detail | Hybrid search with RRF, facets counted correctly, detail assembled from the model | 2 w |
| **M5** | Quality engine | Six dimensions, severity weights, archetype overrides, tier weights, bands, hard blockers, append-only snapshots (I2) | 1.5 w |
| **M6** | Agent registry, publish gate, demo runner | Immutable bundles, eight blocking checks, real answers on demo-tier data | 2 w |
| **M7** | Demo console and grounding | Live answers with citations (I11), refusals that name what does cover the question | 1.5 w |
| **M8** | Workflow rails | Access, enhancement and demand; durable instances; partial approval; public reasoned declines | 2 w |
| **M9** | Meshes | Data and agent meshes with confidence and rationale (I6); divergence detection | 1.5 w |
| **M10** | Observability, value, FinOps | Signals, incidents with computed severity, consumer notification inside the deadline, cost attribution, value measurement | 2 w |
| **M11** | Landing page and motion | Ten bands, CLS 0, ≥58 fps throttled (I14) | 1.5 w |
| **M12** | Academy, admin, hardening | Six paths, 31 modules, certifications that pre-approve a tier; admin that configures and never records; RLS finding and fix; load and chaos gates; RTL as a lint | 2 w |

**Total ≈ 20 weeks** from scratch. The ordering that matters: **M1 and M2 before everything**. The
generated model and the generators are the spine; every engine is a client of them.

---

## 3. Work breakdown for the data engineer

1. **Canonical model and generators** (M1–M2) — the DSL, and the CI check that regeneration is
   byte-identical.
2. **Taxonomies and the KPI register** (M1) — start the client interviews in week one; the register
   is the long-lead content item and the highest-value artefact in the system.
3. **Product and agent manifests** (M4–M6) — 23 products and 30 agents took most of the estate work
   here; a client's first ten are the pilot.
4. **Database roles and the RLS assertion** (M1, revisited M12) — two logins, `NOSUPERUSER
   NOBYPASSRLS`, and the cross-tenant test that proves isolation is on.
5. **Demo tier and sandbox platform** (M3, M6) — calibrated *against* the measures ([04 §4.1](04-data-loading.md)).
6. **Harvest** (M3, M10) — metadata, lineage, usage, cost, quality passes; the kill test at
   commissioning.
7. **Reconciliation as a scheduled job** (M10) — the queries in [04 §8](04-data-loading.md), zero
   rows expected, alerting on non-zero.
8. **Freeze the DDL baseline** before the first client deployment ([03 §6](03-data-model.md)) — after
   which `gen:ddl` emits deltas and forward-only is enforced.

---

## 4. Test strategy

Ten suites, all in one CI pipeline, in this order:

```
lint → typecheck → gen-diff → unit → contract → golden → publish_gate
     → security → a11y → build → e2e → perf
```

| Suite | Covers |
|---|---|
| **lint** (9 checks) | Manifest validation, no-magic-numbers (I10), no-brand-strings (I13), animatable props, logical properties (RTL), migration shape, generated headers, ruff, portal ESLint |
| **gen-diff** | I9 — regeneration produces no diff |
| **unit** (21 files) | Canonical model shape, rubric resolution, planners, scoring, mesh maths, workflow policy, assessment |
| **contract** | API against the generated OpenAPI |
| **golden** | The 150 curated exchanges against recorded answers |
| **publish_gate** | The eight blocking checks, including I3, I4, I7 |
| **security** | Cross-tenant isolation (RLS actually on), entitlement intersection (I12), fails-closed behaviour |
| **kill** | I8 — the connector cannot write |
| **a11y** | Keyboard, labels, focus, contrast |
| **e2e** | The signature journey: browse → demo → request → approve → grant |
| **perf** | Lighthouse + motion frame-rate trace (I14) |
| **load / chaos** | Quarterly; both report **what they measured**, not a tick |

Definition of done for any change: `npm run verify` passes, and you have said plainly what works,
what is stubbed and **what you could not verify**.

---

## 5. Acceptance criteria

Demonstrate the invariants rather than asserting them.

| # | Demonstration | Passes when |
|---|---|---|
| I1 | Author a second active definition of an existing KPI name | The partial unique index refuses it |
| I2 | Insert a quality snapshot with no rubric version | Refused by NOT NULL; the write-path test proves the engine never tries |
| I3 | Remove a demo exchange from a published agent and re-run the gate | The gate turns red on that line and names it |
| I4 | Point a coverage row at a non-existent KPI | FK refuses |
| I5 | Set `sensitivity_tier` directly on a product | The trigger discards it and re-derives from the columns |
| I6 | Insert a mesh edge with no rationale | Refused; a low-confidence edge is reported, not drawn |
| I7 | Set `known_limitations` to "none" | CHECK refuses |
| I8 | Point the connector at a sandbox and attempt a write | The kill test fails the build if it succeeds |
| I9 | Edit a file under `generated/` and run CI | `gen-diff` fails |
| I10 | Put a threshold in `services/` | `lint:no-magic-numbers` fails |
| I11 | Make an agent state a number with no citation | The answer errors rather than shipping |
| I12 | Ask as a persona entitled to fewer columns than the agent's scope | The narrower set answers; the entitlement suite covers ≥3 personas |
| I13 | Put a brand string or hex colour in source | `lint:no-brand-strings` fails |
| I14 | Run the perf suite on the landing page | CLS 0 and ≥58 fps throttled |

Three deployment acceptance items beyond the invariants: a restore from backup inside RTO; the
reconciliation queries returning zero rows in production; and a **named user from the client's IdP**
signing in and landing with the right roles — which today needs the work in [02 §5](02-architecture.md).

---

## 6. Risk register and open items

### 6.1 Gaps to close before a client deployment

| # | Gap | Impact | Fix |
|---|---|---|---|
| **G1** | **OIDC not wired** — the portal runs as `PORTAL_DEV_SUBJECT` | No real authentication. Blocks every client-facing environment | Identity-aware proxy (fast) or Auth.js + JWT validation (proper) — 02 §5 |
| **G2** | **`entitlement_drift` is never written** — the nightly register-vs-platform reconciliation does not exist | The product claims to detect grants the platform no longer honours, and cannot | Build the drift job; it has a table and an incident path waiting for it |
| **G3** | **`decision` is never written** | The reason and outcome are on the request and in the audit log, but the **policy version each decision was taken under** is recorded nowhere | Write a decision row per approval step |
| **G4** | **`publication_snapshot` is never written** | Rollback replays `agent_version`, which works; the promised audit artefact does not exist | Write the snapshot at publish, or drop the table |
| **G5** | **`duplicate_match`, `purpose_binding`, `revocation`, `kpi_definition_version` are never written** | Duplicate findings cannot be revisited; per-query purpose is not logged; revocation reasons are untyped; the KPI history endpoint returns empty | Implement or drop — a migrated table nothing writes is a promise the schema makes on the product's behalf |
| **G6** | **DDL is a baseline, not a migration history** | The first schema change after release has nothing to delta against | Freeze the baseline before the first client deployment (03 §6) |
| **G7** | **`docs/ADR/` holds only a template**; one runbook exists | Decisions live in `DECISIONS.md` (42 of them) but architecture decisions have no ADR trail | Backfill the ADRs that matter — the RLS finding, the Temporal substitution, the canonical-model DSL |

### 6.2 Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **pgvector unavailable** on the client's managed Postgres | Verify in week one (05–07 §3). Without it, hybrid search is lexical-only and the semantic mesh cannot be computed |
| R2 | **Identity work underestimated** — it always involves teams outside the project | Start in week one; use a proxy for the pilot |
| R3 | **Connection exhaustion** from three services plus eight jobs | Budget connections explicitly, stagger schedules, pool via PgBouncer / RDS Proxy |
| R4 | **Model availability or approval in-region** | `analytic` runtime makes the deployment complete without a model endpoint |
| R5 | **Manifest content quality.** A generic KPI register makes the whole marketplace feel generic | Book the steward interviews before manifest authoring starts |
| R6 | **Demo tier calibrated beside its measures rather than against them** — the 139% availability and 157% loss ratio class of defect | Check every measure reads near its target after generation (04 §4.1) |
| R7 | **Superuser collapse** — a deployment pointing both DB URLs at the owner | The security suite asserts it; keep that test in the pipeline and alert if it is skipped |
| R8 | **Scope creep into pipeline execution or catalogue-of-record** | Hold the boundary in 01 §1 |
| R9 | **Governance theatre** — approvals granted without reading, agents published because the gate is green | Report time-to-decision and acceptance rates; the academy exists for exactly this |

### 6.3 Open questions for the client

| # | Question | Default if unanswered |
|---|---|---|
| OQ-1 | Which IdP, and OIDC or proxy? | Platform proxy for the pilot |
| OQ-2 | Is there a warehouse this may read, and over what private path? | Local sandbox platform; demo-tier estate only |
| OQ-3 | Is model inference permitted in-region? | `AGENT_RUNTIME=analytic` |
| OQ-4 | One tenant or several, and what residency per tenant? | One tenant, single-region |
| OQ-5 | Retention for `audit_event` beyond seven years? | Seven years, never deleted |
| OQ-6 | Does the demo tier and answer theatre belong in production? | No — staging only |
| OQ-7 | Who owns the KPI register, and what review cadence? | The stewards named in the manifests; cadence from `review_months` |

---

## 7. Handover checklist

- [ ] Runbooks: deploy, roll back, restore, rotate secrets, add a tenant, author a manifest, publish
      a rubric version, respond to an incident
- [ ] IaC in the client's repository, applied from their pipeline
- [ ] Reconciliation queries scheduled, alerting on non-zero
- [ ] Backup **restore** rehearsed and timed
- [ ] The kill test run against the client's own sandbox account
- [ ] The AI governance pack ([08 §9](08-agents-llm.md)) delivered to the review board
- [ ] Every seeded demo party removed from client environments
- [ ] `PORTAL_DEV_SUBJECT` removed and real authentication in place
- [ ] The DDL baseline frozen and delta migrations enabled
- [ ] The seven unwritten tables (§6.1) either implemented or dropped, with the decision recorded in
      `docs/DECISIONS.md`
