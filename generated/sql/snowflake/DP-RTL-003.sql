-- AUTO-GENERATED FROM manifests/products/DP-RTL-003.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: e3907c67cfe5f6a0bf970d3e3e080796aefa5731f02cd93c3c8cb9c4c93a5cbe  generated_at: 2026-09-04T16:02:50+00:00

-- Governed consumption view for DP-RTL-003 — Visit & Conversion Funnel
-- contract 1.0.0, max sensitivity internal, contains PII: false
-- grain: one row per visit
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_RTL_003.V_DP_RTL_003 AS
SELECT
  visit_id,
  transaction_id,
  visit_timestamp,
  business_date,
  region,
  channel,
  store_format,
  entry_category,
  device_class,
  traffic_source,
  loyalty_identified,
  converted,
  basket_started,
  basket_abandoned,
  items_viewed,
  dwell_seconds,
  net_sales
FROM DP_RTL_003.T_DP_RTL_003;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.

-- Semantic view for DP-RTL-003 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_RTL_003.SV_DP_RTL_003 AS
SELECT
  visit_timestamp,
  business_date,
  channel,
  store_format,
  entry_category,
  device_class,
  traffic_source,
  loyalty_identified,
  converted,
  basket_started,
  basket_abandoned,
  (count(distinct transaction_id)) / NULLIF(count(distinct visit_id), 0) * 100 AS kpi_convrate_048,  -- Conversion Rate (KPI-CONVRATE-048), unit percent
  (count(distinct visit_id) filter (where basket_abandoned)) / NULLIF(count(distinct visit_id) filter (where basket_started), 0) * 100 AS kpi_abandon_076,  -- Basket Abandonment Rate (KPI-ABANDON-076), unit percent
  percentile_cont(0.5) within group (order by dwell_seconds / 60.0) AS kpi_visitdwell_077  -- Median Visit Dwell (KPI-VISITDWELL-077), unit minutes
FROM DP_RTL_003.V_DP_RTL_003
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11;

-- Quality rule attachments for DP-RTL-003.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-RTL-003-01: completeness / not_null (severity critical)
ALTER TABLE DP_RTL_003.T_DP_RTL_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (visit_id);

-- QR-RTL-003-02: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_RTL_003.T_DP_RTL_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (visit_id);

-- QR-RTL-003-03: freshness / partition_completion_by (severity critical)
ALTER TABLE DP_RTL_003.T_DP_RTL_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-RTL-003-04: validity / in_reference_set (severity high)
ALTER TABLE DP_RTL_003.T_DP_RTL_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (channel);

-- QR-RTL-003-05: consistency / non_negative (severity high)
ALTER TABLE DP_RTL_003.T_DP_RTL_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NON_NEGATIVE ON (dwell_seconds);
