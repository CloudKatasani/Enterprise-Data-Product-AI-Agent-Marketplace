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
