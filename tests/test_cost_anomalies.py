from datetime import date, timedelta

from governance.azure_clients import Clients
from governance.models import Severity
from governance.scanners.cost_anomalies import detect_anomalies, scan_cost_anomalies
from tests.conftest import LATEST, SUB, TODAY, FakeCost

D = date(2026, 10, 30)


def flat(value, days=14, end=D):
    return {end - timedelta(days=n): value for n in range(1, days + 1)}


def detect(series, **kw):
    params = {"baseline_days": 14, "sigma": 3, "min_usd": 5} | kw
    return {a.resource_group: a for a in detect_anomalies(series, D, **params)}


# --- detection logic --------------------------------------------------------

def test_spike_is_flagged():
    found = detect({"rg": flat(10.0) | {D: 40.0}})
    assert found["rg"].increase == 30.0


def test_normal_day_is_not_flagged():
    assert detect({"rg": flat(10.0) | {D: 10.5}}) == {}


def test_noisy_group_needs_a_bigger_jump():
    noisy = {D - timedelta(days=n): (5.0 if n % 2 else 25.0) for n in range(1, 15)}
    assert detect({"rg": noisy | {D: 40.0}}) == {}           # within 3 sigma of a noisy mean
    assert "rg" in detect({"rg": noisy | {D: 60.0}})


def test_small_absolute_change_ignored():
    assert detect({"rg": flat(0.10) | {D: 0.60}}) == {}      # 6x, but only $0.50


def test_new_spend():
    found = detect({"rg": {D: 25.0}})
    assert found["rg"].new_spend
    assert found["rg"].baseline_mean == 0


def test_missing_days_count_as_zero():
    sparse = {D - timedelta(days=1): 70.0}                    # one $70 day in 14
    found = detect({"rg": sparse | {D: 70.0}}, sigma=2)
    assert found["rg"].baseline_mean == 5.0


def test_min_usd_and_sigma_are_configurable():
    series = {"rg": flat(10.0) | {D: 14.0}}
    assert detect(series) == {}
    assert "rg" in detect(series, min_usd=3)


# --- scanner ----------------------------------------------------------------

def test_scanner_flags_spike_and_new_spend(clients, settings):
    found = {f.resource_name: f for f in scan_cost_anomalies(clients, settings)}
    assert set(found) == {"rg-spike", "rg-new"}
    assert found["rg-spike"].details["day"] == LATEST.isoformat()
    assert found["rg-spike"].severity == Severity.HIGH        # +$50/day = $1,500/month
    assert "6.0x" in found["rg-spike"].message
    assert "New spend" in found["rg-new"].message


def test_partial_today_is_ignored(clients, settings):
    names = {f.resource_name for f in scan_cost_anomalies(clients, settings)}
    assert "rg-steady" not in names                           # today's $500 not judged


def test_anomalies_do_not_count_as_waste(clients, settings):
    assert all(f.est_monthly_cost_usd is None for f in scan_cost_anomalies(clients, settings))


def test_requests_baseline_plus_margin(clients, settings):
    scan_cost_anomalies(clients, settings)
    sub, start, end = clients.cost.calls[0]
    assert sub == SUB and end == TODAY
    assert (end - start).days == settings.cost_baseline_days + 3


def test_no_complete_data_yet(graph, settings):
    clients = Clients(graph=graph, cost=FakeCost(rows=[]))
    assert scan_cost_anomalies(clients, settings) == []


def test_skipped_without_cost_client(graph, settings):
    assert scan_cost_anomalies(Clients(graph=graph), settings) == []
