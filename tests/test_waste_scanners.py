from governance.models import Severity
from governance.scanners.empty_app_service_plans import (
    estimate_plan_cost,
    scan_empty_app_service_plans,
)
from governance.scanners.orphaned_nics import scan_orphaned_nics
from governance.scanners.orphaned_public_ips import estimate_ip_cost, scan_orphaned_public_ips
from governance.scanners.stopped_vms import scan_stopped_vms


def by_name(findings):
    return {f.resource_name: f for f in findings}


# --- public IPs -------------------------------------------------------------

def test_ip_cost_basic_dynamic_is_free():
    assert estimate_ip_cost("Basic", "Dynamic") == 0.0
    assert estimate_ip_cost("Standard", "Static") == 3.65


def test_orphaned_public_ips(clients, settings):
    found = by_name(scan_orphaned_public_ips(clients, settings))
    assert set(found) == {"pip-standard", "pip-basic-dyn"}
    assert found["pip-standard"].est_monthly_cost_usd == 3.65
    assert found["pip-standard"].severity == Severity.LOW


def test_public_ip_query_excludes_associated(clients, graph, settings):
    scan_orphaned_public_ips(clients, settings)
    kql = graph.queries[0]
    assert "isnull(properties.ipConfiguration)" in kql
    assert "isnull(properties.natGateway)" in kql


# --- NICs -------------------------------------------------------------------

def test_orphaned_nics_rank_public_ip_higher(clients, settings):
    found = by_name(scan_orphaned_nics(clients, settings))
    assert found["nic-plain"].severity == Severity.LOW
    assert found["nic-with-pip"].severity == Severity.MEDIUM
    assert "public IP" in found["nic-with-pip"].message


def test_nic_query_excludes_private_endpoints(clients, graph, settings):
    scan_orphaned_nics(clients, settings)
    assert "privateEndpoint" in graph.queries[0]


# --- App Service Plans ------------------------------------------------------

def test_plan_cost_scales_with_instances():
    assert estimate_plan_cost("P1v3", 2) == 248.20
    assert estimate_plan_cost("Unknown", None) == 50.0


def test_empty_plans_skip_free_tiers(clients, settings):
    found = by_name(scan_empty_app_service_plans(clients, settings))
    assert set(found) == {"asp-p1v3"}                  # Free and Consumption skipped
    assert found["asp-p1v3"].severity == Severity.HIGH


# --- stopped VMs ------------------------------------------------------------

def test_stopped_vms_are_high(clients, settings):
    found = by_name(scan_stopped_vms(clients, settings))
    assert found["vm-stopped"].severity == Severity.HIGH
    assert "deallocate" in found["vm-stopped"].message
