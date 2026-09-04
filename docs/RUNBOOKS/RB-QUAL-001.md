# RB-QUAL-001 — Product quality composite drops a band

**Severity**  Computed from the product's tier and downstream consumer count, not chosen.
A Tier-1 product with attached agents dropping to `at_risk` or `unfit` is a Sev2; the same
drop on a Tier-3 product with no consumers is a Sev4.

**Owner**  The data product's owner rota, escalating to the domain steward.

**Detection**  The scoring job writes an immutable `quality_score_snapshot` per product per
run. A run whose `band` differs from the previous snapshot's band raises this alert. The
band boundaries are rubric data (`manifests/rubrics/quality.yaml`), so a band change caused
by a *rubric* change is distinguishable from one caused by the data — check
`rubric_version_id` on both snapshots before anything else.

## First response

```
npm run score -- <PRODUCT_ID>                 # recompute, see the current composite
curl -s "$API/products/<PRODUCT_ID>/quality"  # current, history and contributing results
psql "$DATABASE_URL" -c "SELECT rubric_version_id, composite, band, blocker_applied,
                                computed_at
                         FROM quality_score_snapshot
                         WHERE product_id = '<PRODUCT_ID>'
                         ORDER BY computed_at DESC LIMIT 5;"
```

## Diagnosis

1. **Did the rubric move?** If `rubric_version_id` differs between the two snapshots, the
   estate was re-scored under a new rubric. This is not a data incident. Confirm the change
   was intended (`git log manifests/rubrics/quality.yaml`) and communicate the re-score.
2. **Is a hard blocker applied?** `blocker_applied` naming `critical_rule_failed` means a
   critical rule failed; `classified_column_unprotected` means a classified column has no
   masking policy on the platform. Both are governance failures, not scoring noise. Go to
   the relevant section below.
3. **Otherwise it is the evidence.** The `contributing_results` in the quality tab show
   every rule with its threshold and observation. Find the dimension that moved:

```
psql "$DATABASE_URL" -c "SELECT q.dimension, q.rule_id, q.threshold_pct, r.observed_pct,
                                r.observed_value, r.passed, r.evaluated_at
                         FROM quality_result r JOIN quality_rule q ON q.rule_id = r.rule_id
                         WHERE r.product_id = '<PRODUCT_ID>'
                         ORDER BY r.evaluated_at DESC LIMIT 40;"
```

### A critical rule failed

The composite is capped at the rubric's value regardless of everything else. Treat this as a
contract breach: the product is not fit for the consumption its contract promises. Raise an
incident against the product (which banners every affected listing and every attached agent),
and work the upstream pipeline that produced the failing rows.

### A classified column is unprotected

A column carrying `pii`, `phi`, `pci` or `credential` has no masking policy attached on the
platform. This is a live disclosure risk, not a scoring problem. Escalate to the steward and
the privacy contact immediately, apply the policy on the platform, and re-harvest:

```
npm run harvest -- metadata
npm run score -- <PRODUCT_ID>
```

## Mitigation

Reversible: none of the scoring path mutates the product. If the band drop is causing
consumer alarm while the underlying issue is understood and being fixed, add owner context to
the incident — owners can add context but **cannot suppress consumer notification**.

## Resolution

Fix the upstream cause, let the next harvest record passing results, and let the scoring job
write a new snapshot. Never edit a snapshot: the table refuses `UPDATE` and `DELETE`, and the
history is what makes the drop explainable afterwards.

## Consumer communications

Consumers of the product and of every attached agent are notified by the incident lifecycle,
not by the owner directly. The notification names the guarantee breached and the expected
recovery, and links to this product's quality history.

## Post-incident

The root cause is published on the incident and linked permanently to the asset's quality
history. If the cause was a rule that measured the wrong thing, change the rule in the
product manifest — not the threshold in the snapshot.
