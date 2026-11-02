"""Shared role-assignment loading for the identity and access checks.

Role assignments come from Resource Graph's `authorizationresources` table.
Role names are resolved in Python by role definition GUID, from three sources
in increasing order of authority:

1. Privileged built-in roles, mapped directly. Their GUIDs are fixed across
   every Azure tenant, so the checks work even if the other sources fail.
2. Custom role definitions returned by Resource Graph.
3. The Azure authorization API (`Clients.roles`), which also covers built-in
   roles. Resource Graph does not return built-in role definitions.

A KQL join is avoided because assignments and definitions format
`roleDefinitionId` differently and built-in roles are absent from the table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from governance.azure_clients import Clients, Principal
from governance.models import Finding, Severity

log = logging.getLogger(__name__)

ASSIGNMENTS_KQL = """
authorizationresources
| where type =~ 'microsoft.authorization/roleassignments'
| project id, subscriptionId,
          principalId      = tostring(properties.principalId),
          principalType    = tostring(properties.principalType),
          scope            = tostring(properties.scope),
          roleDefinitionId = tostring(properties.roleDefinitionId),
          createdOn        = tostring(properties.createdOn)
"""

DEFINITIONS_KQL = """
authorizationresources
| where type =~ 'microsoft.authorization/roledefinitions'
| project id, subscriptionId,
          roleName         = tostring(properties.roleName),
          roleType         = tostring(properties.type),
          permissions      = properties.permissions,
          assignableScopes = properties.assignableScopes
"""

OWNER = "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
CONTRIBUTOR = "b24988ac-6180-42a0-ab88-20f7382dd24c"
USER_ACCESS_ADMIN = "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9"
RBAC_ADMIN = "f58310d9-a9f6-439a-9e8d-f62e7b41a168"
READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"

BUILT_IN_NAMES = {
    OWNER: "Owner",
    CONTRIBUTOR: "Contributor",
    USER_ACCESS_ADMIN: "User Access Administrator",
    RBAC_ADMIN: "Role Based Access Control Administrator",
    READER: "Reader",
}

# Roles that can change resources or grant access. The last three can grant
# access to others, which is effectively full control, so they rank higher.
PRIVILEGED = {OWNER, CONTRIBUTOR, USER_ACCESS_ADMIN, RBAC_ADMIN}
ACCESS_GRANTING = {OWNER, USER_ACCESS_ADMIN, RBAC_ADMIN}

BROAD_LEVELS = {"root", "management-group", "subscription"}


@dataclass
class RoleAssignment:
    id: str
    subscription_id: str
    principal_id: str
    principal_type: str        # as recorded by ARM: User, Group, ServicePrincipal, ...
    scope: str
    role_id: str               # lowercase role definition GUID
    role_name: str
    created_on: str | None = None

    @property
    def level(self) -> str:
        return scope_level(self.scope)

    @property
    def privileged(self) -> bool:
        return self.role_id in PRIVILEGED


def role_guid(role_definition_id: str | None) -> str:
    return (role_definition_id or "").rstrip("/").rsplit("/", 1)[-1].lower()


def scope_level(scope: str | None) -> str:
    parts = [p.lower() for p in (scope or "").strip("/").split("/") if p]
    if not parts:
        return "root"
    if "managementgroups" in parts:
        return "management-group"
    if parts[0] == "subscriptions" and len(parts) == 2:
        return "subscription"
    if len(parts) == 4 and parts[2] == "resourcegroups":
        return "resource-group"
    return "resource"


def resource_group_of(scope: str | None) -> str | None:
    parts = (scope or "").strip("/").split("/")
    lowered = [p.lower() for p in parts]
    if "resourcegroups" in lowered:
        idx = lowered.index("resourcegroups")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def role_names(clients: Clients, subscription_ids: list[str]) -> dict[str, str]:
    """Role GUID -> role name. See the module docstring for the sources."""
    names = dict(BUILT_IN_NAMES)
    for row in clients.graph.query(DEFINITIONS_KQL):
        if row.get("roleName"):
            names[role_guid(row["id"])] = row["roleName"]
    if clients.roles is not None and subscription_ids:
        try:
            names.update(clients.roles.role_names(subscription_ids))
        except Exception:
            log.warning("Role definition lookup failed; some roles will show as GUIDs",
                        exc_info=True)
    return names


def load_assignments(clients: Clients) -> list[RoleAssignment]:
    # Resource Graph can return the same assignment more than once; keep one per ID.
    rows = {row["id"].lower(): row for row in clients.graph.query(ASSIGNMENTS_KQL)}.values()
    names = role_names(clients, [r["subscriptionId"] for r in rows if r.get("subscriptionId")])
    assignments = []
    for row in rows:
        guid = role_guid(row.get("roleDefinitionId"))
        assignments.append(
            RoleAssignment(
                id=row["id"],
                subscription_id=row.get("subscriptionId") or "",
                principal_id=row.get("principalId") or "",
                principal_type=row.get("principalType") or "Unknown",
                scope=row.get("scope") or "",
                role_id=guid,
                role_name=names.get(guid, guid),
                created_on=row.get("createdOn"),
            )
        )
    return assignments


def resolve_principals(clients: Clients, ids: list[str]) -> dict[str, Principal]:
    """Best-effort display names. Returns {} if no directory client or on failure."""
    if clients.directory is None or not ids:
        return {}
    try:
        return clients.directory.lookup(ids)
    except Exception:
        log.warning("Microsoft Graph lookup failed; findings will show principal IDs only",
                    exc_info=True)
        return {}


def principal_label(assignment: RoleAssignment, principal: Principal | None) -> str:
    if principal and (principal.sign_in_name or principal.display_name):
        return principal.sign_in_name or principal.display_name
    return assignment.principal_id


def assignment_finding(
    a: RoleAssignment,
    principal: Principal | None,
    *,
    check: str,
    severity: Severity,
    message: str,
    extra: dict | None = None,
) -> Finding:
    rg = resource_group_of(a.scope)
    return Finding(
        check=check,
        severity=severity,
        resource_id=a.id,
        resource_name=principal_label(a, principal),
        resource_type="microsoft.authorization/roleassignments",
        resource_group=rg or f"({a.level})",
        subscription_id=a.subscription_id,
        message=message,
        details={
            "principal_id": a.principal_id,
            "principal_type": a.principal_type,
            "principal_display_name": principal.display_name if principal else None,
            "role": a.role_name,
            "role_definition_guid": a.role_id,
            "scope": a.scope,
            "scope_level": a.level,
            "created_on": a.created_on,
            **(extra or {}),
        },
    )
