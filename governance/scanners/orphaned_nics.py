"""Find network interfaces not attached to a VM.

Unattached NICs do not bill, but they hold private IP addresses in their
subnet, can keep a public IP or NSG in use, and are usually left behind when
a VM is deleted. NICs owned by private endpoints, Private Link services or
other hosted workloads are excluded because Azure manages their lifecycle.
"""

from __future__ import annotations

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding, Severity
from governance.scanners._common import finding_from_row

KQL = """
Resources
| where type =~ 'microsoft.network/networkinterfaces'
| where isnull(properties.virtualMachine)
| where isnull(properties.privateEndpoint) and isnull(properties.privateLinkService)
| where isnull(properties.hostedWorkloads) or array_length(properties.hostedWorkloads) == 0
| project id, name, resourceGroup, subscriptionId, location,
          privateIp = tostring(properties.ipConfigurations[0].properties.privateIPAddress),
          hasPublicIp = isnotnull(properties.ipConfigurations[0].properties.publicIPAddress)
"""


def scan_orphaned_nics(clients: Clients, settings: Settings) -> list[Finding]:
    findings: list[Finding] = []
    for row in clients.graph.query(KQL):
        # A NIC still holding a public IP keeps that IP billing, so rank it higher.
        severity = Severity.MEDIUM if row.get("hasPublicIp") else Severity.LOW
        findings.append(
            finding_from_row(
                row,
                check="orphaned-nic",
                severity=severity,
                resource_type="microsoft.network/networkinterfaces",
                message="Network interface not attached to a VM"
                + (" (still holds a public IP)" if row.get("hasPublicIp") else ""),
                est_monthly_cost_usd=0.0,
                details={
                    "private_ip": row.get("privateIp"),
                    "has_public_ip": bool(row.get("hasPublicIp")),
                    "location": row.get("location"),
                },
            )
        )
    return findings
