-- AUTO-GENERATED FROM manifests/products/DP-BNK-003.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 8582ee023574045c153f6206c9f567f1bd8bf26f280d60891b3220444572dc41  generated_at: 2026-09-04T21:46:00+00:00

-- Governed consumption view for DP-BNK-003 — Lending & Credit Portfolio
-- contract 1.0.0, max sensitivity restricted, contains PII: true
-- grain: one row per loan account per month
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_BNK_003.V_DP_BNK_003 AS
SELECT
  loan_id,
  customer_id,  -- masking policy MASK_PII attached below
  as_of_month,
  product_type,
  region,
  segment,
  channel,
  risk_grade,
  vintage_band,
  origination_date,
  outstanding_balance,
  original_balance,
  interest_income,
  days_past_due,
  delinquent_30d,
  defaulted,
  charged_off_amount,
  provision_amount,
  collateral_value,
  bureau_score  -- masking policy MASK_PII attached below
FROM DP_BNK_003.T_DP_BNK_003;

-- Column masking, applied in the platform.
ALTER TABLE DP_BNK_003.T_DP_BNK_003 MODIFY COLUMN customer_id SET MASKING POLICY GOVERNANCE.MASK_PII;
ALTER TABLE DP_BNK_003.T_DP_BNK_003 MODIFY COLUMN bureau_score SET MASKING POLICY GOVERNANCE.MASK_PII;

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_BNK_003.T_DP_BNK_003 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-BNK-003 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_BNK_003.SV_DP_BNK_003 AS
SELECT
  as_of_month,
  product_type,
  segment,
  channel,
  vintage_band,
  origination_date,
  (sum(interest_income) * 12) / NULLIF(sum(outstanding_balance), 0) * 100 AS kpi_portyield_078,  -- Portfolio Yield (KPI-PORTYIELD-078), unit percent
  (count(distinct loan_id) filter (where delinquent_30d)) / NULLIF(count(distinct loan_id), 0) * 100 AS kpi_delinq_079,  -- 30+ Delinquency Rate (KPI-DELINQ-079), unit percent
  (sum(outstanding_balance) filter (where defaulted)) / NULLIF(sum(outstanding_balance), 0) * 100 AS kpi_npl_080,  -- Non-Performing Loan Ratio (KPI-NPL-080), unit percent
  (sum(provision_amount)) / NULLIF(sum(outstanding_balance) filter (where defaulted), 0) * 100 AS kpi_provcov_081,  -- Provision Coverage (KPI-PROVCOV-081), unit percent
  (sum(outstanding_balance) filter (where collateral_value > 0)) / NULLIF(sum(collateral_value), 0) * 100 AS kpi_ltv_082  -- Average Loan to Value (KPI-LTV-082), unit percent
FROM DP_BNK_003.V_DP_BNK_003
GROUP BY 1, 2, 3, 4, 5, 6;

-- Quality rule attachments for DP-BNK-003.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-BNK-003-01: completeness / not_null (severity critical)
ALTER TABLE DP_BNK_003.T_DP_BNK_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (loan_id);

-- QR-BNK-003-02: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_BNK_003.T_DP_BNK_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (loan_id, as_of_month);

-- QR-BNK-003-03: freshness / partition_completion_by (severity critical)
ALTER TABLE DP_BNK_003.T_DP_BNK_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-BNK-003-04: validity / in_reference_set (severity high)
ALTER TABLE DP_BNK_003.T_DP_BNK_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (product_type);

-- QR-BNK-003-05: consistency / non_negative (severity critical)
ALTER TABLE DP_BNK_003.T_DP_BNK_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NON_NEGATIVE ON (outstanding_balance);

-- QR-BNK-003-06: accuracy / reconciles_to_source (severity critical)
ALTER TABLE DP_BNK_003.T_DP_BNK_003 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_RECONCILES_TO_SOURCE ON (interest_income);
