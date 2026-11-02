from governance.models import Severity
from governance.scanners.orphaned_disks import estimate_disk_cost, scan_orphaned_disks


def test_cost_estimate():
    assert estimate_disk_cost("Premium_LRS", 512) == 69.12
    assert estimate_disk_cost("Unknown_SKU", 10) == 1.0   # falls back to default rate
    assert estimate_disk_cost(None, None) == 0.0


def test_scan_orphaned_disks(clients, settings):
    findings = scan_orphaned_disks(clients, settings)
    by_name = {f.resource_name: f for f in findings}

    assert by_name["old-vm_OsDisk"].severity == Severity.HIGH
    assert by_name["old-vm_OsDisk"].est_monthly_cost_usd == 69.12
    assert by_name["tiny-data"].severity == Severity.LOW


def test_query_only_targets_unattached(clients, graph, settings):
    scan_orphaned_disks(clients, settings)
    assert "Unattached" in graph.queries[0]
