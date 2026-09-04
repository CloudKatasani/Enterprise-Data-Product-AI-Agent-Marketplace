-- AUTO-GENERATED FROM manifests/products/DP-TEL-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-TEL-001 — Subscriber Churn & Retention 360
-- contract 3.2.0, max sensitivity confidential, contains PII: true
-- grain: one row per subscriber per day
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_TEL_001.V_DP_TEL_001 AS
SELECT
  subscriber_id,  -- masking policy MASK_PII attached below
  account_id,  -- masking policy MASK_PII attached below
  activity_date,
  segment,
  region,
  plan_type,
  tenure_days,
  tenure_band,
  channel,
  active_at_period_start,
  churn_flag,
  churn_reason_code,
  save_offer_made,
  save_offer_accepted,
  churn_propensity_score,
  propensity_decile,
  ltv,
  contract_end_date,
  care_contacts_30d,
  network_incidents_30d
FROM DP_TEL_001.T_DP_TEL_001;

-- Column masking, applied in the platform.
ALTER TABLE DP_TEL_001.T_DP_TEL_001 MODIFY COLUMN subscriber_id SET MASKING POLICY GOVERNANCE.MASK_PII;
ALTER TABLE DP_TEL_001.T_DP_TEL_001 MODIFY COLUMN account_id SET MASKING POLICY GOVERNANCE.MASK_PII;

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_TEL_001.T_DP_TEL_001 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-TEL-001 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_TEL_001.SV_DP_TEL_001 AS
SELECT
  activity_date,
  segment,
  plan_type,
  tenure_band,
  channel,
  active_at_period_start,
  churn_flag,
  churn_reason_code,
  save_offer_made,
  save_offer_accepted,
  contract_end_date,
  (count(distinct subscriber_id) filter (where churn_flag)) / NULLIF(count(distinct subscriber_id) filter (where active_at_period_start), 0) * 100 AS kpi_churn_001,  -- Churn Rate (KPI-CHURN-001), unit percent
  (count(distinct subscriber_id) filter (where not churn_flag)) / NULLIF(count(distinct subscriber_id) filter (where active_at_period_start), 0) * 100 AS kpi_reten_002,  -- Retention Rate (KPI-RETEN-002), unit percent
  (count(distinct subscriber_id) filter (where save_offer_accepted)) / NULLIF(count(distinct subscriber_id) filter (where save_offer_made), 0) * 100 AS kpi_save_003,  -- Save Rate (KPI-SAVE-003), unit percent
  avg(tenure_days) AS kpi_tenure_004,  -- Average Subscriber Tenure (KPI-TENURE-004), unit days
  ntile(10) over (order by churn_propensity_score desc) AS kpi_prop_005  -- Churn Propensity Decile (KPI-PROP-005), unit index
FROM DP_TEL_001.V_DP_TEL_001
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11;

-- Quality rule attachments for DP-TEL-001.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-TEL-001-01: completeness / not_null (severity critical)
ALTER TABLE DP_TEL_001.T_DP_TEL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (subscriber_id);

-- QR-TEL-001-02: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_TEL_001.T_DP_TEL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (subscriber_id, activity_date);

-- QR-TEL-001-03: freshness / partition_completion_by (severity high)
ALTER TABLE DP_TEL_001.T_DP_TEL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-TEL-001-04: validity / in_reference_set (severity high)
ALTER TABLE DP_TEL_001.T_DP_TEL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (segment);

-- QR-TEL-001-05: accuracy / reconcile_to_source (severity medium)
ALTER TABLE DP_TEL_001.T_DP_TEL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_RECONCILE_TO_SOURCE ON (ltv);

-- QR-TEL-001-06: consistency / agrees_with_billing_status (severity high)
ALTER TABLE DP_TEL_001.T_DP_TEL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_AGREES_WITH_BILLING_STATUS ON (churn_flag);
