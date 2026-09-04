-- AUTO-GENERATED FROM manifests/products/DP-RTL-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: e3907c67cfe5f6a0bf970d3e3e080796aefa5731f02cd93c3c8cb9c4c93a5cbe  generated_at: 2026-09-04T15:57:41+00:00

-- Governed consumption view for DP-RTL-001 — Omnichannel Sales & Basket Analytics
-- contract 6.2.0, max sensitivity internal, contains PII: false
-- grain: one row per transaction line
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_RTL_001.V_DP_RTL_001 AS
SELECT
  transaction_id,
  visit_id,
  business_date,
  category,
  sku,
  region,
  channel,
  store_format,
  promotion,
  comparable_store,
  net_sales,
  prior_year_net_sales,
  cost_of_goods_sold,
  promoted_sales,
  baseline_sales,
  units,
  basket_item_count
FROM DP_RTL_001.T_DP_RTL_001;

-- Semantic view for DP-RTL-001 — one measure per certified KPI.
-- ANSI dialect: no semantic layer object exists, so this is a plain view.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_RTL_001.SV_DP_RTL_001 AS
SELECT
  business_date,
  category,
  channel,
  store_format,
  promotion,
  comparable_store,
  (sum(net_sales) - sum(prior_year_net_sales)) / NULLIF(sum(prior_year_net_sales), 0) * 100 AS kpi_compsales_046,  -- Comparable Sales Growth (KPI-COMPSALES-046), unit percent
  (sum(net_sales)) / NULLIF(count(distinct transaction_id), 0) AS kpi_basket_047,  -- Average Basket Value (KPI-BASKET-047), unit currency
  (sum(net_sales) - sum(cost_of_goods_sold)) / NULLIF(sum(net_sales), 0) * 100 AS kpi_gmrate_049,  -- Gross Margin Rate (KPI-GMRATE-049), unit percent
  (sum(promoted_sales) - sum(baseline_sales)) / NULLIF(sum(baseline_sales), 0) * 100 AS kpi_promolift_050  -- Promotion Lift (KPI-PROMOLIFT-050), unit percent
FROM DP_RTL_001.V_DP_RTL_001
GROUP BY 1, 2, 3, 4, 5, 6;

-- Quality rule attachments for DP-RTL-001.
-- Results land in quality_result and are the evidence a composite is computed from.
-- ANSI dialect: emitted as check queries for an external scheduler.

-- QR-RTL-001-01: completeness / not_null (severity critical)
-- SELECT 'QR-RTL-001-01' AS rule_id, ... FROM DP_RTL_001.T_DP_RTL_001;

-- QR-RTL-001-02: freshness / partition_completion_by (severity critical)
-- SELECT 'QR-RTL-001-02' AS rule_id, ... FROM DP_RTL_001.T_DP_RTL_001;

-- QR-RTL-001-03: validity / in_reference_set (severity high)
-- SELECT 'QR-RTL-001-03' AS rule_id, ... FROM DP_RTL_001.T_DP_RTL_001;

-- QR-RTL-001-04: uniqueness / unique_at_grain (severity critical)
-- SELECT 'QR-RTL-001-04' AS rule_id, ... FROM DP_RTL_001.T_DP_RTL_001;

-- QR-RTL-001-05: accuracy / reconcile_to_finance_ledger (severity critical)
-- SELECT 'QR-RTL-001-05' AS rule_id, ... FROM DP_RTL_001.T_DP_RTL_001;
