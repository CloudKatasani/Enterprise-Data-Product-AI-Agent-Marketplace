-- AUTO-GENERATED FROM manifests/products/DP-TEL-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-TEL-002 — Network Experience & Fault Signal
-- contract 2.4.0, max sensitivity internal, contains PII: false
-- grain: one row per site per hour
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_TEL_002.V_DP_TEL_002 AS
SELECT
  site_id,
  observed_hour,
  region,
  site_class,
  technology,
  available_minutes,
  scheduled_minutes,
  established_calls,
  dropped_calls,
  throughput_mbps,
  fault_class,
  fault_closed,
  restore_minutes,
  impacted_subscribers,
  outage_hours,
  impacted_subscriber_hours
FROM DP_TEL_002.T_DP_TEL_002;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.

-- Semantic view for DP-TEL-002 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_TEL_002.SV_DP_TEL_002 AS
SELECT
  observed_hour,
  site_class,
  technology,
  fault_class,
  fault_closed,
  (sum(available_minutes)) / NULLIF(sum(scheduled_minutes), 0) * 100 AS kpi_netavail_006,  -- Network Availability (KPI-NETAVAIL-006), unit percent
  (sum(dropped_calls)) / NULLIF(sum(established_calls), 0) * 100 AS kpi_drop_007,  -- Dropped Call Rate (KPI-DROP-007), unit percent
  percentile_cont(0.5) within group (order by throughput_mbps) AS kpi_thrput_008,  -- Throughput Percentile (KPI-THRPUT-008), unit rate
  (sum(restore_minutes)) / NULLIF(count(*) filter (where fault_closed), 0) AS kpi_fmttr_009,  -- Fault Mean Time to Restore (KPI-FMTTR-009), unit hours
  sum(impacted_subscribers * outage_hours) AS kpi_imphrs_010  -- Impacted Subscriber Hours (KPI-IMPHRS-010), unit count
FROM DP_TEL_002.V_DP_TEL_002
GROUP BY 1, 2, 3, 4, 5;

-- Quality rule attachments for DP-TEL-002.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-TEL-002-01: completeness / not_null (severity critical)
ALTER TABLE DP_TEL_002.T_DP_TEL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (site_id);

-- QR-TEL-002-02: freshness / partition_completion_by (severity critical)
ALTER TABLE DP_TEL_002.T_DP_TEL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-TEL-002-03: validity / in_reference_set (severity high)
ALTER TABLE DP_TEL_002.T_DP_TEL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (technology);

-- QR-TEL-002-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_TEL_002.T_DP_TEL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (site_id, observed_hour);

-- QR-TEL-002-05: consistency / not_greater_than_scheduled (severity high)
ALTER TABLE DP_TEL_002.T_DP_TEL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_GREATER_THAN_SCHEDULED ON (available_minutes);
