"""Scanner registry.

Each scanner is a function: (graph, settings) -> list[Finding].
To add a check, write one function and add it to SCANNERS. Nothing else changes.
"""

from governance.scanners.orphaned_disks import scan_orphaned_disks
from governance.scanners.untagged import scan_untagged_resources

SCANNERS = {
    "untagged-resource": scan_untagged_resources,
    "orphaned-disk": scan_orphaned_disks,
    # Phase 2: "idle-resource", "orphaned-public-ip", "orphaned-nic"
    # Phase 3: "broad-role-assignment" (uses Microsoft Graph too)
    # Phase 4: "cost-anomaly" (uses Cost Management API)
}

__all__ = ["SCANNERS"]
