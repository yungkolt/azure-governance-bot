"""Tests AzureMetrics' parsing of the ARM metrics response without calling Azure.

The SDK client is replaced with a stub returning objects shaped like
azure.mgmt.monitor.models.Response -> Metric -> TimeSeriesElement -> MetricValue.
"""

from types import SimpleNamespace as NS

import pytest

pytest.importorskip("azure.identity")

from governance.azure_clients import AzureMetrics  # noqa: E402

VM_ID = ("/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg"
         "/providers/Microsoft.Compute/virtualMachines/vm1")


class StubMetricsOps:
    def __init__(self, points):
        self.points = points
        self.kwargs = None

    def list(self, resource_uri, **kwargs):
        self.kwargs = {"resource_uri": resource_uri, **kwargs}
        return NS(value=[NS(timeseries=[NS(data=self.points)])])


def metrics_with(points):
    m = AzureMetrics(credential=object())
    ops = StubMetricsOps(points)
    m._client = lambda _sub: NS(metrics=ops)
    return m, ops


def test_averages_and_peak():
    m, _ = metrics_with([NS(average=2.0, maximum=10.0), NS(average=4.0, maximum=30.0)])
    stats = m.cpu_stats(VM_ID, 14)
    assert (stats.avg_percent, stats.max_percent, stats.hours_with_data) == (3.0, 30.0, 2)


def test_gaps_are_ignored():
    m, _ = metrics_with([NS(average=None, maximum=None), NS(average=1.0, maximum=None)])
    stats = m.cpu_stats(VM_ID, 14)
    assert stats.hours_with_data == 1
    assert stats.max_percent == 1.0      # falls back to averages when no maxima


def test_no_data_returns_none():
    m, _ = metrics_with([])
    assert m.cpu_stats(VM_ID, 14) is None


def test_request_parameters():
    m, ops = metrics_with([NS(average=1.0, maximum=1.0)])
    m.cpu_stats(VM_ID, 7)
    assert ops.kwargs["metricnames"] == "Percentage CPU"
    assert ops.kwargs["interval"] == "PT1H"
    assert ops.kwargs["aggregation"] == "Average,Maximum"
    start, end = ops.kwargs["timespan"].split("/")
    assert start < end
