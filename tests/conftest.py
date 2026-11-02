"""Shared test fixtures.

FakeGraph stands in for Azure Resource Graph: it matches a distinctive string
in each scanner's KQL and returns canned rows. FakeMetrics stands in for
Azure Monitor. Tests run offline in milliseconds with no Azure account.
"""

from datetime import UTC, datetime, timedelta

import pytest

from governance.azure_clients import Clients, CostRow, CpuStats, Principal
from governance.config import Settings

SUB = "00000000-0000-0000-0000-000000000001"


def arm_id(rg: str, provider: str, name: str) -> str:
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/{provider}/{name}"


def row(rg: str, provider: str, name: str, **extra) -> dict:
    return {"id": arm_id(rg, provider, name), "name": name, "resourceGroup": rg,
            "subscriptionId": SUB, **extra}


ALL_RESOURCES = [
    {   # fully tagged -> no finding
        "id": arm_id("rg-prod", "Microsoft.Web/sites", "app-good"),
        "name": "app-good", "type": "microsoft.web/sites", "resourceGroup": "rg-prod",
        "subscriptionId": SUB,
        "tags": {"Owner": "platform-team", "Environment": "prod", "CostCenter": "IT"},
    },
    {   # no tags at all -> MEDIUM
        "id": arm_id("rg-lab", "Microsoft.Storage/storageAccounts", "stnotags"),
        "name": "stnotags", "type": "microsoft.storage/storageaccounts", "resourceGroup": "rg-lab",
        "subscriptionId": SUB, "tags": None,
    },
    {   # some tags, one blank -> LOW
        "id": arm_id("rg-lab", "Microsoft.KeyVault/vaults", "kv-partial"),
        "name": "kv-partial", "type": "microsoft.keyvault/vaults", "resourceGroup": "rg-lab",
        "subscriptionId": SUB, "tags": {"owner": "platform-team", "environment": "  "},
    },
    {   # excluded type -> ignored
        "id": arm_id("rg-lab", "Microsoft.Network/networkWatchers", "nw"),
        "name": "nw", "type": "microsoft.network/networkwatchers", "resourceGroup": "rg-lab",
        "subscriptionId": SUB, "tags": None,
    },
]

UNATTACHED_DISKS = [
    row("rg-lab", "Microsoft.Compute/disks", "old-vm_OsDisk", location="westus2", tags=None,
        skuName="Premium_LRS", sizeGb=512, timeCreated="2025-01-10T00:00:00Z"),
    row("rg-lab", "Microsoft.Compute/disks", "tiny-data", location="westus2", tags=None,
        skuName="Standard_LRS", sizeGb=32, timeCreated="2026-06-01T00:00:00Z"),
]

ORPHANED_IPS = [
    row("rg-lab", "Microsoft.Network/publicIPAddresses", "pip-standard", location="westus2",
        skuName="Standard", allocation="Static", ipAddress="20.1.2.3"),
    row("rg-lab", "Microsoft.Network/publicIPAddresses", "pip-basic-dyn", location="westus2",
        skuName="Basic", allocation="Dynamic", ipAddress=None),
]

ORPHANED_NICS = [
    row("rg-lab", "Microsoft.Network/networkInterfaces", "nic-plain", location="westus2",
        privateIp="10.0.0.4", hasPublicIp=False),
    row("rg-lab", "Microsoft.Network/networkInterfaces", "nic-with-pip", location="westus2",
        privateIp="10.0.0.5", hasPublicIp=True),
]

EMPTY_PLANS = [
    row("rg-web", "Microsoft.Web/serverfarms", "asp-p1v3", location="westus2",
        skuName="P1v3", tier="PremiumV3", instances=2, isLinux=True),
    row("rg-web", "Microsoft.Web/serverfarms", "asp-free", location="westus2",
        skuName="F1", tier="Free", instances=1, isLinux=True),
    row("rg-web", "Microsoft.Web/serverfarms", "asp-consumption", location="westus2",
        skuName="Y1", tier="Dynamic", instances=0, isLinux=True),
]

STOPPED_VMS = [
    row("rg-vm", "Microsoft.Compute/virtualMachines", "vm-stopped", location="westus2",
        powerState="PowerState/stopped", vmSize="Standard_D4s_v5"),
]

RUNNING_VMS = [
    row("rg-vm", "Microsoft.Compute/virtualMachines", "vm-idle", location="westus2",
        vmSize="Standard_D2s_v5"),
    row("rg-vm", "Microsoft.Compute/virtualMachines", "vm-busy", location="westus2",
        vmSize="Standard_D2s_v5"),
    row("rg-vm", "Microsoft.Compute/virtualMachines", "vm-nightly-batch", location="westus2",
        vmSize="Standard_D2s_v5"),
    row("rg-vm", "Microsoft.Compute/virtualMachines", "vm-new", location="westus2",
        vmSize="Standard_D2s_v5"),
    row("rg-vm", "Microsoft.Compute/virtualMachines", "vm-metrics-error", location="westus2",
        vmSize="Standard_D2s_v5"),
]

CPU = {
    "vm-idle": CpuStats(avg_percent=1.2, max_percent=8.0, hours_with_data=336),
    "vm-busy": CpuStats(avg_percent=45.0, max_percent=97.0, hours_with_data=336),
    "vm-nightly-batch": CpuStats(avg_percent=3.0, max_percent=85.0, hours_with_data=336),
    "vm-new": CpuStats(avg_percent=0.5, max_percent=2.0, hours_with_data=10),
}

# --- RBAC -------------------------------------------------------------------
SUB_SCOPE = f"/subscriptions/{SUB}"
OWNER = "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"
CONTRIBUTOR = "b24988ac-6180-42a0-ab88-20f7382dd24c"
READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
CUSTOM_VM = "11111111-1111-1111-1111-111111111111"
CUSTOM_ALL = "22222222-2222-2222-2222-222222222222"
CUSTOM_SAFE = "33333333-3333-3333-3333-333333333333"
KV_SECRETS = "4633458b-17de-408a-b874-0445c86b69e6"   # built-in, not in ARG definitions

U_ALICE = "aaaaaaaa-0000-0000-0000-000000000001"     # active user
U_GONE = "aaaaaaaa-0000-0000-0000-000000000002"      # deleted user
U_DISABLED = "aaaaaaaa-0000-0000-0000-000000000003"  # disabled user
G_OPS = "bbbbbbbb-0000-0000-0000-000000000001"       # group
SP_APP = "cccccccc-0000-0000-0000-000000000001"      # app service principal
SP_POLICY = "cccccccc-0000-0000-0000-000000000002"   # policy identity (allowlisted in a test)
FOREIGN = "dddddddd-0000-0000-0000-000000000001"     # Lighthouse group


def assignment(n, principal, ptype, scope, role):
    return {
        "id": f"{scope}/providers/Microsoft.Authorization/roleAssignments/ra-{n}",
        "subscriptionId": SUB, "principalId": principal, "principalType": ptype,
        "scope": scope,
        "roleDefinitionId": f"{SUB_SCOPE}/providers/Microsoft.Authorization/roleDefinitions/{role}",
        "createdOn": "2025-06-01T00:00:00Z",
    }


ROLE_ASSIGNMENTS = [
    assignment(1, U_ALICE, "User", SUB_SCOPE, OWNER),                       # broad HIGH
    assignment(2, G_OPS, "Group", SUB_SCOPE, CONTRIBUTOR),                  # broad MEDIUM
    assignment(3, SP_APP, "ServicePrincipal", f"{SUB_SCOPE}/resourceGroups/rg-app", OWNER),
    assignment(4, U_ALICE, "User", SUB_SCOPE, READER),                      # not privileged
    assignment(5, SP_POLICY, "ServicePrincipal", SUB_SCOPE, CONTRIBUTOR),   # broad unless allowed
    assignment(6, U_GONE, "User", SUB_SCOPE, OWNER),                        # broad + stale
    assignment(7, U_DISABLED, "User", f"{SUB_SCOPE}/resourceGroups/rg-app", READER),  # stale
    assignment(8, G_OPS, "Group", f"{SUB_SCOPE}/resourceGroups/rg-vm", CUSTOM_VM),
    assignment(9, FOREIGN, "ForeignGroup", SUB_SCOPE, CONTRIBUTOR),         # broad, not stale
    assignment(10, G_OPS, "Group",
               "/providers/Microsoft.Management/managementGroups/mg-root", CONTRIBUTOR),
    assignment(11, SP_APP, "ServicePrincipal", f"{SUB_SCOPE}/resourceGroups/rg-app", KV_SECRETS),
    assignment(1, U_ALICE, "User", SUB_SCOPE, OWNER),    # duplicate row, as ARG can return
]


def role_def(guid, name, role_type, permissions):
    return {
        "id": f"{SUB_SCOPE}/providers/Microsoft.Authorization/roleDefinitions/{guid}",
        "subscriptionId": SUB, "roleName": name, "roleType": role_type,
        "permissions": permissions, "assignableScopes": [SUB_SCOPE],
    }


ROLE_DEFINITIONS = [
    role_def(CUSTOM_ALL, "Everything Role", "CustomRole", [{"actions": ["*"], "notActions": []}]),
    role_def(CUSTOM_VM, "VM Operator Plus", "CustomRole",   # capitalised keys on purpose
             [{"Actions": ["Microsoft.Compute/*", "Microsoft.Network/virtualNetworks/read"]}]),
    role_def(CUSTOM_SAFE, "Safe Reader", "CustomRole", [{"actions": ["*/read"]}]),
    role_def(OWNER, "Owner", "BuiltInRole", [{"actions": ["*"]}]),        # built-ins ignored
]

PRINCIPALS = {
    U_ALICE: Principal(U_ALICE, "user", "Alice", "alice@contoso.com", True),
    U_DISABLED: Principal(U_DISABLED, "user", "Dan", "dan@contoso.com", False),
    G_OPS: Principal(G_OPS, "group", "Ops Team"),
    SP_APP: Principal(SP_APP, "servicePrincipal", "billing-app", "app-id-1", True),
    SP_POLICY: Principal(SP_POLICY, "servicePrincipal", "inherit-owner", "app-id-2", True),
}

# First matching marker wins, so the more specific markers come first.
ROUTES = [
    ("microsoft.authorization/roleassignments", ROLE_ASSIGNMENTS),
    ("microsoft.authorization/roledefinitions", ROLE_DEFINITIONS),
    ("PowerState/stopped", STOPPED_VMS),
    ("PowerState/running", RUNNING_VMS),
    ("microsoft.compute/disks", UNATTACHED_DISKS),
    ("microsoft.network/publicipaddresses", ORPHANED_IPS),
    ("microsoft.network/networkinterfaces", ORPHANED_NICS),
    ("microsoft.web/serverfarms", EMPTY_PLANS),
]


class FakeGraph:
    def __init__(self):
        self.queries: list[str] = []

    def query(self, kql: str) -> list[dict]:
        self.queries.append(kql)
        for marker, rows in ROUTES:
            if marker in kql:
                return rows
        return ALL_RESOURCES


class FakeMetrics:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def cpu_stats(self, resource_id: str, lookback_days: int):
        self.calls.append((resource_id, lookback_days))
        name = resource_id.rsplit("/", 1)[-1]
        if name == "vm-metrics-error":
            raise RuntimeError("metrics API unavailable")
        return CPU.get(name)


class FakeRoles:
    """Stands in for the Azure authorization API's role definition list."""

    def __init__(self, fail: bool = False):
        self.fail = fail

    def role_names(self, subscription_ids):
        if self.fail:
            raise RuntimeError("authorization API unavailable")
        return {KV_SECRETS: "Key Vault Secrets User", OWNER: "Owner"}


# --- cost and prices --------------------------------------------------------
TODAY = datetime.now(UTC).date()
LATEST = TODAY - timedelta(days=1)          # most recent complete day


def cost_series():
    rows = []
    for n in range(1, 18):                   # 17 days back, through LATEST
        day = TODAY - timedelta(days=n)
        rows.append(CostRow(day, "rg-steady", 10.0 + (n % 3) * 0.5, "USD"))   # normal wobble
        rows.append(CostRow(day, "rg-spike", 60.0 if day == LATEST else 10.0, "USD"))
        rows.append(CostRow(day, "rg-tiny", 0.5 if day == LATEST else 0.1, "USD"))  # under $5
        if day == LATEST:
            rows.append(CostRow(day, "rg-new", 20.0, "USD"))                 # brand-new spend
    rows.append(CostRow(TODAY, "rg-steady", 500.0, "USD"))   # today is partial: ignored
    return rows


class FakeCost:
    def __init__(self, rows=None):
        self.rows = cost_series() if rows is None else rows
        self.calls = []

    def daily_costs(self, subscription_id, start, end):
        self.calls.append((subscription_id, start, end))
        return [r for r in self.rows if start <= r.day <= end]


class FakePrices:
    HOURLY = {("standard_d4s_v5", "westus2"): 0.192, ("standard_d2s_v5", "westus2"): 0.096}

    def vm_hourly_usd(self, vm_size, region):
        return self.HOURLY.get((vm_size.lower(), region.lower()))


class FakeDirectory:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[list[str]] = []

    def lookup(self, ids):
        self.calls.append(list(ids))
        if self.fail:
            raise RuntimeError("Graph unavailable")
        return {i: PRINCIPALS[i] for i in ids if i in PRINCIPALS}


@pytest.fixture
def graph():
    return FakeGraph()


@pytest.fixture
def metrics():
    return FakeMetrics()


@pytest.fixture
def directory():
    return FakeDirectory()


@pytest.fixture
def clients(graph, metrics, directory):
    return Clients(graph=graph, metrics=metrics, directory=directory, roles=FakeRoles(),
                   cost=FakeCost(), prices=FakePrices())


@pytest.fixture
def settings():
    return Settings(
        subscription_ids=[SUB],
        required_tags=["owner", "environment", "costCenter"],
        teams_webhook_url=None,
        dry_run=True,
        idle_lookback_days=14,
        idle_cpu_avg=5,
        idle_cpu_max=20,
        idle_min_hours=72,
        rbac_allowed_principals=[],
        cost_baseline_days=14,
        cost_anomaly_sigma=3,
        cost_anomaly_min_usd=5,
        report_storage_url=None,
    )
