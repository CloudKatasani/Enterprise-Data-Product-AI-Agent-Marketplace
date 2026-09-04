-- AUTO-GENERATED FROM manifests/products/DP-HLT-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-HLT-001 — Patient Care Journey & Readmission
-- contract 4.3.0, max sensitivity restricted, contains PII: true
-- grain: one row per encounter and per journey segment
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_HLT_001.V_DP_HLT_001 AS
SELECT
  encounter_id,  -- MASK_PHI unavailable on this platform; grant by column instead
  index_encounter_id,  -- MASK_PHI unavailable on this platform; grant by column instead
  attributed_member_id,  -- MASK_PHI unavailable on this platform; grant by column instead
  ed_encounter_id,  -- MASK_PHI unavailable on this platform; grant by column instead
  discharge_date,  -- MASK_PHI unavailable on this platform; grant by column instead
  condition,
  unit,
  payer,
  region,
  clinic,
  measure,
  discharge_disposition,
  eligible_index,
  readmitted_within_30d,
  inpatient_days,
  days_to_followup,
  gap_open_at_period_start,
  gap_closed,
  programme_enrolled
FROM DP_HLT_001.T_DP_HLT_001;

-- Semantic view for DP-HLT-001 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_HLT_001.SV_DP_HLT_001 AS
SELECT
  unit,
  payer,
  clinic,
  eligible_index,
  (count(distinct index_encounter_id) filter (where readmitted_within_30d)) / NULLIF(count(distinct index_encounter_id) filter (where eligible_index), 0) * 100 AS kpi_readmit_036,  -- Thirty Day Readmission Rate (KPI-READMIT-036), unit percent
  (sum(inpatient_days)) / NULLIF(count(distinct encounter_id), 0) AS kpi_alos_037,  -- Average Length of Stay (KPI-ALOS-037), unit days
  (count(distinct ed_encounter_id) * 1000) / NULLIF(count(distinct attributed_member_id), 0) AS kpi_edutil_038,  -- Emergency Department Utilization Rate (KPI-EDUTIL-038), unit rate
  (count(*) filter (where gap_closed)) / NULLIF(count(*) filter (where gap_open_at_period_start), 0) * 100 AS kpi_caregap_039,  -- Care Gap Closure (KPI-CAREGAP-039), unit percent
  percentile_cont(0.5) within group (order by days_to_followup) AS kpi_followup_040  -- Discharge to Follow-up Interval (KPI-FOLLOWUP-040), unit days
FROM DP_HLT_001.V_DP_HLT_001
GROUP BY 1, 2, 3, 4;

-- Quality rule attachments for DP-HLT-001.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-HLT-001-01: completeness / not_null (severity critical)
-- SELECT 'QR-HLT-001-01' AS rule_id, ... FROM DP_HLT_001.T_DP_HLT_001;

-- QR-HLT-001-02: freshness / partition_completion_by (severity critical)
-- SELECT 'QR-HLT-001-02' AS rule_id, ... FROM DP_HLT_001.T_DP_HLT_001;

-- QR-HLT-001-03: validity / in_reference_set (severity critical)
-- SELECT 'QR-HLT-001-03' AS rule_id, ... FROM DP_HLT_001.T_DP_HLT_001;

-- QR-HLT-001-04: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-HLT-001-04' AS rule_id, ... FROM DP_HLT_001.T_DP_HLT_001;

-- QR-HLT-001-05: consistency / implies_index_eligible (severity critical)
-- SELECT 'QR-HLT-001-05' AS rule_id, ... FROM DP_HLT_001.T_DP_HLT_001;

-- QR-HLT-001-06: accuracy / reconcile_to_adt (severity high)
-- SELECT 'QR-HLT-001-06' AS rule_id, ... FROM DP_HLT_001.T_DP_HLT_001;
