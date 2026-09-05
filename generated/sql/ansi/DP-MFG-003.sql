-- AUTO-GENERATED FROM manifests/products/DP-MFG-003.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 0c3198c3ee40134cbb187b05e5dbb00d74d7c572396ee69c86940cc6744f0d95  generated_at: 2026-09-05T23:26:01+00:00

-- Governed consumption view for DP-MFG-003 — Equipment Reliability & Maintenance
-- contract 1.0.0, max sensitivity internal, contains PII: false
-- grain: one row per maintenance work order
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_MFG_003.V_DP_MFG_003 AS
SELECT
  work_order_id,
  asset_id,
  failure_id,
  raised_at,
  plant,
  line,
  region,
  asset_class,
  criticality,
  failure_mode,
  crew,
  operating_hours,
  maintenance_hours,
  repair_minutes,
  unplanned,
  preventive_scheduled,
  completed_in_window,
  spares_needed,
  spares_available,
  condition_alert_open,
  asset_age_years
FROM DP_MFG_003.T_DP_MFG_003;

-- Semantic view for DP-MFG-003 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_MFG_003.SV_DP_MFG_003 AS
SELECT
  raised_at,
  plant,
  line,
  asset_class,
  criticality,
  failure_mode,
  crew,
  unplanned,
  preventive_scheduled,
  completed_in_window,
  spares_needed,
  spares_available,
  condition_alert_open,
  (sum(operating_hours)) / NULLIF(count(distinct failure_id), 0) AS kpi_mtbf_108,  -- Mean Time Between Failures (KPI-MTBF-108), unit hours
  (sum(repair_minutes)) / NULLIF(count(distinct failure_id), 0) AS kpi_mttrepair_109,  -- Mean Time to Repair (KPI-MTTREPAIR-109), unit minutes
  (count(*) filter (where completed_in_window)) / NULLIF(count(*) filter (where preventive_scheduled), 0) * 100 AS kpi_pmadhere_110,  -- Preventive Maintenance Adherence (KPI-PMADHERE-110), unit percent
  (sum(maintenance_hours) filter (where unplanned)) / NULLIF(sum(maintenance_hours), 0) * 100 AS kpi_unplanned_111,  -- Unplanned Maintenance Share (KPI-UNPLANNED-111), unit percent
  (count(*) filter (where spares_available)) / NULLIF(count(*) filter (where spares_needed), 0) * 100 AS kpi_sparesavail_112  -- Spares Availability at Call (KPI-SPARESAVAIL-112), unit percent
FROM DP_MFG_003.V_DP_MFG_003
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13;

-- Quality rule attachments for DP-MFG-003.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-MFG-003-01: completeness / not_null (severity critical)
-- SELECT 'QR-MFG-003-01' AS rule_id, ... FROM DP_MFG_003.T_DP_MFG_003;

-- QR-MFG-003-02: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-MFG-003-02' AS rule_id, ... FROM DP_MFG_003.T_DP_MFG_003;

-- QR-MFG-003-03: freshness / partition_completion_by (severity critical)
-- SELECT 'QR-MFG-003-03' AS rule_id, ... FROM DP_MFG_003.T_DP_MFG_003;

-- QR-MFG-003-04: validity / in_reference_set (severity high)
-- SELECT 'QR-MFG-003-04' AS rule_id, ... FROM DP_MFG_003.T_DP_MFG_003;

-- QR-MFG-003-05: consistency / non_negative (severity high)
-- SELECT 'QR-MFG-003-05' AS rule_id, ... FROM DP_MFG_003.T_DP_MFG_003;
