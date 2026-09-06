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

### D-038 — Conversion rate gets a product that can hold a visit that bought nothing (2026-09-04)
**Context** D-037 left `KPI-CONVRATE-048` uncovered. Its source of record, DP-RTL-001, is one row
per transaction line: a visit that did not convert has no row at all, `visit_id` and
`transaction_id` were one-to-one across every row, and the measure computed to 100.00% in every
slice. The denominator the definition asks for did not exist in the data.
**Decision** DP-RTL-003, "Visit & Conversion Funnel" — one row per visit, converted or not, with
`transaction_id` nullable. That null is the whole product: it is what a transaction-grain table
cannot express. `KPI-CONVRATE-048` is repointed at it and removed from DP-RTL-001's certified
list, and two measures that only exist at this grain are certified alongside it —
`KPI-ABANDON-076` (basket abandonment, against started baskets rather than all visits, so
browsing without intent does not read as abandonment) and `KPI-VISITDWELL-077` (median visit
dwell). AG-RTL-003 binds the new product and covers all three, so the estate gains a product and
no uncovered-KPI debt; it is renamed Trading Performance Analyst, because margin and conversion
are one conversation for the person asking.
**Consequence** Conversion reads 19.5% against the KPI's own 24% target, and the three planted
patterns are visible: store converts at 25.2% against 10.9% digital, express format trails the
other two at 14.6%, and electronics holds visitors nearly twice as long as any other category
while converting worst. The last of those is the finding the funnel exists to produce and the one
a transaction-grain table can never produce, because the visits that make it are exactly the rows
it does not have.

Two runtime defects surfaced, both from the new product's shape:

* The non-poolable test compared `count(DISTINCT key)` against `count(*)`, so a column that is
  null four fifths of the time read as a key recurring across periods, and a measure that pools
  perfectly well was restricted to one month. It now compares against `count(key)`, and both
  sides ignore nulls. This also lifted a false restriction on `KPI-RESTORE-064`, whose
  `outage_id` is unique wherever it is present.
* A question naming a slice by its unqualified noun — "which categories hold visitors longest",
  against a column named `entry_category` — matched no slice and silently answered by whichever
  one the coverage map happened to list first. The slice matcher now falls back to the noun the
  column name ends in, after exact matches, so a product carrying both `category` and
  `entry_category` still resolves the bare word to the bare column.

### D-039 — Six more data products, one per gap in the industry and domain grid (2026-09-04)
**Context** Sixteen products covered nine industries unevenly: three industries had a single
product, and the `finance` domain — which two agents already answer in — had no product of its
own at all. The catalogue's two browse facets are industry and business domain, and both had
holes a consumer would hit on their first filter.
**Decision** One product per gap, each with its own grain, its own upstream sources and its own
certified measures, so none of them is a reslice of a product that already exists:

| Product | Industry | Domain | Grain |
|---|---|---|---|
| DP-BNK-003 Lending & Credit Portfolio | banking | finance | loan account per month |
| DP-TCH-002 Service Reliability & Incident | technology | operations | service per hour |
| DP-TRN-002 Freight Cost & Margin | transportation | finance | carrier invoice line |
| DP-MFG-002 Supplier Quality & Inbound Materials | manufacturing | supply_chain | receipt line |
| DP-HLT-003 Workforce & Care Capacity | healthcare | operations | unit per shift |
| DP-INS-003 Policyholder & Distribution 360 | insurance | customer | customer per month |

Every industry now holds at least two products and every business domain at least one. The
thirty measures they certify are covered by six agents written against them, so the estate gains
products without gaining uncovered KPIs: 107 of 107 are answerable.

**Consequence** Four defects surfaced, each from a shape the estate had not carried before:

* A ranking always ordered descending, so a question asking which lane was thinnest was answered
  with the fattest, and one asking where provision coverage was weakest named the strongest
  region. The order now follows the question — and, for a quality word rather than a magnitude
  word, the KPI's own declared direction, because the worst delinquency rate is the highest and
  the worst margin is the lowest. Eight existing exchanges were answering the wrong end.
* A slice was matched on its exact name or its trailing noun only, so "which vintages" against a
  column named `vintage_band` matched nothing and silently answered by whichever slice the
  coverage map listed first. It now falls back to any word of the column name, after exact
  matches. Three more existing exchanges were answering a dimension nobody asked about.
* Grounding read the `30` in "30+ Delinquency Rate" as an uncited figure. A measure's name is a
  label, so its digits are subtracted from what the prose is held to — computed from the names
  rather than cut out of the text, because cutting `SAIDI` out of `KPI-SAIDI-061` leaves `-061`
  behind and invents a number that was never written.
* The boundary matcher's action verbs had no word for the actions these domains ask for. "Award
  the lane to a different carrier" and "roll back the release" were planned as questions rather
  than refused as instructions. The vocabulary now carries them.

Three source-system codes introduced with DP-RTL-003 were in no vocabulary. They are registered,
and `validate:manifests` now fails on an upstream source outside the `source_system` taxonomy —
the mesh draws its source-overlap edges from these codes, so one that is in no vocabulary is an
edge between two products that nothing can name.

Two generator calibrations were made against the measures rather than beside them: lending
delinquency was set to land near its own 2.4% target instead of at 10%, and freight margin was
reading 26% because fuel surcharge was billed as revenue but never counted as cost.

### D-040 — The agent catalogue gets the rail the product catalogue already had (2026-09-05)
**Context** The agents page read six filter query parameters — industry, domain, autonomy,
certification, KPI, product — and rendered no control for any of them. The filters worked; only
somebody willing to hand-write a query string could find them. `AGENT_FACETS` had been declared
in `services/catalog/facets.py` since M4 and was referenced by nothing.
**Decision** `/agents` returns facets the way `/products` does, counted by the same function
under the same rule: each facet is counted with every *other* selection applied but not its own,
so choosing an industry never collapses the industry list to the one row the consumer picked.
The page grows the same `240px` rail, with the chosen filters shown as removable chips above it
because a filter you cannot see is a filter you cannot undo.
**Consequence** Filtering to an industry is one click and every state is a URL. The rail is
links rather than controls, so it works without JavaScript, and the counts tell a consumer what
they will get before they click.

Manufacturing was the one industry the new rail would have landed a consumer on thinly: three
agents everywhere else, two there, and no reliability view of a plant at all. DP-MFG-003
(Equipment Reliability & Maintenance, one row per maintenance work order) and AG-MFG-003 fill
that — mean time between failures, repair time, preventive adherence, unplanned share and
spares availability, none of them measures any existing agent covers. Every industry now holds
at least three agents and 112 of 112 KPIs are answerable.

Two things the new product exposed:

* Spares availability was drawn independently of whether spares were needed, so the rate came
  out at 139% — more calls served than calls made. Availability is only defined where a part was
  actually called for.
* `spares_available` was not in the cohort vocabulary, so "do repairs take longer when the spare
  was not on the shelf" was answered as a ranking by asset class rather than as the comparison
  it asked for. It is a legitimate cohort — the KPI's own expression does not reference it — and
  the split it produces is the finding: 394 minutes against 140.

### D-041 — A demand is assessed against coverage before it is scored on similarity (2026-09-06)
**Context** New-supply intake had one gate: `/demand/check`, which asks whether a request *reads
like* a published product. That is a text question, and it is the right one for the moment
somebody starts typing — but it is a weak answer to the question the board actually needs, which
is whether anything in the estate can already **answer** what is being asked. It also compared
every demand against data products, including a demand for an agent, so "we already have one of
these" was being judged against the wrong sort of asset. The intake page carried no form: the
whole flow was reachable only by hand-writing a query string.
**Decision** `services/workflow/assessment.py` answers the coverage question from three facts the
estate already holds — a KPI's `source_of_record`, `agent_kpi_coverage`, and
`agent_product_binding` — and returns one of `already_served`, `enhance_agent`,
`enhance_product`, `build_new` or `insufficient_evidence`, with the evidence it was made from.
`/demand/assess` runs it and the similarity check together, so the page cannot show a
recommendation made from one estate beside duplicates from another. The intake grew a real form:
kind, the need, the KPIs the answer would carry, and the questions it would have to place.
`check_duplicates` takes a `kind` and compares an agent demand against agents, defaulting to
products so the submission path is unchanged. Every threshold, including how many candidates are
worth reading, is in `manifests/rubrics/demand.yaml` under `supply_assessment` at 1.4.0.
**Consequence** A demand naming no KPI gets `insufficient_evidence` rather than a verdict the
evidence cannot support — the request for KPIs is not paperwork, it is the only thing that makes
the check possible.

Three things this exposed, all of them errors the first version made confidently:

* A set of measures answered across *two* agents was recommended as an enhancement to whichever
  single agent covered the most — which meant advising someone to add a measure another agent
  already answers, the exact divergence the rationale warns against. Answered is answered,
  however it is spread; that is an entitlement and a composition problem, not missing supply.
* A KPI that is not in the register was reported as a coverage gap. It is not one. There is no
  definition to answer against yet, and an agent asked to answer it would have to invent one, so
  it is named as a definition gap instead.
* A question was counted as placeable whenever the demand named *any* answered KPI. Almost every
  demand does, so the unplaced-question signal disappeared exactly when it was worth having. A
  question is placed by naming a measure something answers, or not at all.
