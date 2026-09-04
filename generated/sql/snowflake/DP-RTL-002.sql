-- AUTO-GENERATED FROM manifests/products/DP-RTL-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-RTL-002 — Inventory Position & Replenishment Signal
-- contract 3.5.0, max sensitivity internal, contains PII: false
-- grain: one row per sku per location per day
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_RTL_002.V_DP_RTL_002 AS
SELECT
  sku,
  location_id,
  activity_date,
  category,
  region,
  store_format,
  season,
  horizon,
  on_hand_units,
  units_received,
  units_sold,
  average_weekly_demand_units,
  forecast_units,
  actual_units,
  unmet_demand_units,
  average_selling_price,
  in_transit_units
FROM DP_RTL_002.T_DP_RTL_002;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.

-- Semantic view for DP-RTL-002 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_RTL_002.SV_DP_RTL_002 AS
SELECT
  activity_date,
  category,
  store_format,
  season,
  horizon,
  (count(*) filter (where on_hand_units > 0)) / NULLIF(count(*), 0) * 100 AS kpi_instock_051,  -- In-Stock Rate (KPI-INSTOCK-051), unit percent
  (sum(on_hand_units)) / NULLIF(sum(average_weekly_demand_units), 0) AS kpi_wos_052,  -- Weeks of Supply (KPI-WOS-052), unit weeks
  (sum(units_sold)) / NULLIF(sum(units_received), 0) * 100 AS kpi_sellthru_053,  -- Sell-Through Rate (KPI-SELLTHRU-053), unit percent
  (sum(abs(forecast_units - actual_units))) / NULLIF(sum(actual_units), 0) * 100 AS kpi_mape_054,  -- Forecast Accuracy MAPE (KPI-MAPE-054), unit percent
  sum(unmet_demand_units * average_selling_price) AS kpi_lostsales_055  -- Lost Sales Estimate (KPI-LOSTSALES-055), unit currency
FROM DP_RTL_002.V_DP_RTL_002
GROUP BY 1, 2, 3, 4, 5;

-- Quality rule attachments for DP-RTL-002.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-RTL-002-01: completeness / not_null (severity critical)
ALTER TABLE DP_RTL_002.T_DP_RTL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (sku);

-- QR-RTL-002-02: freshness / partition_completion_by (severity critical)
ALTER TABLE DP_RTL_002.T_DP_RTL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-RTL-002-03: validity / in_reference_set (severity high)
ALTER TABLE DP_RTL_002.T_DP_RTL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (category);

-- QR-RTL-002-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_RTL_002.T_DP_RTL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (sku, location_id, activity_date);

-- QR-RTL-002-05: consistency / non_negative (severity high)
ALTER TABLE DP_RTL_002.T_DP_RTL_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NON_NEGATIVE ON (on_hand_units);
