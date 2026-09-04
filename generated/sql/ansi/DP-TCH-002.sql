-- AUTO-GENERATED FROM manifests/products/DP-TCH-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:35:53+00:00

-- Governed consumption view for DP-TCH-002 — Service Reliability & Incident
-- contract 1.0.0, max sensitivity internal, contains PII: false
-- grain: one row per service per hour
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_TCH_002.V_DP_TCH_002 AS
SELECT
  service_id,
  observed_hour,
  service_tier,
  region,
  team,
  deployment_ring,
  incident_id,
  severity,
  request_count,
  error_count,
  latency_p95_ms,
  availability_minutes,
  scheduled_minutes,
  acknowledged_minutes,
  resolved_minutes,
  change_deployed,
  change_failed,
  on_call_page_count
FROM DP_TCH_002.T_DP_TCH_002;

-- Semantic view for DP-TCH-002 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_TCH_002.SV_DP_TCH_002 AS
SELECT
  observed_hour,
  service_tier,
  team,
  deployment_ring,
  severity,
  change_deployed,
  change_failed,
  (sum(error_count)) / NULLIF(sum(request_count), 0) * 100 AS kpi_errrate_083,  -- Service Error Rate (KPI-ERRRATE-083), unit percent
  (sum(availability_minutes)) / NULLIF(sum(scheduled_minutes), 0) * 100 AS kpi_svcavail_084,  -- Service Availability (KPI-SVCAVAIL-084), unit percent
  (sum(acknowledged_minutes)) / NULLIF(count(distinct incident_id), 0) AS kpi_mtta_085,  -- Mean Time to Acknowledge (KPI-MTTA-085), unit minutes
  (sum(resolved_minutes)) / NULLIF(count(distinct incident_id), 0) AS kpi_mttr_086,  -- Mean Time to Restore (KPI-MTTR-086), unit minutes
  (count(*) filter (where change_failed)) / NULLIF(count(*) filter (where change_deployed), 0) * 100 AS kpi_chgfail_087  -- Change Failure Rate (KPI-CHGFAIL-087), unit percent
FROM DP_TCH_002.V_DP_TCH_002
GROUP BY 1, 2, 3, 4, 5, 6, 7;

-- Quality rule attachments for DP-TCH-002.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-TCH-002-01: completeness / not_null (severity critical)
-- SELECT 'QR-TCH-002-01' AS rule_id, ... FROM DP_TCH_002.T_DP_TCH_002;

-- QR-TCH-002-02: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-TCH-002-02' AS rule_id, ... FROM DP_TCH_002.T_DP_TCH_002;

-- QR-TCH-002-03: freshness / partition_completion_by (severity critical)
-- SELECT 'QR-TCH-002-03' AS rule_id, ... FROM DP_TCH_002.T_DP_TCH_002;

-- QR-TCH-002-04: validity / in_reference_set (severity high)
-- SELECT 'QR-TCH-002-04' AS rule_id, ... FROM DP_TCH_002.T_DP_TCH_002;

-- QR-TCH-002-05: consistency / non_negative (severity high)
-- SELECT 'QR-TCH-002-05' AS rule_id, ... FROM DP_TCH_002.T_DP_TCH_002;
