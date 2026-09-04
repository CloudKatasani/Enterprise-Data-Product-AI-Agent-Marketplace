-- AUTO-GENERATED FROM manifests/products/DP-BNK-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-BNK-002 — Transaction Surveillance & Financial Crime Signal
-- contract 2.9.0, max sensitivity restricted, contains PII: false
-- grain: one row per alert per disposition event
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_BNK_002.V_DP_BNK_002 AS
SELECT
  alert_id,
  event_timestamp,
  typology,
  rule_id,
  business_line,
  region,
  investigator_team,
  disposition,
  sar_filed,
  investigation_days,
  age_days,
  alert_score,
  customer_risk_rating,
  transaction_count,
  transaction_value
FROM DP_BNK_002.T_DP_BNK_002;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_BNK_002.T_DP_BNK_002 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-BNK-002 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_BNK_002.SV_DP_BNK_002 AS
SELECT
  event_timestamp,
  typology,
  rule_id,
  business_line,
  investigator_team,
  disposition,
  sar_filed,
  customer_risk_rating,
  count(distinct alert_id) AS kpi_alertvol_021,  -- Alert Volume (KPI-ALERTVOL-021), unit count
  (count(*) filter (where disposition = 'no_further_action')) / NULLIF(count(*) filter (where disposition is not null), 0) * 100 AS kpi_fprate_022,  -- False Positive Rate (KPI-FPRATE-022), unit percent
  (count(*) filter (where sar_filed)) / NULLIF(count(*) filter (where disposition is not null), 0) * 100 AS kpi_sarconv_023,  -- SAR Conversion Rate (KPI-SARCONV-023), unit percent
  percentile_cont(0.5) within group (order by investigation_days) AS kpi_invcycle_024,  -- Investigation Cycle Time (KPI-INVCYCLE-024), unit days
  percentile_cont(0.9) within group (order by age_days) filter (where disposition is null) AS kpi_backlog_025  -- Alert Backlog Age (KPI-BACKLOG-025), unit days
FROM DP_BNK_002.V_DP_BNK_002
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8;

-- Quality rule attachments for DP-BNK-002.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-BNK-002-01: completeness / not_null (severity critical)
ALTER TABLE DP_BNK_002.T_DP_BNK_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (alert_id);

-- QR-BNK-002-02: freshness / stream_lag_under (severity critical)
ALTER TABLE DP_BNK_002.T_DP_BNK_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_STREAM_LAG_UNDER ON (*);

-- QR-BNK-002-03: validity / in_reference_set (severity critical)
ALTER TABLE DP_BNK_002.T_DP_BNK_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (typology);

-- QR-BNK-002-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_BNK_002.T_DP_BNK_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (alert_id, event_timestamp);

-- QR-BNK-002-05: consistency / implies_disposition_escalated (severity critical)
ALTER TABLE DP_BNK_002.T_DP_BNK_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IMPLIES_DISPOSITION_ESCALATED ON (sar_filed);
