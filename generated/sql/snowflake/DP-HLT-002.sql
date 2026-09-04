-- AUTO-GENERATED FROM manifests/products/DP-HLT-002.yaml BY scripts/gen.py — DO NOT EDIT
-- generator_version: 1.0.0  manifest_hash: 6b3bdcc61fdf1bdb94713ea967b74622e853f598a88b9678a925458dc60bbc6c  generated_at: 2026-09-04T02:50:43+00:00

-- Governed consumption view for DP-HLT-002 — Pharmacy & Clinical Supply Utilization
-- contract 1.8.0, max sensitivity confidential, contains PII: false
-- grain: one row per item per location per day
--
-- Row and column policy is enforced by the platform, never by the caller.
CREATE OR REPLACE VIEW DP_HLT_002.V_DP_HLT_002 AS
SELECT
  item_id,
  facility,
  activity_date,
  therapeutic_class,
  item_class,
  service_line,
  on_formulary,
  substitution_eligible,
  substituted,
  on_hand_units,
  demand_units,
  dispensed_cost,
  wasted_cost,
  patient_days,
  days_to_expiry,
  reorder_point
FROM DP_HLT_002.T_DP_HLT_002;

-- Column masking, applied in the platform.

-- Purpose binding is mandatory above Internal; the row access policy
-- reads the session purpose set by the gateway and fails closed.
ALTER TABLE DP_HLT_002.T_DP_HLT_002 ADD ROW ACCESS POLICY GOVERNANCE.PURPOSE_BOUND ON (ALL);

-- Semantic view for DP-HLT-002 — one measure per certified KPI.
-- Each measure is written exactly once, from the KPI manifest, so a re-derived
-- figure can cite the certified definition rather than approximate it.
CREATE OR REPLACE VIEW DP_HLT_002.SV_DP_HLT_002 AS
SELECT
  facility,
  activity_date,
  item_class,
  service_line,
  on_formulary,
  (count(*) filter (where on_formulary)) / NULLIF(count(*), 0) * 100 AS kpi_formadh_041,  -- Formulary Adherence (KPI-FORMADH-041), unit percent
  (count(*) filter (where on_hand_units = 0 and demand_units > 0)) / NULLIF(count(*), 0) * 100 AS kpi_stockout_042,  -- Pharmacy Stockout Rate (KPI-STOCKOUT-042), unit percent
  (sum(dispensed_cost)) / NULLIF(sum(patient_days), 0) AS kpi_costppd_043,  -- Pharmacy Cost per Patient Day (KPI-COSTPPD-043), unit currency
  (sum(wasted_cost)) / NULLIF(sum(dispensed_cost), 0) * 100 AS kpi_waste_044,  -- Pharmacy Waste Rate (KPI-WASTE-044), unit percent
  (count(*) filter (where substituted)) / NULLIF(count(*) filter (where substitution_eligible), 0) * 100 AS kpi_subst_045  -- Therapeutic Substitution Rate (KPI-SUBST-045), unit percent
FROM DP_HLT_002.V_DP_HLT_002
GROUP BY 1, 2, 3, 4, 5;

-- Quality rule attachments for DP-HLT-002.
-- Results land in quality_result and are the evidence a composite is computed from.

-- QR-HLT-002-01: completeness / not_null (severity critical)
ALTER TABLE DP_HLT_002.T_DP_HLT_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_NOT_NULL ON (item_id);

-- QR-HLT-002-02: freshness / partition_completion_by (severity high)
ALTER TABLE DP_HLT_002.T_DP_HLT_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_PARTITION_COMPLETION_BY ON (*);

-- QR-HLT-002-03: validity / in_reference_set (severity high)
ALTER TABLE DP_HLT_002.T_DP_HLT_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IN_REFERENCE_SET ON (therapeutic_class);

-- QR-HLT-002-04: uniqueness / unique_at_grain (severity critical)
ALTER TABLE DP_HLT_002.T_DP_HLT_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_UNIQUE_AT_GRAIN ON (item_id, facility, activity_date);

-- QR-HLT-002-05: consistency / implies_substitution_eligible (severity high)
ALTER TABLE DP_HLT_002.T_DP_HLT_002 ADD DATA METRIC FUNCTION GOVERNANCE.DMF_IMPLIES_SUBSTITUTION_ELIGIBLE ON (substituted);
