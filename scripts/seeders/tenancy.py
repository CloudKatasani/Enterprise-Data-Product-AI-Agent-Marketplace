"""The tenant row and the parties every other seeder references.

Owners and stewards are seeded as ``party`` rows with the ids the manifests
name. A manifest that names a party id with no row fails seeding rather than
creating one implicitly: an unknown owner is a governance gap, not a typo to
paper over.
"""

from __future__ import annotations

from typing import Any

import psycopg

from scripts.seeders.parties import ORG_UNITS, PARTIES


def seed(connection: psycopg.Connection[Any], tenant: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenant (tenant_id, name, deployment_mode, residency_regions) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant_id) DO UPDATE "
            "SET name = EXCLUDED.name",
            (tenant, f"Marketplace tenant {tenant}", "multi_tenant", ["US", "EU"]),
        )
        for unit in ORG_UNITS:
            cursor.execute(
                "INSERT INTO org_unit (org_unit_id, tenant_id, name, parent_org_unit_id, "
                "cost_centre, region) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (org_unit_id) DO UPDATE SET name = EXCLUDED.name, "
                "  region = EXCLUDED.region",
                (unit["id"], tenant, unit["name"], unit["parent"], unit["cost_centre"],
                 unit["region"]),
            )
        for party in PARTIES:
            cursor.execute(
                "INSERT INTO party (party_id, tenant_id, party_type, display_name, email, "
                "org_unit_id, external_subject, mfa_enforced, active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true) "
                "ON CONFLICT (party_id) DO UPDATE SET display_name = EXCLUDED.display_name, "
                "org_unit_id = EXCLUDED.org_unit_id, mfa_enforced = EXCLUDED.mfa_enforced",
                (party["id"], tenant, party["type"], party["name"], party.get("email"),
                 party.get("org_unit"), party.get("subject"), party.get("mfa", False)),
            )
        for party in PARTIES:
            for role in party.get("roles", []):
                cursor.execute(
                    "INSERT INTO role_assignment (assignment_id, tenant_id, party_id, "
                    "role_code, scope_type, scope_id, granted_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (party_id, role_code, scope_type, scope_id) DO NOTHING",
                    (f"RA-{tenant}-{party['id']}-{role}", tenant, party["id"], role,
                     "tenant", tenant, party["id"]),
                )
    return len(PARTIES) + len(ORG_UNITS)
