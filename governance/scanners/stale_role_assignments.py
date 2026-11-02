"""Find role assignments held by deleted principals or disabled users.

When a user, group or service principal is deleted from Entra ID, its Azure
role assignments are not removed. The portal shows them as "Identity not
found". They grant nothing while the object is gone, but they clutter access
reviews and count toward the subscription's role-assignment limit. A disabled
user's assignments are live again the moment the account is re-enabled.

Microsoft Graph decides which principals still exist. If the Graph call fails,
this check raises instead of reporting every assignment as stale; the runner
logs the error and the other checks still report.
"""

from __future__ import annotations

import logging

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding, Severity
from governance.scanners.rbac import assignment_finding, load_assignments

log = logging.getLogger(__name__)

# Principals Graph can't resolve in this tenant by design (Azure Lighthouse,
# cross-tenant groups). Treating them as deleted would be a false positive.
SKIP_TYPES = {"foreigngroup"}


def scan_stale_role_assignments(clients: Clients, settings: Settings) -> list[Finding]:
    if clients.directory is None:
        log.info("No directory client configured; skipping stale role-assignment check")
        return []

    assignments = [
        a for a in load_assignments(clients)
        if a.principal_id and a.principal_type.lower() not in SKIP_TYPES
    ]
    principals = clients.directory.lookup([a.principal_id for a in assignments])

    findings: list[Finding] = []
    for a in assignments:
        principal = principals.get(a.principal_id)
        if principal is None:
            findings.append(assignment_finding(
                a, None,
                check="stale-role-assignment",
                severity=Severity.HIGH if a.privileged else Severity.MEDIUM,
                message=f"{a.role_name} assigned to a deleted {a.principal_type.lower()} "
                f"(identity not found); remove the assignment",
                extra={"reason": "principal-deleted"},
            ))
        elif principal.type == "user" and principal.account_enabled is False:
            findings.append(assignment_finding(
                a, principal,
                check="stale-role-assignment",
                severity=Severity.HIGH if a.privileged else Severity.MEDIUM,
                message=f"{a.role_name} held by a disabled user; access returns if the "
                "account is re-enabled",
                extra={"reason": "user-disabled"},
            ))
    return findings
