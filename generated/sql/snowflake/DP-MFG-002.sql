-- AUTO-GENERATED FROM manifests/products/DP-MFG-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:35:53+00:00

-- Governed consumption view for DP-MFG-002 — Supplier Quality & Inbound Materials
-- contract 1.0.0, max sensitivity confidential, contains PII: false
-- grain: one row per inbound receipt line
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_MFG_002.V_DP_MFG_002 AS
SELECT
  receipt_line_id,
  purchase_order_id,
  supplier_id,
  receipt_date,
  material_class,
  plant,
  region,
  supplier_tier,
  country_of_origin,
  ordered_units,
  received_units,
  accepted_units,
  rejected_units,
  rejection_reason,
  promised_date,
  on_time,
  inspection_required,
  inspection_passed,
  unit_cost,
  standard_cost,
  lead_time_days
FROM DP_MFG_002.T_DP_MFG_002;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_MFG_002.T_DP_MFG_002 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-MFG-002 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_MFG_002.SV_DP_MFG_002 AS
SELECT
  receipt_date,
  material_class,
  plant,
  supplier_tier,
  rejection_reason,
  promised_date,
  on_time,
  inspection_required,
  inspection_passed,
  (sum(rejected_units)) / NULLIF(sum(received_units), 0) * 100 AS kpi_suppdef_093,  -- Supplier Defect Rate (KPI-SUPPDEF-093), unit percent
  (count(*) filter (where on_time)) / NULLIF(count(*), 0) * 100 AS kpi_inbotd_094,  -- Inbound On-Time Rate (KPI-INBOTD-094), unit percent
  (sum(received_units)) / NULLIF(sum(ordered_units), 0) * 100 AS kpi_fillrate_095,  -- Supplier Fill Rate (KPI-FILLRATE-095), unit percent
  sum((unit_cost - standard_cost) * received_units) AS kpi_ppv_096,  -- Purchase Price Variance (KPI-PPV-096), unit currency
  percentile_cont(0.5) within group (order by lead_time_days) AS kpi_inblead_097  -- Median Inbound Lead Time (KPI-INBLEAD-097), unit days
FROM DP_MFG_002.V_DP_MFG_002
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9;

-- Quality rule attachments for DP-MFG-002.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-MFG-002-01: completeness / not_null (severity critical)
ALTER TABLE DP_MFG_002.T_DP_MFG_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (receipt_line_id);

-- QR-MFG-002-02: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_MFG_002.T_DP_MFG_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (receipt_line_id);

-- QR-MFG-002-03: freshness / partition_completion_by (severity critical)
ALTER TABLE DP_MFG_002.T_DP_MFG_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-MFG-002-04: validity / in_reference_set (severity high)
ALTER TABLE DP_MFG_002.T_DP_MFG_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (material_class);

-- QR-MFG-002-05: consistency / non_negative (severity high)
ALTER TABLE DP_MFG_002.T_DP_MFG_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NON_NEGATIVE ON (received_units);
