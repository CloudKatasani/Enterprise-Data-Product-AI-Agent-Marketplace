-- AUTO-GENERATED FROM manifests/products/DP-HLT-003.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:35:53+00:00

-- Governed consumption view for DP-HLT-003 — Workforce & Care Capacity
-- contract 1.0.0, max sensitivity internal, contains PII: false
-- grain: one row per unit per shift
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_HLT_003.V_DP_HLT_003 AS
SELECT
  unit_id,
  shift_start,
  facility,
  region,
  unit_type,
  shift,
  budgeted_hours,
  worked_hours,
  overtime_hours,
  agency_hours,
  census_patients,
  staffed_beds,
  licensed_beds,
  admissions,
  discharges,
  boarding_hours,
  call_offs,
  vacancy_count,
  filled_shift,
  float_pool_used
FROM DP_HLT_003.T_DP_HLT_003;

-- Semantic view for DP-HLT-003 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_HLT_003.SV_DP_HLT_003 AS
SELECT
  shift_start,
  facility,
  unit_type,
  shift,
  filled_shift,
  float_pool_used,
  (sum(overtime_hours)) / NULLIF(sum(worked_hours), 0) * 100 AS kpi_otshare_098,  -- Overtime Share of Hours (KPI-OTSHARE-098), unit percent
  (sum(agency_hours)) / NULLIF(sum(worked_hours), 0) * 100 AS kpi_agency_099,  -- Agency Hours Share (KPI-AGENCY-099), unit percent
  (sum(census_patients)) / NULLIF(sum(staffed_beds), 0) * 100 AS kpi_occup_100,  -- Bed Occupancy (KPI-OCCUP-100), unit percent
  (sum(worked_hours)) / NULLIF(sum(census_patients), 0) AS kpi_hppd_101,  -- Hours per Patient Day (KPI-HPPD-101), unit hours
  percentile_cont(0.5) within group (order by boarding_hours) AS kpi_board_102  -- Median Boarding Hours (KPI-BOARD-102), unit hours
FROM DP_HLT_003.V_DP_HLT_003
GROUP BY 1, 2, 3, 4, 5, 6;

-- Quality rule attachments for DP-HLT-003.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-HLT-003-01: completeness / not_null (severity critical)
-- SELECT 'QR-HLT-003-01' AS rule_id, ... FROM DP_HLT_003.T_DP_HLT_003;

-- QR-HLT-003-02: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-HLT-003-02' AS rule_id, ... FROM DP_HLT_003.T_DP_HLT_003;

-- QR-HLT-003-03: freshness / partition_completion_by (severity critical)
-- SELECT 'QR-HLT-003-03' AS rule_id, ... FROM DP_HLT_003.T_DP_HLT_003;

-- QR-HLT-003-04: validity / in_reference_set (severity high)
-- SELECT 'QR-HLT-003-04' AS rule_id, ... FROM DP_HLT_003.T_DP_HLT_003;

-- QR-HLT-003-05: consistency / non_negative (severity high)
-- SELECT 'QR-HLT-003-05' AS rule_id, ... FROM DP_HLT_003.T_DP_HLT_003;
