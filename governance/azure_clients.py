"""Thin wrappers around the Azure SDK.

Inventory is read from Azure Resource Graph (ARG) rather than by enumerating
subscriptions and resource groups through ARM. A single KQL query covers all
in-scope subscriptions and is served from an index, avoiding thousands of
throttled ARM calls. Queries can be prototyped in Resource Graph Explorer.

Authentication uses DefaultAzureCredential, which resolves environment
variables, Managed Identity, then Azure CLI credentials. The same code runs
locally (`az login`) and in Azure Functions (Managed Identity) with no secrets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

log = logging.getLogger(__name__)


class GraphQuery(Protocol):
    """Anything that can run a KQL query and return rows as dicts.

    Scanners depend on this Protocol rather than the concrete client, so tests
    inject a fake and production injects ResourceGraph.
    """

    def query(self, kql: str) -> list[dict]: ...


class ResourceGraph:
    """Real Azure Resource Graph client with paging."""

    def __init__(self, subscription_ids: list[str] | None = None, credential=None):
        # Imports inside __init__ so tests never need the Azure SDK installed.
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.resourcegraph import ResourceGraphClient

        self._credential = credential or DefaultAzureCredential()
        self._client = ResourceGraphClient(self._credential)
        self._subs = subscription_ids or None  # None = tenant scope (all visible subs)

    def query(self, kql: str) -> list[dict]:
        from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

        rows: list[dict] = []
        skip_token = None
        while True:
            req = QueryRequest(
                subscriptions=self._subs,
                query=kql,
                options=QueryRequestOptions(
                    result_format="objectArray", top=1000, skip_token=skip_token
                ),
            )
            resp = self._client.resources(req)
            rows.extend(resp.data)
            skip_token = resp.skip_token
            if not skip_token:  # ARG pages at 1000 rows; keep going until done
                break
        log.info("ARG query returned %d rows", len(rows))
        return rows


@dataclass
class CpuStats:
    """CPU summary for one VM over the lookback window."""

    avg_percent: float
    max_percent: float
    hours_with_data: int


class MetricsQuery(Protocol):
    """Anything that can summarise a VM's CPU over a lookback window."""

    def cpu_stats(self, resource_id: str, lookback_days: int) -> CpuStats | None: ...


class AzureMetrics:
    """Azure Monitor platform metrics via the ARM metrics API.

    Uses azure-mgmt-monitor rather than azure-monitor-query: metrics support
    was removed from azure-monitor-query 2.0. Platform metrics such as
    "Percentage CPU" are collected for every VM automatically, with no agent,
    and reading them is covered by the built-in Reader role.
    """

    def __init__(self, credential=None):
        from azure.identity import DefaultAzureCredential

        self._credential = credential or DefaultAzureCredential()
        self._clients: dict = {}  # one MonitorManagementClient per subscription

    def _client(self, subscription_id: str):
        from azure.mgmt.monitor import MonitorManagementClient

        if subscription_id not in self._clients:
            self._clients[subscription_id] = MonitorManagementClient(
                self._credential, subscription_id
            )
        return self._clients[subscription_id]

    def cpu_stats(self, resource_id: str, lookback_days: int) -> CpuStats | None:
        subscription_id = resource_id.split("/")[2]
        end = datetime.now(UTC)
        start = end - timedelta(days=lookback_days)
        resp = self._client(subscription_id).metrics.list(
            resource_id,
            timespan=f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
            interval="PT1H",
            metricnames="Percentage CPU",
            aggregation="Average,Maximum",
        )
        averages: list[float] = []
        maxima: list[float] = []
        for metric in resp.value:
            for series in metric.timeseries or []:
                for point in series.data or []:
                    if point.average is not None:
                        averages.append(point.average)
                    if point.maximum is not None:
                        maxima.append(point.maximum)
        if not averages:
            return None
        return CpuStats(
            avg_percent=round(sum(averages) / len(averages), 2),
            max_percent=round(max(maxima or averages), 2),
            hours_with_data=len(averages),
        )


@dataclass
class Clients:
    """Every external dependency a scanner may need, injected as one object.

    Scanners receive this container instead of constructing SDK clients
    themselves, so tests swap in fakes and new data sources (Microsoft Graph,
    Cost Management) are added in one place.
    """

    graph: GraphQuery
    metrics: MetricsQuery | None = None


def build_clients(subscription_ids: list[str] | None = None) -> Clients:
    """Create production clients sharing one credential."""
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    return Clients(
        graph=ResourceGraph(subscription_ids, credential=credential),
        metrics=AzureMetrics(credential=credential),
    )
