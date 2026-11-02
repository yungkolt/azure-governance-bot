"""Find VMs that are stopped but not deallocated.

Shutting a VM down from inside the guest OS, or stopping it without
deallocating, leaves the compute allocation reserved, so it keeps billing at
the full hourly rate. Only "Stop (deallocate)" in the portal or
`az vm deallocate` stops compute charges.
"""

from __future__ import annotations

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding, Severity
from governance.scanners._common import finding_from_row

# Resource Graph exposes the VM power state under properties.extended.instanceView.
KQL = """
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| extend powerState = tostring(properties.extended.instanceView.powerState.code)
| where powerState =~ 'PowerState/stopped'
| project id, name, resourceGroup, subscriptionId, location, powerState,
          vmSize = tostring(properties.hardwareProfile.vmSize)
"""


def scan_stopped_vms(clients: Clients, settings: Settings) -> list[Finding]:
    return [
        finding_from_row(
            row,
            check="stopped-not-deallocated-vm",
            # Full compute cost for zero work; cost isn't estimated because VM
            # pricing varies widely by size, region and OS (Phase 4 adds real cost).
            severity=Severity.HIGH,
            resource_type="microsoft.compute/virtualmachines",
            message=f"{row.get('vmSize')} VM is stopped but still allocated "
            "(compute is billing); deallocate it",
            details={"vm_size": row.get("vmSize"), "location": row.get("location")},
        )
        for row in clients.graph.query(KQL)
    ]
