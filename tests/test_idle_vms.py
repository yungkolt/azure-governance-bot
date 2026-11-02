from governance.azure_clients import Clients
from governance.scanners.idle_vms import scan_idle_vms


def test_only_truly_idle_vm_is_flagged(clients, settings):
    findings = scan_idle_vms(clients, settings)
    # vm-busy: high CPU.  vm-nightly-batch: low average but high peak.
    # vm-new: too little history.  vm-metrics-error: API failure, skipped.
    assert [f.resource_name for f in findings] == ["vm-idle"]
    assert findings[0].details["avg_cpu_percent"] == 1.2


def test_metrics_error_does_not_stop_scan(clients, metrics, settings):
    scan_idle_vms(clients, settings)
    assert len(metrics.calls) == 5    # every running VM was attempted


def test_lookback_is_passed_through(clients, metrics, settings):
    settings.idle_lookback_days = 30
    scan_idle_vms(clients, settings)
    assert all(days == 30 for _, days in metrics.calls)


def test_thresholds_are_configurable(clients, settings):
    settings.idle_cpu_max = 90          # now the nightly-batch VM counts as idle too
    names = {f.resource_name for f in scan_idle_vms(clients, settings)}
    assert names == {"vm-idle", "vm-nightly-batch"}


def test_skipped_without_metrics_client(graph, settings):
    assert scan_idle_vms(Clients(graph=graph, metrics=None), settings) == []
