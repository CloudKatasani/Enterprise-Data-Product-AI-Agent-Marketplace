-- AUTO-GENERATED FROM manifests/products/DP-TRN-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-TRN-001 — Fleet Movement & Delivery Performance
-- contract 2.2.0, max sensitivity internal, contains PII: false
-- grain: one row per shipment leg
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_TRN_001.V_DP_TRN_001 AS
SELECT
  shipment_leg_id,
  shipment_id,
  departure_timestamp,
  lane,
  carrier,
  customer,
  service_level,
  facility,
  equipment_type,
  region,
  exception_type,
  delivery_attempted,
  delivered_within_window,
  exception_logged,
  loaded_miles,
  linehaul_cost,
  accessorial_cost,
  dwell_hours,
  revenue_hours,
  available_hours,
  sla_penalty_risk
FROM DP_TRN_001.T_DP_TRN_001;

-- Semantic view for DP-TRN-001 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_TRN_001.SV_DP_TRN_001 AS
SELECT
  departure_timestamp,
  lane,
  carrier,
  service_level,
  facility,
  equipment_type,
  exception_type,
  delivery_attempted,
  delivered_within_window,
  exception_logged,
  sla_penalty_risk,
  (count(*) filter (where delivered_within_window)) / NULLIF(count(*) filter (where delivery_attempted), 0) * 100 AS kpi_otd_056,  -- On-Time Delivery Rate (KPI-OTD-056), unit percent
  (sum(linehaul_cost) + sum(accessorial_cost)) / NULLIF(sum(loaded_miles), 0) AS kpi_cpm_057,  -- Cost per Mile (KPI-CPM-057), unit currency
  percentile_cont(0.5) within group (order by dwell_hours) AS kpi_dwell_058,  -- Dwell Time (KPI-DWELL-058), unit hours
  (sum(revenue_hours)) / NULLIF(sum(available_hours), 0) * 100 AS kpi_assetutil_059,  -- Asset Utilization (KPI-ASSETUTIL-059), unit percent
  (count(*) filter (where exception_logged)) / NULLIF(count(*), 0) * 100 AS kpi_excrate_060  -- Exception Rate (KPI-EXCRATE-060), unit percent
FROM DP_TRN_001.V_DP_TRN_001
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11;

-- Quality rule attachments for DP-TRN-001.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-TRN-001-01: completeness / not_null (severity critical)
-- SELECT 'QR-TRN-001-01' AS rule_id, ... FROM DP_TRN_001.T_DP_TRN_001;

-- QR-TRN-001-02: freshness / stream_lag_under (severity critical)
-- SELECT 'QR-TRN-001-02' AS rule_id, ... FROM DP_TRN_001.T_DP_TRN_001;

-- QR-TRN-001-03: validity / in_reference_set (severity high)
-- SELECT 'QR-TRN-001-03' AS rule_id, ... FROM DP_TRN_001.T_DP_TRN_001;

-- QR-TRN-001-04: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-TRN-001-04' AS rule_id, ... FROM DP_TRN_001.T_DP_TRN_001;

-- QR-TRN-001-05: consistency / not_greater_than_available (severity high)
-- SELECT 'QR-TRN-001-05' AS rule_id, ... FROM DP_TRN_001.T_DP_TRN_001;
