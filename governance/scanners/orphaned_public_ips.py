"""Find public IP addresses not associated with anything.

A public IP is in use when it is bound to an IP configuration (a NIC, load
balancer frontend, VPN or application gateway, Bastion host) or to a NAT
gateway. Static and Standard SKU addresses bill hourly whether or not they
are associated.
"""

from __future__ import annotations

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding
from governance.scanners._common import finding_from_row, severity_for_cost

KQL = """
Resources
| where type =~ 'microsoft.network/publicipaddresses'
| where isnull(properties.ipConfiguration) and isnull(properties.natGateway)
| project id, name, resourceGroup, subscriptionId, location,
          skuName    = tostring(sku.name),
          allocation = tostring(properties.publicIPAllocationMethod),
          ipAddress  = tostring(properties.ipAddress)
"""

# Approximate list price: about $0.005 per hour for a Standard or static IPv4
# address. A Basic dynamic address releases its IP when unassociated and costs
# nothing, but is still reported as clutter.
EST_USD_PER_MONTH = 3.65


def estimate_ip_cost(sku: str | None, allocation: str | None) -> float:
    if (sku or "").lower() == "basic" and (allocation or "").lower() == "dynamic":
        return 0.0
    return EST_USD_PER_MONTH


def scan_orphaned_public_ips(clients: Clients, settings: Settings) -> list[Finding]:
    findings: list[Finding] = []
    for row in clients.graph.query(KQL):
        cost = estimate_ip_cost(row.get("skuName"), row.get("allocation"))
        findings.append(
            finding_from_row(
                row,
                check="orphaned-public-ip",
                severity=severity_for_cost(cost),
                resource_type="microsoft.network/publicipaddresses",
                message=f"Unassociated {row.get('skuName')} public IP "
                f"({row.get('allocation')}, {row.get('ipAddress') or 'no address'})",
                est_monthly_cost_usd=cost,
                details={
                    "sku": row.get("skuName"),
                    "allocation": row.get("allocation"),
                    "ip_address": row.get("ipAddress"),
                    "location": row.get("location"),
                },
            )
        )
    return findings
