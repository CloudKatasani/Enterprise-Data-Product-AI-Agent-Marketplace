-- AUTO-GENERATED FROM manifests/products/DP-INS-003.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:35:53+00:00

-- Governed consumption view for DP-INS-003 — Policyholder & Distribution 360
-- contract 1.0.0, max sensitivity restricted, contains PII: true
-- grain: one row per customer per month
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_INS_003.V_DP_INS_003 AS
SELECT
  customer_id,  -- MASK_PII unavailable on this platform; grant by column instead
  household_id,  -- MASK_PII unavailable on this platform; grant by column instead
  as_of_month,
  segment,
  region,
  distribution_channel,
  agency_id,
  tenure_band,
  policies_held,
  coverage_lines_held,
  total_written_premium,
  service_contacts_90d,
  complaints_90d,
  nps_response,
  digital_registered,
  autopay_enrolled,
  cross_sell_eligible,
  cross_sell_accepted,
  multi_line,
  lapsed
FROM DP_INS_003.T_DP_INS_003;

-- Semantic view for DP-INS-003 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_INS_003.SV_DP_INS_003 AS
SELECT
  as_of_month,
  segment,
  distribution_channel,
  tenure_band,
  multi_line,
  lapsed,
  (sum(policies_held)) / NULLIF(count(distinct customer_id), 0) AS kpi_polpercust_103,  -- Policies per Customer (KPI-POLPERCUST-103), unit count
  (count(distinct customer_id) filter (where multi_line)) / NULLIF(count(distinct customer_id), 0) * 100 AS kpi_multiline_104,  -- Multi-Line Penetration (KPI-MULTILINE-104), unit percent
  (count(distinct customer_id) filter (where digital_registered)) / NULLIF(count(distinct customer_id), 0) * 100 AS kpi_digital_105,  -- Digital Enrolment Rate (KPI-DIGITAL-105), unit percent
  (count(distinct customer_id) filter (where cross_sell_accepted)) / NULLIF(count(distinct customer_id) filter (where cross_sell_eligible), 0) * 100 AS kpi_xsell_106,  -- Cross-Sell Acceptance (KPI-XSELL-106), unit percent
  (count(distinct customer_id) filter (where complaints_90d > 0) * 1000) / NULLIF(count(distinct customer_id), 0) AS kpi_complaint_107  -- Complaint Rate per Thousand (KPI-COMPLAINT-107), unit rate
FROM DP_INS_003.V_DP_INS_003
GROUP BY 1, 2, 3, 4, 5, 6;

-- Quality rule attachments for DP-INS-003.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-INS-003-01: completeness / not_null (severity critical)
-- SELECT 'QR-INS-003-01' AS rule_id, ... FROM DP_INS_003.T_DP_INS_003;

-- QR-INS-003-02: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-INS-003-02' AS rule_id, ... FROM DP_INS_003.T_DP_INS_003;

-- QR-INS-003-03: freshness / partition_completion_by (severity critical)
-- SELECT 'QR-INS-003-03' AS rule_id, ... FROM DP_INS_003.T_DP_INS_003;

-- QR-INS-003-04: validity / in_reference_set (severity high)
-- SELECT 'QR-INS-003-04' AS rule_id, ... FROM DP_INS_003.T_DP_INS_003;

-- QR-INS-003-05: consistency / non_negative (severity high)
-- SELECT 'QR-INS-003-05' AS rule_id, ... FROM DP_INS_003.T_DP_INS_003;
