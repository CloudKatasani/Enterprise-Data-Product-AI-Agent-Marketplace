-- AUTO-GENERATED FROM manifests/products/DP-TCH-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-TCH-001 — Product Usage & Feature Adoption
-- contract 4.1.0, max sensitivity confidential, contains PII: false
-- grain: one row per account per feature per day
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_TCH_001.V_DP_TCH_001 AS
SELECT
  account_id,
  feature,
  activity_date,
  plan_tier,
  segment,
  region,
  acquisition_channel,
  feature_entitled,
  feature_used,
  daily_active_account,
  monthly_active_account,
  onboarded,
  activated,
  days_to_first_value,
  starting_recurring_revenue,
  ending_recurring_revenue,
  renewal_date
FROM DP_TCH_001.T_DP_TCH_001;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_TCH_001.T_DP_TCH_001 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-TCH-001 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_TCH_001.SV_DP_TCH_001 AS
SELECT
  feature,
  activity_date,
  plan_tier,
  segment,
  acquisition_channel,
  feature_entitled,
  feature_used,
  onboarded,
  activated,
  renewal_date,
  (count(distinct daily_active_account)) / NULLIF(count(distinct monthly_active_account), 0) AS kpi_daumau_011,  -- DAU to MAU Ratio (KPI-DAUMAU-011), unit ratio
  (count(distinct account_id) filter (where feature_used)) / NULLIF(count(distinct account_id) filter (where feature_entitled), 0) * 100 AS kpi_featadp_012,  -- Feature Adoption Rate (KPI-FEATADP-012), unit percent
  (count(distinct account_id) filter (where activated)) / NULLIF(count(distinct account_id) filter (where onboarded), 0) * 100 AS kpi_activ_013,  -- Activation Rate (KPI-ACTIV-013), unit percent
  percentile_cont(0.5) within group (order by days_to_first_value) AS kpi_ttv_014,  -- Time to First Value (KPI-TTV-014), unit days
  (sum(ending_recurring_revenue)) / NULLIF(sum(starting_recurring_revenue), 0) * 100 AS kpi_nrr_015  -- Net Revenue Retention (KPI-NRR-015), unit percent
FROM DP_TCH_001.V_DP_TCH_001
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10;

-- Quality rule attachments for DP-TCH-001.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-TCH-001-01: completeness / not_null (severity critical)
ALTER TABLE DP_TCH_001.T_DP_TCH_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (account_id);

-- QR-TCH-001-02: freshness / partition_completion_by (severity high)
ALTER TABLE DP_TCH_001.T_DP_TCH_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-TCH-001-03: validity / in_reference_set (severity high)
ALTER TABLE DP_TCH_001.T_DP_TCH_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (plan_tier);

-- QR-TCH-001-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_TCH_001.T_DP_TCH_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (account_id, feature, activity_date);

-- QR-TCH-001-05: consistency / implies_entitled_or_trial (severity medium)
ALTER TABLE DP_TCH_001.T_DP_TCH_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IMPLIES_ENTITLED_OR_TRIAL ON (feature_used);
