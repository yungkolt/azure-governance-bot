"""Find running VMs with sustained low CPU.

Two data sources are combined:
1. Resource Graph lists running VMs (one query, all subscriptions).
2. Azure Monitor returns hourly CPU for each of those VMs.

A VM is idle when its average CPU over the lookback window is below
`idle_cpu_avg` AND it never peaked above `idle_cpu_max`. Requiring both
avoids flagging a VM that is quiet most of the day but runs a nightly batch.

CPU alone does not prove a VM is unused (a domain controller or a licence
server can be essential at 1% CPU), so these findings are recommendations to
review and right-size, not candidates for automatic action.
"""

from __future__ import annotations

import logging

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding, Severity
from governance.scanners._common import finding_from_row

log = logging.getLogger(__name__)

KQL = """
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| extend powerState = tostring(properties.extended.instanceView.powerState.code)
| where powerState =~ 'PowerState/running'
| project id, name, resourceGroup, subscriptionId, location,
          vmSize = tostring(properties.hardwareProfile.vmSize)
"""


def scan_idle_vms(clients: Clients, settings: Settings) -> list[Finding]:
    if clients.metrics is None:
        log.info("No metrics client configured; skipping idle-VM check")
        return []

    findings: list[Finding] = []
    for row in clients.graph.query(KQL):
        try:
            stats = clients.metrics.cpu_stats(row["id"], settings.idle_lookback_days)
        except Exception:  # one VM's metrics failing shouldn't stop the rest
            log.exception("Could not read CPU metrics for %s", row["id"])
            continue

        if stats is None or stats.hours_with_data < settings.idle_min_hours:
            continue  # too little history to judge
        if stats.avg_percent >= settings.idle_cpu_avg or stats.max_percent >= settings.idle_cpu_max:
            continue

        findings.append(
            finding_from_row(
                row,
                check="idle-vm",
                severity=Severity.MEDIUM,
                resource_type="microsoft.compute/virtualmachines",
                message=f"{row.get('vmSize')} VM averaged {stats.avg_percent}% CPU "
                f"(peak {stats.max_percent}%) over {settings.idle_lookback_days} days; "
                "review for shutdown or a smaller size",
                details={
                    "vm_size": row.get("vmSize"),
                    "avg_cpu_percent": stats.avg_percent,
                    "max_cpu_percent": stats.max_percent,
                    "hours_with_data": stats.hours_with_data,
                    "lookback_days": settings.idle_lookback_days,
                },
            )
        )
    return findings
