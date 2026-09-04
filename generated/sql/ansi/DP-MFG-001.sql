-- AUTO-GENERATED FROM manifests/products/DP-MFG-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-MFG-001 — Manufacturing Yield & Equipment Effectiveness
-- contract 2.8.0, max sensitivity internal, contains PII: false
-- grain: one row per production run per line per shift
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_MFG_001.V_DP_MFG_001 AS
SELECT
  run_id,
  line,
  plant,
  shift,
  shift_date,
  product_family,
  reason_code,
  downtime_type,
  root_cause,
  availability_rate,
  performance_rate,
  quality_rate,
  started_units,
  scrapped_units,
  passed_without_rework,
  downtime_hours,
  changeover_minutes,
  standardised_changeover
FROM DP_MFG_001.T_DP_MFG_001;

-- Semantic view for DP-MFG-001 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_MFG_001.SV_DP_MFG_001 AS
SELECT
  line,
  shift,
  shift_date,
  product_family,
  reason_code,
  downtime_type,
  root_cause,
  passed_without_rework,
  standardised_changeover,
  avg(availability_rate * performance_rate * quality_rate) AS kpi_oee_071,  -- Overall Equipment Effectiveness (KPI-OEE-071), unit percent
  (count(*) filter (where passed_without_rework)) / NULLIF(count(*), 0) * 100 AS kpi_fpy_072,  -- First Pass Yield (KPI-FPY-072), unit percent
  sum(downtime_hours) filter (where downtime_type = 'unplanned') AS kpi_downtime_073,  -- Unplanned Downtime Hours (KPI-DOWNTIME-073), unit hours
  (sum(scrapped_units)) / NULLIF(sum(started_units), 0) * 100 AS kpi_scrap_074,  -- Scrap Rate (KPI-SCRAP-074), unit percent
  percentile_cont(0.5) within group (order by changeover_minutes) AS kpi_changeover_075  -- Changeover Time (KPI-CHANGEOVER-075), unit minutes
FROM DP_MFG_001.V_DP_MFG_001
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9;

-- Quality rule attachments for DP-MFG-001.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-MFG-001-01: completeness / not_null (severity critical)
-- SELECT 'QR-MFG-001-01' AS rule_id, ... FROM DP_MFG_001.T_DP_MFG_001;

-- QR-MFG-001-02: freshness / partition_completion_by (severity high)
-- SELECT 'QR-MFG-001-02' AS rule_id, ... FROM DP_MFG_001.T_DP_MFG_001;

-- QR-MFG-001-03: validity / in_reference_set (severity high)
-- SELECT 'QR-MFG-001-03' AS rule_id, ... FROM DP_MFG_001.T_DP_MFG_001;

-- QR-MFG-001-04: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-MFG-001-04' AS rule_id, ... FROM DP_MFG_001.T_DP_MFG_001;

-- QR-MFG-001-05: consistency / not_greater_than_started (severity high)
-- SELECT 'QR-MFG-001-05' AS rule_id, ... FROM DP_MFG_001.T_DP_MFG_001;
