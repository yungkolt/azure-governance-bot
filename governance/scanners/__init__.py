"""Scanner registry.

Each scanner is a function: (clients, settings) -> list[Finding].
To add a check, write one function and add it to SCANNERS. Nothing else changes.
"""

from governance.scanners.broad_role_assignments import scan_broad_role_assignments
from governance.scanners.custom_role_wildcards import scan_custom_role_wildcards
from governance.scanners.empty_app_service_plans import scan_empty_app_service_plans
from governance.scanners.idle_vms import scan_idle_vms
from governance.scanners.orphaned_disks import scan_orphaned_disks
from governance.scanners.orphaned_nics import scan_orphaned_nics
from governance.scanners.orphaned_public_ips import scan_orphaned_public_ips
from governance.scanners.stale_role_assignments import scan_stale_role_assignments
from governance.scanners.stopped_vms import scan_stopped_vms
from governance.scanners.untagged import scan_untagged_resources

SCANNERS = {
    "untagged-resource": scan_untagged_resources,
    "orphaned-disk": scan_orphaned_disks,
    "orphaned-public-ip": scan_orphaned_public_ips,
    "orphaned-nic": scan_orphaned_nics,
    "empty-app-service-plan": scan_empty_app_service_plans,
    "stopped-not-deallocated-vm": scan_stopped_vms,
    "idle-vm": scan_idle_vms,
    "broad-role-assignment": scan_broad_role_assignments,
    "stale-role-assignment": scan_stale_role_assignments,
    "custom-role-wildcard": scan_custom_role_wildcards,
    # Phase 4: "cost-anomaly" (Cost Management API)
}

__all__ = ["SCANNERS"]
