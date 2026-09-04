-- AUTO-GENERATED FROM manifests/products/DP-UTL-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-UTL-001 — Grid Asset Health & Outage
-- contract 3.7.0, max sensitivity internal, contains PII: false
-- grain: one row per asset per day and per outage event
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_UTL_001.V_DP_UTL_001 AS
SELECT
  asset_id,
  outage_id,
  observed_date,
  feeder,
  region,
  asset_class,
  vintage_band,
  cause_class,
  crew,
  served_customer_id,
  customer_interruptions,
  customer_interruption_minutes,
  restoration_minutes,
  asset_health_score,
  scheduled,
  completed_within_window,
  deferral_count,
  major_event_day,
  load_impact_mw
FROM DP_UTL_001.T_DP_UTL_001;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.

-- Semantic view for DP-UTL-001 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_UTL_001.SV_DP_UTL_001 AS
SELECT
  observed_date,
  feeder,
  asset_class,
  vintage_band,
  cause_class,
  crew,
  scheduled,
  completed_within_window,
  major_event_day,
  (sum(customer_interruption_minutes)) / NULLIF(count(distinct served_customer_id), 0) AS kpi_saidi_061,  -- SAIDI (KPI-SAIDI-061), unit minutes
  (sum(customer_interruptions)) / NULLIF(count(distinct served_customer_id), 0) AS kpi_saifi_062,  -- SAIFI (KPI-SAIFI-062), unit count
  avg(asset_health_score) AS kpi_ahi_063,  -- Asset Health Index (KPI-AHI-063), unit score
  (sum(restoration_minutes)) / NULLIF(count(distinct outage_id), 0) AS kpi_restore_064,  -- Average Restoration Time (KPI-RESTORE-064), unit minutes
  (count(*) filter (where completed_within_window)) / NULLIF(count(*) filter (where scheduled), 0) * 100 AS kpi_pmcomp_065  -- Preventive Maintenance Compliance (KPI-PMCOMP-065), unit percent
FROM DP_UTL_001.V_DP_UTL_001
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9;

-- Quality rule attachments for DP-UTL-001.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-UTL-001-01: completeness / not_null (severity critical)
ALTER TABLE DP_UTL_001.T_DP_UTL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (asset_id);

-- QR-UTL-001-02: freshness / stream_lag_under (severity critical)
ALTER TABLE DP_UTL_001.T_DP_UTL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_STREAM_LAG_UNDER ON (*);

-- QR-UTL-001-03: validity / in_reference_set (severity critical)
ALTER TABLE DP_UTL_001.T_DP_UTL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (asset_class);

-- QR-UTL-001-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_UTL_001.T_DP_UTL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (asset_id, observed_date, outage_id);

-- QR-UTL-001-05: accuracy / reconcile_to_oms (severity critical)
ALTER TABLE DP_UTL_001.T_DP_UTL_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_RECONCILE_TO_OMS ON (customer_interruption_minutes);
