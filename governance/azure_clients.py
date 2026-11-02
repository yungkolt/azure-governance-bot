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
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

log = logging.getLogger(__name__)


class GraphQuery(Protocol):
    """Anything that can run a KQL query and return rows as dicts.

    Scanners depend on this Protocol rather than the concrete client, so tests
    inject a fake and production injects ResourceGraph.
    """

    def query(self, kql: str) -> list[dict]: ...


class ResourceGraph:
    """Real Azure Resource Graph client with paging.

    Results are cached per query string for the lifetime of the instance (one
    scan run), so scanners that share a query, such as the RBAC checks, cost one
    Resource Graph request instead of several. Resource Graph allows roughly 15
    queries per 5-second window per user.
    """

    def __init__(self, subscription_ids: list[str] | None = None, credential=None):
        # Imports inside __init__ so tests never need the Azure SDK installed.
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.resourcegraph import ResourceGraphClient

        self._credential = credential or DefaultAzureCredential()
        self._client = ResourceGraphClient(self._credential)
        self._subs = subscription_ids or None  # None = tenant scope (all visible subs)
        self._cache: dict[str, list[dict]] = {}

    def query(self, kql: str) -> list[dict]:
        if kql not in self._cache:
            self._cache[kql] = self._query(kql)
        return self._cache[kql]

    def _query(self, kql: str) -> list[dict]:
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
class Principal:
    """An Entra ID object that can hold an Azure role assignment."""

    id: str
    type: str                       # "user", "group" or "servicePrincipal"
    display_name: str | None = None
    sign_in_name: str | None = None  # UPN for users, appId for service principals
    account_enabled: bool | None = None


class DirectoryQuery(Protocol):
    """Resolves principal IDs against the directory.

    Returns found principals keyed by ID. An ID missing from the result was not
    found, which for a role assignment means the principal was deleted. Raises
    on failure, so callers never mistake an outage for "everyone was deleted".
    """

    def lookup(self, ids: list[str]) -> dict[str, Principal]: ...


class GraphDirectory:
    """Microsoft Graph client for principal lookups, using plain HTTPS.

    Two calls cover any number of principals:
    - POST /directoryObjects/getByIds (up to 1000 IDs per call) answers which
      principals still exist, with their type and display name.
    - GET /users?$filter=id in (...) (up to 15 IDs per filter) adds
      accountEnabled, which getByIds does not return by default.

    Required permission: Directory.Read.All (application permission for the
    Managed Identity; see scripts/grant-graph-permissions.sh). Locally, the
    Azure CLI's own token is used.
    """

    BASE = "https://graph.microsoft.com/v1.0"
    SCOPE = "https://graph.microsoft.com/.default"
    TYPES = {"#microsoft.graph.user": "user", "#microsoft.graph.group": "group",
             "#microsoft.graph.servicePrincipal": "servicePrincipal"}

    def __init__(self, credential=None, timeout: int = 30):
        from azure.identity import DefaultAzureCredential

        self._credential = credential or DefaultAzureCredential()
        self._timeout = timeout
        self._cache: dict[str, Principal | None] = {}  # None = looked up, not found

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        import json
        import urllib.request

        token = self._credential.get_token(self.SCOPE).token
        req = urllib.request.Request(  # noqa: S310 (fixed https base URL)
            self.BASE + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
            return json.loads(resp.read())

    def lookup(self, ids: list[str]) -> dict[str, Principal]:
        from urllib.parse import quote

        pending = sorted({i for i in ids if i} - set(self._cache))
        for chunk in _chunks(pending, 1000):
            found = self._request("POST", "/directoryObjects/getByIds", {
                "ids": chunk, "types": ["user", "group", "servicePrincipal"],
            }).get("value", [])
            by_id = {}
            for obj in found:
                by_id[obj["id"]] = Principal(
                    id=obj["id"],
                    type=self.TYPES.get(obj.get("@odata.type", ""), "unknown"),
                    display_name=obj.get("displayName"),
                    sign_in_name=obj.get("userPrincipalName") or obj.get("appId"),
                    account_enabled=obj.get("accountEnabled"),
                )
            for i in chunk:
                self._cache[i] = by_id.get(i)

        users = [p for i in pending if (p := self._cache[i]) and p.type == "user"]
        for chunk in _chunks(users, 15):
            id_list = ",".join(f"'{u.id}'" for u in chunk)
            query = quote(f"id in ({id_list})")
            rows = self._request(
                "GET", f"/users?$filter={query}&$select=id,accountEnabled"
            ).get("value", [])
            for r in rows:
                principal = self._cache.get(r["id"])
                if principal:
                    principal.account_enabled = r.get("accountEnabled")

        return {i: p for i in set(ids) if (p := self._cache.get(i))}


class RoleCatalog(Protocol):
    """Maps role definition GUIDs to names for the given subscriptions."""

    def role_names(self, subscription_ids: list[str]) -> dict[str, str]: ...


class AzureRoleCatalog:
    """Role definitions from the Azure authorization API.

    Resource Graph's authorizationresources table does not include built-in
    role definitions, so names for roles such as Key Vault Secrets User come
    from here. The list includes every built-in role plus custom roles
    assignable in each subscription, and is cached for the run.
    """

    def __init__(self, credential=None):
        from azure.identity import DefaultAzureCredential

        self._credential = credential or DefaultAzureCredential()
        self._cache: dict[str, dict[str, str]] = {}

    def role_names(self, subscription_ids: list[str]) -> dict[str, str]:
        from azure.mgmt.authorization import AuthorizationManagementClient

        names: dict[str, str] = {}
        for sub in sorted(set(subscription_ids)):
            if sub not in self._cache:
                client = AuthorizationManagementClient(self._credential, sub)
                self._cache[sub] = {
                    d.name.lower(): d.role_name
                    for d in client.role_definitions.list(scope=f"/subscriptions/{sub}")
                    if d.name and d.role_name
                }
            names.update(self._cache[sub])
        return names


@dataclass
class CostRow:
    """Actual cost for one resource group on one day."""

    day: date
    resource_group: str
    cost: float
    currency: str


class CostQuery(Protocol):
    """Daily actual cost per resource group for one subscription."""

    def daily_costs(self, subscription_id: str, start: date, end: date) -> list[CostRow]: ...


class AzureCost:
    """Azure Cost Management Query API.

    One request per subscription returns daily ActualCost grouped by resource
    group. Reader at subscription scope is enough to read cost data. The API
    is rate-limited more tightly than other ARM APIs, so the scanner makes a
    single call per subscription per run. Cost data lags usage by roughly 8 to
    24 hours, so the most recent day is usually incomplete.
    """

    COST_COLUMNS = ("Cost", "PreTaxCost", "CostUSD")

    def __init__(self, credential=None):
        from azure.identity import DefaultAzureCredential

        self._credential = credential or DefaultAzureCredential()
        self._client = None

    def _usage(self, scope: str, body: dict):
        if self._client is None:
            from azure.mgmt.costmanagement import CostManagementClient

            self._client = CostManagementClient(self._credential)
        return self._client.query.usage(scope=scope, parameters=body)

    def daily_costs(self, subscription_id: str, start: date, end: date) -> list[CostRow]:
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {"from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"},
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ResourceGroupName"}],
            },
        }
        result = self._usage(f"/subscriptions/{subscription_id}", body)
        if result is None or result.properties is None:
            return []
        props = result.properties
        if props.next_link:
            log.warning("Cost query for %s returned more rows than one page", subscription_id)
        return parse_cost_rows([c.name for c in props.columns or []], props.rows or [])


def parse_cost_rows(columns: list[str], rows: list[list]) -> list[CostRow]:
    """Parse Cost Management rows by column name; column order is not guaranteed."""
    index = {name: i for i, name in enumerate(columns)}
    cost_col = next((index[c] for c in AzureCost.COST_COLUMNS if c in index), None)
    if cost_col is None or "UsageDate" not in index:
        raise ValueError(f"Unexpected cost columns: {columns}")
    rg_col, cur_col = index.get("ResourceGroupName"), index.get("Currency")
    day_col = index["UsageDate"]
    parsed = []
    for row in rows:
        raw_day = str(int(row[day_col]))                       # 20261030 -> "20261030"
        parsed.append(CostRow(
            day=date(int(raw_day[:4]), int(raw_day[4:6]), int(raw_day[6:8])),
            resource_group=(row[rg_col] if rg_col is not None else "") or "(no resource group)",
            cost=float(row[cost_col] or 0),
            currency=row[cur_col] if cur_col is not None else "USD",
        ))
    return parsed


class PriceQuery(Protocol):
    """Pay-as-you-go list prices."""

    def vm_hourly_usd(self, vm_size: str, region: str) -> float | None: ...


class RetailPrices:
    """Azure Retail Prices API: public list prices, no authentication.

    Returns the Linux pay-as-you-go hourly price, which is the floor of what a
    VM costs: Windows licensing adds to it; reservations, savings plans and
    Azure Hybrid Benefit reduce it. Spot and Low Priority meters are excluded.
    """

    BASE = "https://prices.azure.com/api/retail/prices"
    API_VERSION = "2023-01-01-preview"
    MAX_PAGES = 5

    def __init__(self, timeout: int = 20):
        self._timeout = timeout
        self._cache: dict[tuple[str, str], float | None] = {}

    def _get(self, url: str) -> dict:
        import json
        import urllib.request

        with urllib.request.urlopen(url, timeout=self._timeout) as resp:  # noqa: S310 (fixed https)
            return json.loads(resp.read())

    def vm_hourly_usd(self, vm_size: str, region: str) -> float | None:
        from urllib.parse import quote

        key = (vm_size.lower(), region.lower())
        if key in self._cache:
            return self._cache[key]
        filt = (f"serviceName eq 'Virtual Machines' and armSkuName eq '{vm_size}' "
                f"and armRegionName eq '{region}' and priceType eq 'Consumption'")
        url = f"{self.BASE}?api-version={self.API_VERSION}&$filter={quote(filt)}"
        prices = []
        for _ in range(self.MAX_PAGES):
            page = self._get(url)
            for item in page.get("Items", []):
                names = " ".join(
                    str(item.get(k, "")) for k in ("productName", "skuName", "meterName")
                )
                if item.get("unitOfMeasure") != "1 Hour":
                    continue
                if any(word in names for word in ("Windows", "Spot", "Low Priority")):
                    continue
                prices.append(float(item["retailPrice"]))
            url = page.get("NextPageLink")
            if not url:
                break
        self._cache[key] = min(prices) if prices else None
        return self._cache[key]


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


@dataclass
class Clients:
    """Every external dependency a scanner may need, injected as one object.

    Scanners receive this container instead of constructing SDK clients
    themselves, so tests swap in fakes and new data sources are added in one
    place: Resource Graph (inventory), Azure Monitor (metrics), Microsoft
    Graph (directory), Cost Management (billed cost) and the Retail Prices
    API (list prices).
    """

    graph: GraphQuery
    metrics: MetricsQuery | None = None
    directory: DirectoryQuery | None = None
    roles: RoleCatalog | None = None
    cost: CostQuery | None = None
    prices: PriceQuery | None = None


def build_clients(subscription_ids: list[str] | None = None) -> Clients:
    """Create production clients sharing one credential."""
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    return Clients(
        graph=ResourceGraph(subscription_ids, credential=credential),
        metrics=AzureMetrics(credential=credential),
        directory=GraphDirectory(credential=credential),
        roles=AzureRoleCatalog(credential=credential),
        cost=AzureCost(credential=credential),
        prices=RetailPrices(),
    )
