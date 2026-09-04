-- AUTO-GENERATED FROM manifests/products/DP-INS-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-INS-001 — Claims Lifecycle & Loss Performance
-- contract 3.0.0, max sensitivity confidential, contains PII: true
-- grain: one row per claim per status transition
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_INS_001.V_DP_INS_001 AS
SELECT
  claim_id,  -- MASK_PII unavailable on this platform; grant by column instead
  policy_id,
  transition_timestamp,
  coverage_line,
  region,
  channel,
  complexity_band,
  adjuster_team,
  claim_status,
  incurred_losses,
  earned_premium,
  cycle_days,
  assessed_leakage_amount,
  subrogation_recovered,
  salvage_recovered,
  settlement_amount,
  triage_rule_version
FROM DP_INS_001.T_DP_INS_001;

-- Semantic view for DP-INS-001 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_INS_001.SV_DP_INS_001 AS
SELECT
  transition_timestamp,
  coverage_line,
  channel,
  complexity_band,
  adjuster_team,
  claim_status,
  triage_rule_version,
  (sum(incurred_losses)) / NULLIF(sum(earned_premium), 0) * 100 AS kpi_lossratio_026,  -- Loss Ratio (KPI-LOSSRATIO-026), unit percent
  percentile_cont(0.5) within group (order by cycle_days) AS kpi_clmcycle_027,  -- Claims Cycle Time (KPI-CLMCYCLE-027), unit days
  (sum(incurred_losses)) / NULLIF(count(distinct claim_id), 0) AS kpi_avgsev_028,  -- Average Claim Severity (KPI-AVGSEV-028), unit currency
  (sum(assessed_leakage_amount)) / NULLIF(sum(incurred_losses), 0) * 100 AS kpi_leakage_029,  -- Claims Leakage Rate (KPI-LEAKAGE-029), unit percent
  (sum(subrogation_recovered) + sum(salvage_recovered)) / NULLIF(sum(incurred_losses), 0) * 100 AS kpi_recovery_030  -- Recovery Rate (KPI-RECOVERY-030), unit percent
FROM DP_INS_001.V_DP_INS_001
GROUP BY 1, 2, 3, 4, 5, 6, 7;

-- Quality rule attachments for DP-INS-001.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-INS-001-01: completeness / not_null (severity critical)
-- SELECT 'QR-INS-001-01' AS rule_id, ... FROM DP_INS_001.T_DP_INS_001;

-- QR-INS-001-02: freshness / partition_completion_by (severity high)
-- SELECT 'QR-INS-001-02' AS rule_id, ... FROM DP_INS_001.T_DP_INS_001;

-- QR-INS-001-03: validity / in_reference_set (severity high)
-- SELECT 'QR-INS-001-03' AS rule_id, ... FROM DP_INS_001.T_DP_INS_001;

-- QR-INS-001-04: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-INS-001-04' AS rule_id, ... FROM DP_INS_001.T_DP_INS_001;

-- QR-INS-001-05: accuracy / reconcile_to_general_ledger (severity critical)
-- SELECT 'QR-INS-001-05' AS rule_id, ... FROM DP_INS_001.T_DP_INS_001;
