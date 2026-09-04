# Decisions

Every judgement call made while executing `BUILD.md` is recorded here, newest last.
Where `BUILD.md` was ambiguous, the narrower reading was implemented and the question
recorded as a `SPEC-QUESTION`.

## Format

```
### D-NNN — <title>  (milestone, date)
**Context** what forced the decision
**Decision** what was done
**Consequence** what this costs or buys
```

---

### D-001 — Repository root is the marketplace root (M0, 2026-09-04)
**Context** BUILD.md section 4 shows the tree rooted at `marketplace/`. The repository is
itself the marketplace, so an extra `marketplace/` directory would add a level with no
information in it.
**Decision** The directory names under section 4 (`manifests/`, `generated/`, `services/`,
`connectors/`, `portal/`, `seed/`, `tests/`, `docs/`, `scripts/`) sit at the repository root.
**Consequence** Paths in this repo drop one segment against the paths written in BUILD.md.
Everything else about the layout is unchanged.

### D-002 — Python 3.11 floor rather than 3.12 (M0, 2026-09-04)
**Context** BUILD.md section 3 pins Python 3.12. The toolchain available in the build and CI
environment is Python 3.11.
**Decision** `requires-python = ">=3.11"`. No 3.12-only syntax is used; the codebase runs
unchanged on 3.12.
**Consequence** None functionally. CI runs 3.12 where the runner provides it and 3.11 locally.

### D-003 — Postgres-backed job runner instead of Temporal (M0, 2026-09-04)
**Context** BUILD.md section 3 names Temporal for durable workflows with an explicit fallback:
"(fallback: Postgres-backed job runner)". Temporal needs a server this deployment does not
provision.
**Decision** The stated fallback is implemented: durable workflow state lives in Postgres
(`workflow_instance` / `workflow_event`), and the worker advances instances transactionally so
an approval survives a restart. The engine is behind an interface a Temporal adapter can
implement later.
**Consequence** Approvals are durable and restart-safe, which is what section 14 requires.
Long-timer semantics are polled rather than pushed.

### D-004 — Numeric-literal whitelist is `{0, 1, -1}` plus subscripts (M0, 2026-09-04)
**Context** Rule 2 whitelists "0, 1, -1, array indices, HTTP status codes, CSS in tokens" but
does not say how HTTP status codes are recognised.
**Decision** Status codes live in exactly one module, `services/common/http_status.py`, which is
the sole file exempt from the rule. Everywhere else imports from it. `portal/styles/**` is
exempt because it is design tokens, not logic.
**Consequence** There is no inline suppression comment anywhere, so the rule cannot be argued
around; a threshold that needs to exist has to go into `manifests/rubrics/`.

### D-005 — The canonical model definition is a Python DSL, not a manifest (M1, 2026-09-04)
**Context** BUILD.md section 9 feeds `gen:ddl` from "canonical model definition + manifests",
naming the two separately. The model needs typed structure (columns, checks, indexes,
tenant-scoping, append-only) that YAML would express verbosely and unsafely.
**Decision** The canonical model lives in `scripts/generators/canonical_model.py` using the DSL
in `scripts/generators/model.py`. It is generator input, not application source, so the
numeric-literal rule does not reach it.
**Consequence** `tenant_scoped` and `append_only` are declarations, so RLS and immutability
cannot be forgotten for a new table; `scripts/lint/migrations.py` re-checks the emitted SQL.

### D-006 — `generated_at` is a property of content, not of the run (M1, 2026-09-04)
**Context** M2.2 requires "no timestamps inside hashed content", while the gen-diff gate
requires `npm run gen` to leave generated files byte-identical when inputs have not changed.
A timestamp refreshed on every run satisfies neither.
**Decision** `manifest_hash` is computed over the generator's inputs only. The writer compares
the newly rendered body with the body already on disk and, when they match, leaves the file
and its existing `generated_at` untouched.
**Consequence** `generated_at` honestly records when this content was produced, and the gate
stays meaningful rather than noisy.

### D-007 — `derive_sensitivity` returns a tier code, not a rank number (M1, 2026-09-04)
**Context** BUILD.md 6.2 writes `derive_sensitivity` as `SELECT COALESCE(MAX(t.rank_order), 1)::TEXT`,
which yields `'3'`, while `data_product.sensitivity_tier` is consumed everywhere else as a
`sensitivity_tier.code` — `data_contract_version.max_sensitivity` even declares
`REFERENCES sensitivity_tier(code)`.
**Decision** The narrower reading that keeps the value usable: the function applies exactly the
`MAX(rank_order)` selection rule the specification writes, and returns that tier's `code`. A
`SPEC-QUESTION` comment sits on the function.
**Consequence** Sensitivity reads as `confidential`, not `3`, and joins to the tier table.

### D-008 — Rubric content that changes must bump its declared version (M1, 2026-09-04)
**Context** `rubric_version` is unique on `(rubric_id, semver)` and every score records the
version id it was computed under. Editing a weight without moving `version:` would make two
different rubrics answer to the same name.
**Decision** The seeder refuses the write, naming both content hashes and telling the author to
bump `version`. It does not synthesise a version or overwrite the existing one.
**Consequence** Rubric history stays replayable. The M1 acceptance flow is: change the weight,
bump the version, re-seed — which is also how the admin UI will version a rubric in M12.2.

### D-009 — `source_of_record` on a KPI is back-filled after products seed (M1, 2026-09-04)
**Context** `kpi_definition.source_of_record` references `data_product`, but the KPI register is
seeded in M1 and the product catalog in M4.
**Decision** The KPI seeder sets the reference when the product already exists and leaves it null
otherwise; `backfill_source_of_record` closes the loop and runs last in the seeder order. Both
are idempotent.
**Consequence** Seeding order is not load-bearing, and a KPI whose source product is genuinely
absent is visibly null rather than pointing at nothing.

### D-010 — Portal-only environment variables extend `.env.example` (M1, 2026-09-04)
**Context** The portal is an ordinary client of the API and needs to know where the API is;
`.env.example` in BUILD.md section 5 does not list it. The worker's poll cadence is likewise
operational tuning that must not be a literal in source (I10).
**Decision** `API_BASE_URL`, `PORTAL_BASE_URL` and `WORKER_POLL_SECONDS` are added to
`.env.example` and to the required set, so they are validated at boot like everything else.
**Consequence** The rule that the app refuses to boot on a missing variable still covers every
variable the app actually reads.

### D-011 — The OpenAPI document carries a fixed title, not the deployment's (M2, 2026-09-04)
**Context** The running API titles itself `<PRODUCT_NAME> API`, but the generated OpenAPI
document is a committed build artifact. Embedding the deployment name would make two machines
generate different bytes from the same code (I9) and would put a brand string into a committed
file (I13).
**Decision** The generator overwrites `info.title` with a fixed, deployment-independent name.
The running app still titles itself with `PRODUCT_NAME`.
**Consequence** Regeneration is stable across environments, and `/docs` still shows the
deployment's own name.

### D-012 — Source systems are a tenant-scoped taxonomy (M2, 2026-09-04)
**Context** BUILD.md section 6.1 lists `source_system` under Reference, but which upstream
systems feed a marketplace is a property of the deployment, not shared vocabulary like the
sensitivity ladder.
**Decision** `manifests/taxonomies/source_system.yaml` is authored as a taxonomy manifest and
seeded into the tenant-scoped `source_system` table, carrying platform, owning team and
criticality. The taxonomy schema requires those three fields for `SRC-` codes only.
**Consequence** Two tenants can name different upstream systems, and shared-source mesh edges
are computed within a tenant rather than across all of them.

### D-013 — `lint:generated` compares against what the generators reported writing (M2, 2026-09-04)
**Context** The rule re-runs generation into a scratch copy of `generated/` so unchanged files
keep their timestamps. Scanning that tree afterwards would count a hand-added file as
"generated", because the copy put it there.
**Decision** Each generator returns the paths it wrote; the rule compares that set against the
committed set. A file nothing generates, and a generated file that was not committed, are both
reported.
**Consequence** Adding, editing or deleting a file under `generated/` all fail the build, which
is what rule 3 asks for.

### D-014 — A stand-in platform, not a stand-in connector (M3, 2026-09-04)
**Context** M3 requires a real harvest and a kill test, but no Snowflake account is available to
this build. Mocking the connector would test the mock.
**Decision** `scripts/seeders/platform_sandbox.py` materialises the ACCOUNT_USAGE and
INFORMATION_SCHEMA *shapes* the connector reads, in a physically separate Postgres schema, and
fills them from the product manifests. `SandboxSession` rewrites only the namespaces; the
statements, the read-only guard, the result shapes and the harvest code are the ones that run
against a real account. Nothing in `connectors/` knows the sandbox exists.
**Consequence** A change to a harvest query is exercised rather than silently diverging, and the
kill test has a real platform to attack. `open_session()` picks the real account whenever
`SNOWFLAKE_PRIVATE_KEY` is configured.

### D-015 — The kill test proves two independent layers (M3, 2026-09-04)
**Context** A kill test that only checks an in-process guard is checking that we wrote an `if`.
**Decision** Every write attempt is asserted twice: refused by `assert_read_only` before it
reaches a driver, and refused by the platform when submitted straight to the driver through
`unguarded_execute`. The stand-in platform enforces read-only the way `MKT_READONLY` does.
**Consequence** I8 holds even against an account whose grants were misconfigured, and the claim
is worth making. `npm run test:kill` runs on every commit against the stand-in and on a
schedule against a real sandbox account.

### D-016 — Manifest and platform both write columns; disagreement is a finding (M3, 2026-09-04)
**Context** The product manifest declares columns and the harvest observes them. Both write
`data_product_column`.
**Decision** The manifest seeds what the product promises; the harvest upserts what the platform
holds. Sensitivity is written by neither — the I5 trigger derives it from whatever the columns
say, so a classification tag appearing on the platform raises the product's tier by itself.
**Consequence** The derived tier tracks reality rather than the document, which is the point of
deriving it. Recording explicit drift rows is M10 work, alongside entitlement reconciliation.

### D-017 — Harvest windows, confidences and the credit rate are a rubric (M3, 2026-09-04)
**Context** Lookback windows, the confidence attached to a declared versus an inferred lineage
edge, and the dollars-per-credit used to apportion cost are all numbers, and I10 forbids them
in source.
**Decision** `manifests/rubrics/harvest.yaml` (`platform_harvest`) holds them, and every harvest
pass takes the resolved rubric as an argument.
**Consequence** The difference between "the platform's dependency graph says so" (1.0) and
"queries touched both" (0.85) is reviewable without reading Python, which is what rule 4 is for.

### D-018 — A deterministic hashing embedder is the default (M4, 2026-09-04)
**Context** Hybrid search needs a semantic retriever. The marketplace ships no model, and a
hosted one makes results irreproducible: a ranking that changed because a model was retrained
cannot be debugged.
**Decision** `services/search/embedding.py` defines an `Embedder` interface and one
implementation that needs nothing — word unigrams, bigrams and character n-grams hashed into
the vector space with signed collisions. Its hyperparameters live in the `semantic_search`
rubric and its `model_id` is part of the embedding key, so a deployment can register its own
model and the old vectors stay distinguishable.
**Consequence** Search is reproducible and dependency-free. Absolute semantic quality is lower
than a trained model's; on this corpus a related pair scores roughly four times an unrelated
pair, which is enough for the retriever whose job is to feed RRF.

### D-019 — The exact-name guarantee is applied twice (M4, 2026-09-04)
**Context** M4's acceptance is that an exact name never loses to a semantic neighbour, and the
seed catalog is full of near neighbours that share vocabulary (churn and retention, sales and
inventory, outage and fault).
**Decision** `fusion.exact_name_boost` is added at fusion *and* again after the weighted rank,
because normalisation would otherwise dilute it back into the pack.
**Consequence** Six adversarial cases are pinned as tests. The boost is a rubric value, so the
guarantee can be tuned without touching the ranker.

### D-020 — Facet counts exclude their own selection (M4, 2026-09-04)
**Context** Counting a facet against the full filter set collapses it to the selected value, so
a consumer cannot change their mind without clearing everything.
**Decision** Each facet is counted with its own predicate removed and every other predicate
applied.
**Consequence** One extra query per facet on the listing page, in exchange for a rail a
consumer can actually navigate.

### D-021 — Display precision is a rubric value, applied server-side (M4, 2026-09-04)
**Context** Search explanations expose signal values. Formatting them in the portal would put a
numeric literal in portal source (I10), and how precisely a system reports a computed signal is
a policy rather than a presentation detail.
**Decision** `fusion.explanation_precision` lives in the ranking rubric and the API rounds
before serialising. The portal prints the number it is given.
**Consequence** One place decides how precise the system claims to be, next to the weights that
produced the number.

### D-022 — Generated Python constants are parsed, not imported (M4, 2026-09-04)
**Context** The embedding dimension must equal the `vector(n)` column type, so it is generated
from the canonical model. Importing it put `generated/types/` on `sys.path` and scattered
`__pycache__` through a directory that must stay byte-identical.
**Decision** The constant is read with a regex over the generated file, and `lint:generated`
ignores build caches.
**Consequence** No bytecode in `generated/`, and a missing or malformed constant fails loudly
with "run npm run gen".

### D-023 — The mesh render threshold is lowered, and the rubric says why (M9, 2026-09-04)
**Context** Section 13.3 states a render threshold of 0.25. Measured across this estate the
strength distribution has a natural gap between 0.087 and 0.100 and nothing above 0.188, because
`kpi_overlap` is structurally zero here: every certified KPI has exactly one source of record
(I1), so no two products can share one.
**Decision** `render_threshold` is 0.10 in `manifests/rubrics/mesh.yaml`, with the reasoning
recorded beside the value rather than in a commit message.
**Consequence** The mesh renders the edges that exist instead of an empty graph. An estate where
products genuinely share KPIs would raise it back, and the rubric is where that argument happens.

### D-024 — An owner can add context to an incident and can never suppress it (M10, 2026-09-04)
**Context** Every incident tool eventually grows a mute button, and the reason is always
reasonable at the time.
**Decision** There is no suppression path: not in the engine, not as an API parameter, not as a
prop on the banner. An owner adds context, which is shown alongside the fact and never in place
of it. Resolution requires a root cause, so "it went away" does not close an incident.
**Consequence** A noisy signal has to be fixed in the rubric where everyone can see the
threshold move, rather than silenced on one asset where nobody can.

### D-025 — Findings carry the unit their number is measured in (M10, 2026-09-04)
**Context** The health plane showed `0.0666` and `79` in one column. Both are true; neither is
legible, and no formatting rule in the portal could tell them apart.
**Decision** The unit belongs to the signal, so `UNIT_BY_SIGNAL` states it once and the payload
carries it. The portal renders a fraction as a percentage using `Intl.NumberFormat`, which takes
the fraction directly and therefore needs no conversion factor of its own.
**Consequence** A new detector without a unit fails a test rather than shipping a column of bare
decimals. The portal never holds a number that could drift from the server's.

### D-026 — The hero constellation settles on the server (M11, 2026-09-04)
**Context** 13.3 asks for a pre-warmed layout so the client paints a settled graph. The obvious
route is `d3-force` in the browser, warmed for 300 ticks before first paint.
**Decision** The simulation — link springs, many-body repulsion, collision, velocity decay — is
implemented in `services/landing/layout.py` and runs on the server. Its parameters are rubric
data, it is seeded from the identifiers, and it sorts its nodes, so the same estate always
settles into the same picture. `d3-force` and `d3-quadtree` were removed from the portal.
**Consequence** A screenshot in a deck is the graph the client opens, the hero and the mesh
explorer cannot disagree about the shape of the same estate, and the largest single item in the
motion budget is gone. Above 150 nodes a canvas renderer with quadtree hit-testing is still the
right answer, and the quadtree comes back with the renderer that needs it.

### D-027 — Orbit speed is returned as a seed, not a rate (M11, 2026-09-04)
**Context** Agent satellites orbit at 0.6–1.1 deg/sec, a range that lives in the motion tokens.
The server knows which agent orbits which products; the token layer knows how fast anything may
move.
**Decision** The API returns `speed_seed` in [0, 1). The client maps it onto the token range.
**Consequence** The server never states a number the token layer would then have to agree with,
and changing the range is a token edit rather than a coordinated change on both sides.

### D-028 — A KPI value is rounded once, and the claim is what the reader sees (M11, 2026-09-04)
**Context** Currency values were quantised to six decimal places, so an answer read "$58,557,319.919999"
while its recorded claim held the same figure. The grounding check compared the two and passed,
which is the wrong thing to be reassured by.
**Decision** Precision per unit lives in the runtime rubric, and `_quantise` applies it before
the claim is recorded. The number in the sentence, the number in the table and the number
grounding checks are one number.
**Consequence** An agent is held to the figure a reader was actually shown. Re-capturing the
golden answers changed 70 files and no behaviour, which is what a display-only change should
look like.

### D-029 — The landing page fetches on the server and never renders a skeleton (M11, 2026-09-04)
**Context** 13.6 asks for CLS 0.00 and 13.2 forbids skeletons on the marketing page. Those two
rule out the usual pattern of streaming each band in as it arrives.
**Decision** Every band is fetched in one `Promise.all` on the server, every band declares its
box height as a token, and a band whose data is unavailable collapses rather than reserving
space for something that is not coming. The answer theatre renders its *completed* answer
server-side and the choreography starts from that frame.
**Consequence** The page is coherent without JavaScript, identical under reduced motion, and
nothing moves after paint. A slow API makes the page slower rather than jumpier, which is the
trade the budget asks for.

### D-030 — The application connects as a role RLS applies to (M12.5, 2026-09-04)
**Context** The security suite asserted that a connection bound to another tenant sees nothing.
It saw everything. PostgreSQL exempts superusers from row-level security entirely — `FORCE ROW
LEVEL SECURITY` included — and the application was connecting as the owner of its own schema,
so every policy in the generated DDL was decoration and nothing anywhere reported it.
**Decision** Two URLs. `DATABASE_URL` owns the schema and is used by migrations; the new
`APP_DATABASE_URL` is the application's own login, created by `npm run migrate` as a member of
`app_role` with `NOSUPERUSER NOBYPASSRLS` re-asserted on every run. The `tenant` table moved off
the shared-vocabulary list at the same time: its rows are per-tenant and disclosing one tenant's
name, deployment mode and residency to another is a leak.
**Consequence** Isolation is real and a test asserts the connection cannot bypass it. Two
consequences fell out immediately and are the reason this was worth finding: the demo-tier and
platform-sandbox schemas needed explicit grants, and `entitlement_grant` turned out to revoke
`UPDATE` at the table level while its trigger existed to police updates — which meant a grant
could never be revoked at all.

### D-031 — Append-only comes in two shapes (M12.5, 2026-09-04)
**Context** Rule 6 says snapshot, publication, audit and grant history are append-only, and the
generator emitted one `REVOKE UPDATE, DELETE` for all four. But a grant is *ended* by stamping
`revoked_at` on it rather than by writing a new row, and a trigger already existed to freeze its
terms while permitting exactly that.
**Decision** `stamped_in_place` on the canonical model. Those tables revoke `DELETE` only, and
the trigger — required by the migration lint rather than assumed — is what makes `UPDATE` safe.
**Consequence** The strongest constraint that can be expressed is still expressed, and the one
operation the table exists to support works. The lint now checks the trigger rather than the
grant, which is the thing that actually holds.

### D-032 — A certification is worth an access tier (M12.1, 2026-09-04)
**Context** An academy nobody finishes is a cost. Badges do not make people finish.
**Decision** A certification pre-approves an access tier for its asset class: a certified
consumer's request for a product inside that tier takes the automatic path. Which certificate
covers what lives in the academy rubric, the policy reads it through a `certification_pre_approved`
fact, and a feature flag can switch the whole benefit off in a hurry.
**Consequence** Finishing the path is worth something concrete, and how much it is worth is a
versioned, arguable number rather than a line in an evaluator. Certification widens nothing on
its own — it changes which path a request takes, and the grant that follows is still scoped,
purposed and expiring.

### D-033 — A version is a bundle, so rollback is one action (M12.3, 2026-09-04)
**Context** "Restore the previous bundle in one action" is easy to claim and hard to mean.
Restoring a prompt without its bindings restores a configuration that never existed.
**Decision** An agent version *is* the bundle — prompt, model, parameters, guardrails, coverage
map, product and tool bindings, budgets, evaluation run — and versions are immutable, so rolling
back is pointing at the previous one. One transaction, nothing reconstructed.
**Consequence** The rollback drill releases a real candidate through the real gate and rolls it
back, comparing every field of the restored bundle to the one that was live. It runs in CI and
leaves the estate exactly as it found it.

### D-034 — Right-to-left is a lint, not a project (M12.4, 2026-09-04)
**Context** Mirroring an interface after it is built is a rewrite. Mirroring one written in
logical properties is an attribute on `<html>`.
**Decision** `lint:logical-properties` fails the build on any physical direction property in
`portal/` — CSS and the Tailwind classes that compile to the same thing — with no suppression
comment. Direction comes from `PORTAL_LOCALE`.
**Consequence** Serving the portal in Arabic is one environment variable, verified by rendering
it. The 35% string-expansion pass is asserted in the a11y suite against the reserved box heights
the CLS budget depends on, so the two requirements are reconciled in the tokens rather than
discovered in a screenshot.

### D-035 — One connection per session, and the load test says so (M12.5, 2026-09-04)
**Context** Section 20 asks the load gate to hold at 500 concurrent sessions. At 200 the
harness ran 129 and the rest were refused a database connection: every session opens its own,
there is no pool, and PostgreSQL's `max_connections` is the ceiling. Catalog search also went
over its 400ms p95 under that concurrency, on an estate of fifteen products.
**Decision** Recorded rather than papered over. The load harness reports how many sessions
actually ran, names the cause, and prints the size of the estate it measured — a green run
against fifteen products proves the code path and nothing about the scale the budget was
written for, and it says that in those words. A connection pool is the fix and is not attempted
here: pooling changes how the tenant setting is bound to a connection, which is the mechanism
row-level security depends on, and that is a change to make deliberately rather than at the end
of a milestone.
**Consequence** The quarterly gate produces a number and a named blocker instead of a tick.
Nobody reading the report can mistake it for a 500-session result.

### D-036 — A grant is keyed on its request, not on (principal, asset) (M12.5, 2026-09-04)
**Context** The end-to-end journey test revokes the access it was granted, so it can run twice.
The second run approved a request and provisioned nothing: the grant id was
`GRT-<party>-<asset>`, the revoked row from the first run was already there, and the insert's
`ON CONFLICT DO NOTHING` silently did nothing while the workflow reported success.
**Decision** The grant id is `GRT-<request_id>`. A grant is the record of one approval, so
keying it on the approval is both correct and unique by construction.
**Consequence** Revocation ends an access rather than blacklisting a person, and re-granting
works. This is the worst shape a permission bug can take — both sides believe access was
given — and it was invisible until a test tried the same journey twice.

### D-037 — Nine more agents, and the six defects covering them exposed (2026-09-04)
**Context** The agent catalogue had fourteen agents against fifteen data products, and 55 of the
75 certified KPIs were answerable by nobody. Coverage was uneven in the two ways the browse
experience shows: three industries had one agent or none in a whole business domain, and the
`finance` domain existed in the taxonomy with nothing in it.
**Decision** Nine agents, chosen so that each covers only KPIs no existing agent covers —
AG-ENG-001, AG-BNK-003, AG-HLT-003, AG-INS-003, AG-RTL-003, AG-TCH-002, AG-TEL-003, AG-TRN-002,
AG-UTL-002. Every industry and every business domain in the taxonomy now has at least one agent,
and 74 of 75 KPIs are covered. Manufacturing keeps its single agent: all five of its KPIs are
already answered by AG-MFG-001, and a second one would be the duplication the agent mesh exists
to flag.
**Consequence** Writing an agent against a KPI is the first thing that reads that KPI, and six
defects surfaced that way — each fixed here rather than routed around:

* `KPI-LOADFACT-067` multiplied a bare `period_hours` outside an aggregate, so any query over it
  failed. Its numerator and denominator now compute the ratio its own business definition
  states: average demand over peak demand.
* `KPI-RETEN-002` counted subscribers with any non-churn row, which on daily data is everyone.
  Retention read 100% while churn on the same denominator read 2.3%. It is now the complement it
  claims to be: active at period start, less churned.
* A measure that cannot be pooled across periods was restricted to the latest complete period
  *at the grain the question asked for* — so a question with no time word pooled a year of
  monthly snapshots and carried a note saying it had not. The restriction is now never wider
  than a month.
* A cohort split on a column the KPI's own expression uses is the definition restated: save rate
  was "100% where the save offer was accepted against 0% where it was not". Such a column is no
  longer eligible, and the question becomes the slice comparison it can answer.
* `SELECT measure AS measure, (...) AS measure` returned the wrong one of the two, silently:
  DP-HLT-001 has a slice column named `measure`. The grouped dimension now has a reserved alias.
* A distribution fell back to the first readable column when none matched the KPI expression,
  which under a narrowed entitlement was a date — `percentile_cont` over a date, and a crash.
  The column must now be both the measured one and numeric, else the question degrades to a
  slice comparison.

The same first reading recalibrated one generated column. DP-INS-001's `earned_premium` was
drawn from a range picked beside the loss range rather than against it, putting the book's loss
ratio at 157% — a number no insurer survives, and one nothing read until an agent covered
`KPI-LOSSRATIO-026`. The range now yields about 70%.

**Consequence** `KPI-CONVRATE-048` is left uncovered, and deliberately. Its source of record,
DP-RTL-001, is one row per transaction line: a visit that did not convert has no row, `visit_id`
and `transaction_id` are one-to-one across all 23,400 rows, and conversion computes to 100.00%
everywhere. The measure needs a visit-grain product, which is a supply gap to raise rather than
a number to publish.
