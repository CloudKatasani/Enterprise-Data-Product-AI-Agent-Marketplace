-- AUTO-GENERATED FROM manifests/products/DP-ENG-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 99a80e0d1dbb27012fc672eef277ab5269c9f0e90b8e24b75c55f0a9b2cc01a0  generated_at: 2026-09-04T15:18:50+00:00

-- Governed consumption view for DP-ENG-001 — Smart Meter Consumption & Load Profile
-- contract 2.1.0, max sensitivity confidential, contains PII: true
-- grain: one row per meter per interval
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_ENG_001.V_DP_ENG_001 AS
SELECT
  meter_id,  -- masking policy MASK_PII attached below
  interval_start,
  rate_class,
  region,
  feeder,
  dwelling_type,
  meter_type,
  programme,
  read_type,
  consumption_kwh,
  interval_demand_kw,
  period_hours,
  enrolled_and_called,
  curtailed_during_event,
  temperature_c
FROM DP_ENG_001.T_DP_ENG_001;

-- Column masking, applied in the platform.
ALTER TABLE DP_ENG_001.T_DP_ENG_001 MODIFY COLUMN meter_id SET MASKING POLICY GOVERNANCE.MASK_PII;

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_ENG_001.T_DP_ENG_001 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-ENG-001 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_ENG_001.SV_DP_ENG_001 AS
SELECT
  interval_start,
  rate_class,
  feeder,
  dwelling_type,
  meter_type,
  programme,
  read_type,
  enrolled_and_called,
  max(interval_demand_kw) AS kpi_peakdem_066,  -- Peak Demand (KPI-PEAKDEM-066), unit count
  (avg(interval_demand_kw)) / NULLIF(max(interval_demand_kw), 0) AS kpi_loadfact_067,  -- Load Factor (KPI-LOADFACT-067), unit ratio
  (sum(consumption_kwh)) / NULLIF(count(distinct meter_id), 0) AS kpi_conspc_068,  -- Consumption per Customer (KPI-CONSPC-068), unit count
  (count(distinct meter_id) filter (where curtailed_during_event)) / NULLIF(count(distinct meter_id) filter (where enrolled_and_called), 0) * 100 AS kpi_drresp_069,  -- Demand Response Event Response Rate (KPI-DRRESP-069), unit percent
  (count(*) filter (where read_type = 'estimated')) / NULLIF(count(*), 0) * 100 AS kpi_estread_070  -- Estimated Read Rate (KPI-ESTREAD-070), unit percent
FROM DP_ENG_001.V_DP_ENG_001
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8;

-- Quality rule attachments for DP-ENG-001.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-ENG-001-01: completeness / not_null (severity critical)
ALTER TABLE DP_ENG_001.T_DP_ENG_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (meter_id);

-- QR-ENG-001-02: freshness / partition_completion_by (severity high)
ALTER TABLE DP_ENG_001.T_DP_ENG_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-ENG-001-03: validity / in_reference_set (severity high)
ALTER TABLE DP_ENG_001.T_DP_ENG_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (rate_class);

-- QR-ENG-001-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_ENG_001.T_DP_ENG_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (meter_id, interval_start);

-- QR-ENG-001-05: consistency / estimated_implies_null_interval (severity medium)
ALTER TABLE DP_ENG_001.T_DP_ENG_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_ESTIMATED_IMPLIES_NULL_INTERVAL ON (read_type);
