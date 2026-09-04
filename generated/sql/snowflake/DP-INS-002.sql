-- AUTO-GENERATED FROM manifests/products/DP-INS-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-INS-002 — Policy & Underwriting Portfolio
-- contract 2.6.0, max sensitivity confidential, contains PII: false
-- grain: one row per policy per month
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_INS_002.V_DP_INS_002 AS
SELECT
  policy_id,
  quote_id,
  as_of_month,
  coverage_line,
  segment,
  region,
  county,
  channel,
  peril,
  written_premium,
  charged_premium,
  technical_premium,
  total_insured_value,
  in_top_accumulation_zone,
  up_for_renewal,
  renewed,
  bound,
  rate_change_pct
FROM DP_INS_002.T_DP_INS_002;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_INS_002.T_DP_INS_002 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-INS-002 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_INS_002.SV_DP_INS_002 AS
SELECT
  as_of_month,
  coverage_line,
  segment,
  channel,
  peril,
  in_top_accumulation_zone,
  up_for_renewal,
  renewed,
  bound,
  sum(written_premium) AS kpi_writtenprem_031,  -- Gross Written Premium (KPI-WRITTENPREM-031), unit currency
  (count(distinct policy_id) filter (where renewed)) / NULLIF(count(distinct policy_id) filter (where up_for_renewal), 0) * 100 AS kpi_polreten_032,  -- Policy Retention (KPI-POLRETEN-032), unit percent
  (count(distinct quote_id) filter (where bound)) / NULLIF(count(distinct quote_id), 0) * 100 AS kpi_qtb_033,  -- Quote-to-Bind Rate (KPI-QTB-033), unit percent
  (sum(charged_premium)) / NULLIF(sum(technical_premium), 0) AS kpi_rateadq_034,  -- Rate Adequacy (KPI-RATEADQ-034), unit ratio
  (sum(total_insured_value) filter (where in_top_accumulation_zone)) / NULLIF(sum(total_insured_value), 0) * 100 AS kpi_expconc_035  -- Exposure Concentration (KPI-EXPCONC-035), unit percent
FROM DP_INS_002.V_DP_INS_002
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9;

-- Quality rule attachments for DP-INS-002.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-INS-002-01: completeness / not_null (severity critical)
ALTER TABLE DP_INS_002.T_DP_INS_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (policy_id);

-- QR-INS-002-02: freshness / partition_completion_by (severity high)
ALTER TABLE DP_INS_002.T_DP_INS_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-INS-002-03: validity / in_reference_set (severity high)
ALTER TABLE DP_INS_002.T_DP_INS_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (peril);

-- QR-INS-002-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_INS_002.T_DP_INS_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (policy_id, as_of_month, peril);

-- QR-INS-002-05: accuracy / reconcile_to_general_ledger (severity critical)
ALTER TABLE DP_INS_002.T_DP_INS_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_RECONCILE_TO_GENERAL_LEDGER ON (written_premium);
