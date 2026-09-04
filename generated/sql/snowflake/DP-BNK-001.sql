-- AUTO-GENERATED FROM manifests/products/DP-BNK-001.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-BNK-001 — Customer Financial 360
-- contract 5.0.0, max sensitivity restricted, contains PII: true
-- grain: one row per customer per month
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_BNK_001.V_DP_BNK_001 AS
SELECT
  customer_id,  -- masking policy MASK_PII attached below
  household_id,  -- masking policy MASK_PII attached below
  as_of_month,
  segment,
  region,
  tenure_band,
  value_band,
  product_family,
  active_product_count,
  primary_relationship,
  starting_deposit_balance,
  ending_deposit_balance,
  discounted_contribution_margin,
  attrition_model_score,
  relationship_value,
  last_contact_date
FROM DP_BNK_001.T_DP_BNK_001;

-- Column masking, applied in the platform.
ALTER TABLE DP_BNK_001.T_DP_BNK_001 MODIFY COLUMN customer_id SET MASKING POLICY GOVERNANCE.MASK_PII;
ALTER TABLE DP_BNK_001.T_DP_BNK_001 MODIFY COLUMN household_id SET MASKING POLICY GOVERNANCE.MASK_PII;

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_BNK_001.T_DP_BNK_001 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-BNK-001 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_BNK_001.SV_DP_BNK_001 AS
SELECT
  as_of_month,
  segment,
  tenure_band,
  value_band,
  product_family,
  last_contact_date,
  (count(distinct customer_id) filter (where primary_relationship)) / NULLIF(count(distinct customer_id), 0) * 100 AS kpi_pbshare_016,  -- Primary Bank Share (KPI-PBSHARE-016), unit percent
  (sum(active_product_count)) / NULLIF(count(distinct customer_id), 0) AS kpi_ppc_017,  -- Products per Customer (KPI-PPC-017), unit count
  sum(discounted_contribution_margin) AS kpi_clv_018,  -- Customer Lifetime Value (KPI-CLV-018), unit currency
  avg(attrition_model_score) AS kpi_attrisk_019,  -- Attrition Risk Score (KPI-ATTRISK-019), unit score
  (sum(ending_deposit_balance) - sum(starting_deposit_balance)) / NULLIF(sum(starting_deposit_balance), 0) * 100 AS kpi_depgrw_020  -- Deposit Balance Growth (KPI-DEPGRW-020), unit percent
FROM DP_BNK_001.V_DP_BNK_001
GROUP BY 1, 2, 3, 4, 5, 6;

-- Quality rule attachments for DP-BNK-001.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-BNK-001-01: completeness / not_null (severity critical)
ALTER TABLE DP_BNK_001.T_DP_BNK_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (customer_id);

-- QR-BNK-001-02: freshness / partition_completion_by (severity critical)
ALTER TABLE DP_BNK_001.T_DP_BNK_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-BNK-001-03: validity / in_reference_set (severity high)
ALTER TABLE DP_BNK_001.T_DP_BNK_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (segment);

-- QR-BNK-001-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_BNK_001.T_DP_BNK_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (customer_id, as_of_month);

-- QR-BNK-001-05: accuracy / reconcile_to_general_ledger (severity critical)
ALTER TABLE DP_BNK_001.T_DP_BNK_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_RECONCILE_TO_GENERAL_LEDGER ON (ending_deposit_balance);

-- QR-BNK-001-06: consistency / stable_across_months (severity medium)
ALTER TABLE DP_BNK_001.T_DP_BNK_001 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_STABLE_ACROSS_MONTHS ON (household_id);
