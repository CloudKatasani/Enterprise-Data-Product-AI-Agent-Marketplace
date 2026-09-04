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
