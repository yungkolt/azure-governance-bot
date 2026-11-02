"""Find custom roles granting wildcard permissions.

A custom role with `*` in its actions is equivalent to Owner or Contributor
but is easy to miss in a review because it has an innocuous name. A
provider-wide wildcard such as `Microsoft.Compute/*` grants every current and
future action on that provider, including deletes.
"""

from __future__ import annotations

import re

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding, Severity
from governance.scanners.rbac import DEFINITIONS_KQL, load_assignments, role_guid

PROVIDER_WILDCARD = re.compile(r"^[^/*]+/\*$")   # e.g. Microsoft.Compute/*


def _list(perm: dict, key: str) -> list[str]:
    # Property casing differs between API versions ("actions" vs "Actions").
    return list(perm.get(key) or perm.get(key[0].upper() + key[1:]) or [])


def wildcard_actions(permissions: list[dict] | None) -> tuple[list[str], list[str]]:
    """Return (full wildcards, provider-wide wildcards) across actions and dataActions."""
    full, provider = [], []
    for perm in permissions or []:
        for action in _list(perm, "actions") + _list(perm, "dataActions"):
            if action == "*":
                full.append(action)
            elif PROVIDER_WILDCARD.match(action):
                provider.append(action)
    return full, provider


def scan_custom_role_wildcards(clients: Clients, settings: Settings) -> list[Finding]:
    usage: dict[str, int] = {}
    for a in load_assignments(clients):
        usage[a.role_id] = usage.get(a.role_id, 0) + 1

    findings: list[Finding] = []
    for row in clients.graph.query(DEFINITIONS_KQL):
        if (row.get("roleType") or "").lower() != "customrole":
            continue
        full, provider = wildcard_actions(row.get("permissions"))
        if not full and not provider:
            continue
        guid = role_guid(row["id"])
        assigned = usage.get(guid, 0)
        what = "all actions (*)" if full else ", ".join(sorted(set(provider)))
        findings.append(
            Finding(
                check="custom-role-wildcard",
                severity=Severity.HIGH if full else Severity.MEDIUM,
                resource_id=row["id"],
                resource_name=row.get("roleName") or guid,
                resource_type="microsoft.authorization/roledefinitions",
                resource_group="(custom role)",
                subscription_id=row.get("subscriptionId") or "",
                message=f"Custom role grants {what}; assigned {assigned} time(s)",
                details={
                    "full_wildcards": full,
                    "provider_wildcards": sorted(set(provider)),
                    "assignment_count": assigned,
                    "assignable_scopes": row.get("assignableScopes"),
                },
            )
        )
    return findings
