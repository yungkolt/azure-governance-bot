"""Shared test fixtures.

FakeGraph stands in for Azure Resource Graph: it matches a distinctive string
in each scanner's KQL and returns canned rows. FakeMetrics stands in for
Azure Monitor. Tests run offline in milliseconds with no Azure account.
"""

import pytest

from governance.azure_clients import Clients, CpuStats
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

# First matching marker wins, so the more specific markers come first.
ROUTES = [
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


@pytest.fixture
def graph():
    return FakeGraph()


@pytest.fixture
def metrics():
    return FakeMetrics()


@pytest.fixture
def clients(graph, metrics):
    return Clients(graph=graph, metrics=metrics)


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
    )
