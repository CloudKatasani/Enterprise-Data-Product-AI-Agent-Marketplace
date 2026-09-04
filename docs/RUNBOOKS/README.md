# Runbooks

One file per condition that can page someone. A feature is not done until it has a runbook
entry if it can page (Definition of Done, BUILD.md section 22).

## Required shape

```
# RB-<AREA>-<NNN> — <symptom as the pager states it>
Severity        how severity is computed for this condition
Owner           the rota, not a person
Detection       the signal that fires, and where it is defined
First response  the three commands to run in the first five minutes
Diagnosis       the decision tree
Mitigation      the reversible action
Resolution      the durable fix
Consumer comms  what affected consumers are told, and by whom
Post-incident   what gets linked to the asset's quality history
```

## Index

| Runbook | Condition | Milestone |
|---|---|---|
| `RB-QUAL-001.md` | Product quality composite drops a band | M5 |
| `RB-AGENT-001.md` | Demo exchange marked `stale` by the nightly validator | M6 |
| `RB-GRND-001.md` | Groundedness failures spike (424 rate) | M7 |
| `RB-PROV-001.md` | Provisioning failed after an approved access request | M8 |
| `RB-MESH-001.md` | Nightly mesh recompute did not complete | M9 |
| `RB-FRESH-001.md` | Freshness guarantee breached on a Tier-1 product | M10 |
| `RB-ENT-001.md` | Entitlement register drifts from platform grants | M10 |
