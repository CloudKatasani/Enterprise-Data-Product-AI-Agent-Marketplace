"""Seed identities.

Owners, stewards, approvers and consumer personas referenced by the manifests.
Every ``party_id`` a manifest names must exist here: seeding fails on an unknown
owner rather than creating one, because an unknown owner is a governance gap.

Service and agent identities are separate parties (section 19): an agent holds
its own machine identity so effective access can be the intersection of the
agent's scope and the user's entitlement (I12).
"""

from __future__ import annotations

from typing import Any

# Regions are ISO-style short codes matching the residency lists on the data
# contracts. A unit whose people sit outside a product's permitted regions makes
# the request cross-border, which is a fact the policy can act on rather than a
# judgement someone has to make.
ORG_UNITS: list[dict[str, Any]] = [
    {"id": "OU-ROOT", "name": "Enterprise", "parent": None, "cost_centre": "CC-0000", "region": "US"},
    {"id": "OU-DATA", "name": "Data & Analytics", "parent": "OU-ROOT", "cost_centre": "CC-1000", "region": "US"},
    {"id": "OU-GOV", "name": "Data Governance", "parent": "OU-DATA", "cost_centre": "CC-1100", "region": "US"},
    {"id": "OU-PLAT", "name": "Data Platform", "parent": "OU-DATA", "cost_centre": "CC-1200", "region": "US"},
    {"id": "OU-SEC", "name": "Security & Privacy", "parent": "OU-ROOT", "cost_centre": "CC-2000", "region": "US"},
    {"id": "OU-TEL", "name": "Telecom Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3100", "region": "US"},
    {"id": "OU-TCH", "name": "Technology Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3200", "region": "US"},
    {"id": "OU-BNK", "name": "Banking Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3300", "region": "US"},
    {"id": "OU-INS", "name": "Insurance Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3400", "region": "EU"},
    {"id": "OU-HLT", "name": "Healthcare Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3500", "region": "US"},
    {"id": "OU-RTL", "name": "Retail Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3600", "region": "US"},
    {"id": "OU-TRN", "name": "Transportation Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3700", "region": "US"},
    {"id": "OU-UTL", "name": "Utilities & Energy Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3800", "region": "EU"},
    {"id": "OU-MFG", "name": "Manufacturing Business Unit", "parent": "OU-ROOT", "cost_centre": "CC-3900", "region": "APAC"},
]


def _person(
    party_id: str, name: str, org_unit: str, roles: list[str], *, mfa: bool = False
) -> dict[str, Any]:
    handle = name.lower().replace(" ", ".").replace("'", "")
    return {
        "id": party_id,
        "type": "person",
        "name": name,
        "email": f"{handle}@example.invalid",
        "org_unit": org_unit,
        "subject": f"oidc|{party_id.lower()}",
        "roles": roles,
        # MFA is enforced for owner, steward, architect and administrator (section 19).
        "mfa": mfa or bool({"owner", "steward", "architect", "administrator"} & set(roles)),
    }


def _team(party_id: str, name: str, org_unit: str) -> dict[str, Any]:
    return {"id": party_id, "type": "team", "name": name, "org_unit": org_unit, "roles": []}


def _agent_identity(party_id: str, name: str, org_unit: str) -> dict[str, Any]:
    return {"id": party_id, "type": "agent", "name": name, "org_unit": org_unit,
            "roles": ["consumer"]}


PARTIES: list[dict[str, Any]] = [
    # Governance and platform
    _person("PTY-0001", "Data Governance Council", "OU-GOV", ["architect", "administrator"]),
    _person("PTY-0002", "Ines Cardoso", "OU-GOV", ["architect"]),
    _person("PTY-0003", "Marcus Feld", "OU-SEC", ["security"]),
    _person("PTY-0004", "Priya Raghunathan", "OU-SEC", ["privacy"]),
    _person("PTY-0005", "Tomas Lindqvist", "OU-PLAT", ["administrator"]),
    _person("PTY-0006", "Aisha Bello", "OU-GOV", ["steward"]),
    _person("PTY-0007", "Renata Silva", "OU-GOV", ["steward"]),
    # Product and agent owners, by business unit
    _person("PTY-0031", "Elena Moreau", "OU-TEL", ["owner", "steward"]),
    _person("PTY-0032", "Karl Osei", "OU-TEL", ["owner"]),
    _person("PTY-0033", "Nadia Haddad", "OU-TCH", ["owner", "steward"]),
    _person("PTY-0034", "Diego Ferreira", "OU-BNK", ["owner", "steward"]),
    _person("PTY-0035", "Sofia Andersen", "OU-BNK", ["owner"]),
    _person("PTY-0036", "Rahul Menon", "OU-INS", ["owner", "steward"]),
    _person("PTY-0037", "Claire Dubois", "OU-INS", ["owner"]),
    _person("PTY-0038", "Amara Nwosu", "OU-HLT", ["owner", "steward"]),
    _person("PTY-0039", "Jonas Weber", "OU-HLT", ["owner"]),
    _person("PTY-0040", "Mei Tanaka", "OU-RTL", ["owner", "steward"]),
    _person("PTY-0041", "Oliver Grant", "OU-RTL", ["owner"]),
    _person("PTY-0042", "Yusuf Demir", "OU-TRN", ["owner", "steward"]),
    _person("PTY-0043", "Hanna Kovacs", "OU-UTL", ["owner", "steward"]),
    _person("PTY-0044", "Leo Almeida", "OU-TEL", ["owner"]),
    _person("PTY-0045", "Grace Okoye", "OU-UTL", ["owner"]),
    _person("PTY-0046", "Viktor Sorensen", "OU-MFG", ["owner", "steward"]),
    _person("PTY-0047", "Fatima Zahra", "OU-TCH", ["owner"]),
    _person("PTY-0048", "Daniel Ruiz", "OU-BNK", ["owner"]),
    _person("PTY-0049", "Anouk Visser", "OU-INS", ["owner"]),
    _person("PTY-0050", "Samuel Adeyemi", "OU-HLT", ["owner"]),
    _person("PTY-0051", "Ingrid Solberg", "OU-RTL", ["owner"]),
    _person("PTY-0052", "Chen Wei", "OU-TRN", ["owner"]),
    _person("PTY-0053", "Marta Nowak", "OU-MFG", ["owner"]),
    # Consumer personas used by the entitlement evaluation suite and the e2e journey
    _person("PTY-0061", "Rosa Iglesias", "OU-TEL", ["consumer"]),
    _person("PTY-0062", "Ben Coulter", "OU-RTL", ["consumer"]),
    _person("PTY-0063", "Nour Khalil", "OU-BNK", ["consumer"]),
    _person("PTY-0064", "Peter Lindgren", "OU-HLT", ["consumer"]),
    _person("PTY-0065", "Aditi Sharma", "OU-INS", ["consumer"]),
    # Teams named as escalation targets
    _team("PTY-0101", "Telecom Customer Domain", "OU-TEL"),
    _team("PTY-0102", "Telecom Network Domain", "OU-TEL"),
    _team("PTY-0103", "Product Analytics", "OU-TCH"),
    _team("PTY-0104", "Banking Customer Domain", "OU-BNK"),
    _team("PTY-0105", "Financial Crime Operations", "OU-BNK"),
    _team("PTY-0106", "Claims Analytics", "OU-INS"),
    _team("PTY-0107", "Underwriting Analytics", "OU-INS"),
    _team("PTY-0108", "Clinical Informatics", "OU-HLT"),
    _team("PTY-0109", "Pharmacy Operations", "OU-HLT"),
    _team("PTY-0110", "Merchandising Analytics", "OU-RTL"),
    _team("PTY-0111", "Supply Chain Planning", "OU-RTL"),
    _team("PTY-0112", "Fleet Operations", "OU-TRN"),
    _team("PTY-0113", "Grid Operations", "OU-UTL"),
    _team("PTY-0114", "Manufacturing Excellence", "OU-MFG"),
]

# One machine identity per seed agent (section 19). The agent_id is derivable
# from the party id so the audit trail reads without a lookup.
AGENT_IDENTITIES: list[tuple[str, str]] = [
    ("AG-TEL-001", "Churn Sentinel"),
    ("AG-TEL-002", "Network Quality Advisor"),
    ("AG-TCH-001", "Product Adoption Analyst"),
    ("AG-BNK-001", "Relationship Value Advisor"),
    ("AG-BNK-002", "Financial Crime Triage"),
    ("AG-INS-001", "Claims Leakage Investigator"),
    ("AG-INS-002", "Underwriting Portfolio Copilot"),
    ("AG-HLT-001", "Readmission Risk Navigator"),
    ("AG-HLT-002", "Pharmacy Utilization Agent"),
    ("AG-RTL-001", "Merchandising Performance Agent"),
    ("AG-RTL-002", "Inventory Availability Agent"),
    ("AG-TRN-001", "Delivery SLA Sentinel"),
    ("AG-UTL-001", "Outage Impact Analyst"),
    ("AG-MFG-001", "Yield & Downtime Analyst"),
    ("AG-ENG-001", "Load & Demand Analyst"),
    ("AG-BNK-003", "Cross-Hold Analyst"),
    ("AG-HLT-003", "Care Access & Adherence Analyst"),
    ("AG-INS-003", "Underwriting Result Analyst"),
    ("AG-RTL-003", "Trading Margin Analyst"),
    ("AG-TCH-002", "Account Retention Analyst"),
    ("AG-TEL-003", "Subscriber Experience Analyst"),
    ("AG-TRN-002", "Fleet Utilisation Analyst"),
    ("AG-UTL-002", "Restoration Performance Analyst"),
    ("AG-BNK-004", "Credit Portfolio Analyst"),
    ("AG-TCH-003", "Service Reliability Analyst"),
    ("AG-TRN-003", "Freight Cost Analyst"),
    ("AG-MFG-002", "Supplier Quality Analyst"),
    ("AG-HLT-004", "Care Capacity Analyst"),
    ("AG-INS-004", "Policyholder Relationship Analyst"),
    ("AG-MFG-003", "Equipment Reliability Analyst"),
]

ORG_UNIT_FOR_INDUSTRY = {
    "TEL": "OU-TEL",
    "TCH": "OU-TCH",
    "BNK": "OU-BNK",
    "INS": "OU-INS",
    "HLT": "OU-HLT",
    "RTL": "OU-RTL",
    "TRN": "OU-TRN",
    "UTL": "OU-UTL",
    "ENG": "OU-UTL",
    "MFG": "OU-MFG",
}

PARTIES.extend(
    _agent_identity(
        f"PTY-9{index:03d}",
        f"{name} (machine identity)",
        ORG_UNIT_FOR_INDUSTRY[agent_id.split("-")[1]],
    )
    for index, (agent_id, name) in enumerate(AGENT_IDENTITIES, start=1)
)


def machine_party_for(agent_id: str) -> str:
    """The party id holding an agent's machine identity."""
    for index, (candidate, _) in enumerate(AGENT_IDENTITIES, start=1):
        if candidate == agent_id:
            return f"PTY-9{index:03d}"
    raise KeyError(f"no machine identity seeded for {agent_id}")
