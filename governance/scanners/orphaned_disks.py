"""Find managed disks not attached to any VM.

When a VM is deleted, its data disks (and often its OS disk) are retained
by default and continue to bill monthly until they are removed.
"""

from __future__ import annotations

from governance.azure_clients import GraphQuery
from governance.config import Settings
from governance.models import Finding, Severity

# diskState 'Unattached' = no VM owns it. 'Reserved' / 'ActiveSAS' are
# transitional states (e.g. VM deallocated, or a snapshot/export in progress)
# and are excluded on purpose so we don't flag disks that are in use.
KQL = """
Resources
| where type =~ 'microsoft.compute/disks'
| where properties.diskState =~ 'Unattached'
| project id, name, resourceGroup, subscriptionId, location, tags,
          skuName = tostring(sku.name),
          sizeGb  = toint(properties.diskSizeGB),
          timeCreated = tostring(properties.timeCreated)
"""

# Approximate list price in USD per GB per month, by SKU. Used only to rank
# findings. Phase 4 replaces this with the Azure Retail Prices API and actual
# billed cost from Cost Management.
EST_USD_PER_GB_MONTH = {
    "Standard_LRS": 0.045,
    "StandardSSD_LRS": 0.075,
    "StandardSSD_ZRS": 0.094,
    "Premium_LRS": 0.135,
    "Premium_ZRS": 0.169,
    "PremiumV2_LRS": 0.081,
    "UltraSSD_LRS": 0.12,
}
DEFAULT_RATE = 0.10


def estimate_disk_cost(sku: str | None, size_gb: int | None) -> float:
    rate = EST_USD_PER_GB_MONTH.get(sku or "", DEFAULT_RATE)
    return round(rate * (size_gb or 0), 2)


def scan_orphaned_disks(graph: GraphQuery, settings: Settings) -> list[Finding]:
    findings: list[Finding] = []
    for row in graph.query(KQL):
        cost = estimate_disk_cost(row.get("skuName"), row.get("sizeGb"))
        severity = Severity.HIGH if cost >= 50 else Severity.MEDIUM if cost >= 10 else Severity.LOW
        findings.append(
            Finding(
                check="orphaned-disk",
                severity=severity,
                resource_id=row["id"],
                resource_name=row["name"],
                resource_type="microsoft.compute/disks",
                resource_group=row["resourceGroup"],
                subscription_id=row["subscriptionId"],
                message=f"Unattached {row.get('skuName')} disk, {row.get('sizeGb')} GB",
                est_monthly_cost_usd=cost,
                details={
                    "sku": row.get("skuName"),
                    "size_gb": row.get("sizeGb"),
                    "location": row.get("location"),
                    "created": row.get("timeCreated"),
                },
            )
        )
    return findings
