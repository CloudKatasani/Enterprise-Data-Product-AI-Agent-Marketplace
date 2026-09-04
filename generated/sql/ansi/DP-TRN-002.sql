-- AUTO-GENERATED FROM manifests/products/DP-TRN-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:46:00+00:00

-- Governed consumption view for DP-TRN-002 — Freight Cost & Margin
-- contract 1.0.0, max sensitivity confidential, contains PII: false
-- grain: one row per carrier invoice line
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_TRN_002.V_DP_TRN_002 AS
SELECT
  invoice_line_id,
  shipment_id,
  invoice_date,
  lane,
  carrier,
  customer,
  service_level,
  mode,
  equipment_type,
  region,
  accessorial_type,
  billed_revenue,
  linehaul_cost,
  accessorial_cost,
  fuel_surcharge,
  contracted_rate,
  spot_rate,
  tendered_to_spot,
  invoice_disputed,
  disputed_amount,
  weight_kg,
  billable_km
FROM DP_TRN_002.T_DP_TRN_002;

-- Semantic view for DP-TRN-002 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_TRN_002.SV_DP_TRN_002 AS
SELECT
  invoice_date,
  lane,
  carrier,
  customer,
  service_level,
  mode,
  equipment_type,
  accessorial_type,
  tendered_to_spot,
  invoice_disputed,
  (sum(billed_revenue) - sum(linehaul_cost) - sum(accessorial_cost) - sum(fuel_surcharge)) / NULLIF(sum(billed_revenue), 0) * 100 AS kpi_frtmargin_088,  -- Freight Margin Rate (KPI-FRTMARGIN-088), unit percent
  (sum(linehaul_cost) + sum(accessorial_cost) + sum(fuel_surcharge)) / NULLIF(sum(billable_km), 0) AS kpi_costperkm_089,  -- Cost per Kilometre (KPI-COSTPERKM-089), unit currency
  (sum(accessorial_cost)) / NULLIF(sum(linehaul_cost) + sum(accessorial_cost) + sum(fuel_surcharge), 0) * 100 AS kpi_accessshare_090,  -- Accessorial Share of Spend (KPI-ACCESSSHARE-090), unit percent
  (count(*) filter (where tendered_to_spot)) / NULLIF(count(*), 0) * 100 AS kpi_spotexp_091,  -- Spot Exposure (KPI-SPOTEXP-091), unit percent
  (sum(disputed_amount)) / NULLIF(sum(billed_revenue), 0) * 100 AS kpi_dispute_092  -- Invoice Dispute Rate (KPI-DISPUTE-092), unit percent
FROM DP_TRN_002.V_DP_TRN_002
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10;

-- Quality rule attachments for DP-TRN-002.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-TRN-002-01: completeness / not_null (severity critical)
-- SELECT 'QR-TRN-002-01' AS rule_id, ... FROM DP_TRN_002.T_DP_TRN_002;

-- QR-TRN-002-02: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-TRN-002-02' AS rule_id, ... FROM DP_TRN_002.T_DP_TRN_002;

-- QR-TRN-002-03: freshness / partition_completion_by (severity critical)
-- SELECT 'QR-TRN-002-03' AS rule_id, ... FROM DP_TRN_002.T_DP_TRN_002;

-- QR-TRN-002-04: validity / in_reference_set (severity high)
-- SELECT 'QR-TRN-002-04' AS rule_id, ... FROM DP_TRN_002.T_DP_TRN_002;

-- QR-TRN-002-05: consistency / non_negative (severity high)
-- SELECT 'QR-TRN-002-05' AS rule_id, ... FROM DP_TRN_002.T_DP_TRN_002;

-- QR-TRN-002-06: accuracy / reconciles_to_source (severity critical)
-- SELECT 'QR-TRN-002-06' AS rule_id, ... FROM DP_TRN_002.T_DP_TRN_002;
