"""Find privileged roles assigned at broad scope.

Owner, Contributor, User Access Administrator and Role Based Access Control
Administrator at subscription, management-group or root scope give control
over everything underneath. Least privilege means granting these at the
narrowest scope that works, to groups rather than individual users, and
ideally as just-in-time Privileged Identity Management (PIM) eligibility
rather than a standing assignment.

Access-granting roles constrained by a role assignment condition, for example
an RBAC Administrator that may only grant Reader, are still reported but at
medium severity: the holder can't grant itself or others arbitrary access.

Principals that legitimately need broad access, such as break-glass accounts
or automation identities, are exempted with GOV_RBAC_ALLOWED_PRINCIPALS.
"""

from __future__ import annotations

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding, Severity
from governance.scanners.rbac import (
    ACCESS_GRANTING,
    BROAD_LEVELS,
    assignment_finding,
    load_assignments,
    resolve_principals,
)


def scan_broad_role_assignments(clients: Clients, settings: Settings) -> list[Finding]:
    allowed = {p.lower() for p in settings.rbac_allowed_principals}
    broad = [
        a for a in load_assignments(clients)
        if a.privileged and a.level in BROAD_LEVELS and a.principal_id.lower() not in allowed
    ]
    principals = resolve_principals(clients, [a.principal_id for a in broad])

    findings: list[Finding] = []
    for a in broad:
        direct_user = a.principal_type.lower() == "user"
        access_granting = a.role_id in ACCESS_GRANTING
        message = f"{a.role_name} at {a.level} scope"
        if access_granting and a.conditional:
            message += "; constrained by a role assignment condition"
        if direct_user:
            message += "; assigned directly to a user (prefer a group or PIM eligibility)"
        high = access_granting and not a.conditional
        findings.append(
            assignment_finding(
                a,
                principals.get(a.principal_id),
                check="broad-role-assignment",
                severity=Severity.HIGH if high else Severity.MEDIUM,
                message=message,
                extra={"direct_user_assignment": direct_user},
            )
        )
    return findings
