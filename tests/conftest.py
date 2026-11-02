"""Shared test fixtures.

FakeGraph stands in for Azure Resource Graph. It inspects the KQL text and
returns canned rows, so tests run in milliseconds with no Azure account.
"""

import pytest

from governance.config import Settings

SUB = "00000000-0000-0000-0000-000000000001"


def arm_id(rg: str, provider: str, name: str) -> str:
    return f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/{provider}/{name}"


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
    {
        "id": arm_id("rg-lab", "Microsoft.Compute/disks", "old-vm_OsDisk"),
        "name": "old-vm_OsDisk", "resourceGroup": "rg-lab", "subscriptionId": SUB,
        "location": "westus2", "tags": None, "skuName": "Premium_LRS", "sizeGb": 512,
        "timeCreated": "2025-01-10T00:00:00Z",
    },
    {
        "id": arm_id("rg-lab", "Microsoft.Compute/disks", "tiny-data"),
        "name": "tiny-data", "resourceGroup": "rg-lab", "subscriptionId": SUB,
        "location": "westus2", "tags": None, "skuName": "Standard_LRS", "sizeGb": 32,
        "timeCreated": "2026-06-01T00:00:00Z",
    },
]


class FakeGraph:
    def __init__(self):
        self.queries: list[str] = []

    def query(self, kql: str) -> list[dict]:
        self.queries.append(kql)
        if "microsoft.compute/disks" in kql:
            return UNATTACHED_DISKS
        return ALL_RESOURCES


@pytest.fixture
def graph():
    return FakeGraph()


@pytest.fixture
def settings():
    return Settings(
        subscription_ids=[SUB],
        required_tags=["owner", "environment", "costCenter"],
        teams_webhook_url=None,
        dry_run=True,
    )
