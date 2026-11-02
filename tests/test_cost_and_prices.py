"""Tests the Cost Management parser, Retail Prices client and report history offline."""

from datetime import date

import pytest

from governance.azure_clients import RetailPrices, parse_cost_rows
from governance.reporting.history import blob_name
from governance.scanners.idle_vms import scan_idle_vms
from governance.scanners.stopped_vms import scan_stopped_vms

# --- Cost Management parsing ------------------------------------------------

def test_parses_by_column_name_in_any_order():
    rows = parse_cost_rows(
        ["UsageDate", "ResourceGroupName", "Currency", "Cost"],
        [[20261030, "rg-a", "USD", 1.25], [20261031, "", "USD", 0.5]],
    )
    assert rows[0].day == date(2026, 10, 30) and rows[0].cost == 1.25
    assert rows[1].resource_group == "(no resource group)"   # e.g. support charges


def test_accepts_pretax_cost_column():
    assert parse_cost_rows(["PreTaxCost", "UsageDate"], [[2.0, 20261101]])[0].cost == 2.0


def test_rejects_unknown_shape():
    with pytest.raises(ValueError):
        parse_cost_rows(["Foo"], [[1]])


# --- Retail Prices ----------------------------------------------------------

class StubPrices(RetailPrices):
    def __init__(self, pages):
        super().__init__()
        self.pages, self.urls = pages, []

    def _get(self, url):
        self.urls.append(url)
        return self.pages[len(self.urls) - 1]


def item(product, sku, price, unit="1 Hour"):
    return {"productName": product, "skuName": sku, "meterName": sku,
            "retailPrice": price, "unitOfMeasure": unit}


def test_picks_linux_pay_as_you_go_price():
    prices = StubPrices([{
        "Items": [
            item("Virtual Machines DSv5 Series Windows", "D4s v5", 0.376),
            item("Virtual Machines DSv5 Series", "D4s v5 Spot", 0.02),
            item("Virtual Machines DSv5 Series", "D4s v5 Low Priority", 0.04),
            item("Virtual Machines DSv5 Series", "D4s v5", 0.192),
        ],
        "NextPageLink": None,
    }])
    assert prices.vm_hourly_usd("Standard_D4s_v5", "westus2") == 0.192
    assert "armSkuName%20eq%20%27Standard_D4s_v5%27" in prices.urls[0]


def test_follows_pagination_and_caches():
    prices = StubPrices([
        {"Items": [], "NextPageLink": "https://prices.azure.com/next"},
        {"Items": [item("Virtual Machines", "B1s", 0.0104)], "NextPageLink": None},
    ])
    assert prices.vm_hourly_usd("Standard_B1s", "westus2") == 0.0104
    assert prices.vm_hourly_usd("Standard_B1s", "westus2") == 0.0104
    assert len(prices.urls) == 2                                # second call cached


def test_unknown_size_returns_none():
    assert StubPrices([{"Items": []}]).vm_hourly_usd("Standard_Nope", "westus2") is None


# --- VM pricing in findings -------------------------------------------------

def test_stopped_vm_gets_monthly_cost(clients, settings):
    finding = scan_stopped_vms(clients, settings)[0]
    assert finding.est_monthly_cost_usd == round(0.192 * 730, 2)


def test_idle_vm_gets_monthly_cost(clients, settings):
    finding = scan_idle_vms(clients, settings)[0]
    assert finding.est_monthly_cost_usd == round(0.096 * 730, 2)


def test_price_failure_leaves_cost_unset(clients, settings):
    class Broken:
        def vm_hourly_usd(self, *_):
            raise RuntimeError("prices API down")

    clients.prices = Broken()
    assert scan_stopped_vms(clients, settings)[0].est_monthly_cost_usd is None


# --- report history ---------------------------------------------------------

def test_blob_name_is_date_partitioned(clients, settings):
    from datetime import datetime

    from governance.runner import run_scan

    report = run_scan(clients, settings, notify=False)
    name = blob_name(report, now=datetime(2026, 11, 2))
    assert name == f"2026/11/02/{report.run_id}.json"


def test_runner_saves_history_when_configured(clients, settings, monkeypatch):
    saved = {}

    def fake_save(report, url, container):
        saved.update(url=url, container=container)

    monkeypatch.setattr("governance.runner.save_report", fake_save)
    settings.report_storage_url = "https://stexample.blob.core.windows.net"
    from governance.runner import run_scan

    run_scan(clients, settings, notify=False)
    assert saved == {"url": "https://stexample.blob.core.windows.net", "container": "reports"}


def test_history_failure_does_not_fail_scan(clients, settings, monkeypatch):
    def boom(*_):
        raise RuntimeError("storage down")

    monkeypatch.setattr("governance.runner.save_report", boom)
    settings.report_storage_url = "https://stexample.blob.core.windows.net"
    from governance.runner import run_scan

    assert run_scan(clients, settings, notify=False).findings


def test_azure_cost_reads_real_sdk_result_shape():
    pytest.importorskip("azure.mgmt.costmanagement")
    from azure.mgmt.costmanagement.models import QueryResult

    from governance.azure_clients import AzureCost

    result = QueryResult({"properties": {
        "columns": [{"name": "Cost", "type": "Number"}, {"name": "UsageDate", "type": "Number"},
                    {"name": "ResourceGroupName", "type": "String"},
                    {"name": "Currency", "type": "String"}],
        "rows": [[3.5, 20261030, "rg-a", "USD"]],
    }})
    cost = AzureCost(credential=object())
    sent = {}
    cost._usage = lambda scope, body: sent.update(scope=scope, body=body) or result
    rows = cost.daily_costs("sub-1", date(2026, 10, 1), date(2026, 10, 31))
    assert rows[0].cost == 3.5 and rows[0].resource_group == "rg-a"
    assert sent["scope"] == "/subscriptions/sub-1"
    assert sent["body"]["dataset"]["grouping"][0]["name"] == "ResourceGroupName"
