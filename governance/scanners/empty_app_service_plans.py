"""Find App Service Plans with no apps.

A dedicated App Service Plan bills for its instances whether or not any app
runs on it. Free, Consumption (Dynamic) and Flex Consumption plans cost
nothing when empty and are excluded.
"""

from __future__ import annotations

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding
from governance.scanners._common import finding_from_row, severity_for_cost

FREE_TIERS = {"free", "dynamic", "flexconsumption"}

KQL = """
Resources
| where type =~ 'microsoft.web/serverfarms'
| where toint(properties.numberOfSites) == 0
| project id, name, resourceGroup, subscriptionId, location,
          skuName   = tostring(sku.name),
          tier      = tostring(sku.tier),
          instances = toint(sku.capacity),
          isLinux   = tobool(properties.reserved)
"""

# Approximate list price per instance per month (Linux). Windows is higher;
# this table is only used to rank findings.
EST_USD_PER_INSTANCE_MONTH = {
    "B1": 13.14, "B2": 26.28, "B3": 52.56,
    "S1": 69.35, "S2": 138.70, "S3": 277.40,
    "P0v3": 62.05, "P1v3": 124.10, "P2v3": 248.20, "P3v3": 496.40,
    "P1mv3": 149.65, "P2mv3": 299.30,
}
DEFAULT_PER_INSTANCE = 50.0


def estimate_plan_cost(sku: str | None, instances: int | None) -> float:
    rate = EST_USD_PER_INSTANCE_MONTH.get(sku or "", DEFAULT_PER_INSTANCE)
    return round(rate * max(instances or 1, 1), 2)


def scan_empty_app_service_plans(clients: Clients, settings: Settings) -> list[Finding]:
    findings: list[Finding] = []
    for row in clients.graph.query(KQL):
        if (row.get("tier") or "").lower() in FREE_TIERS:
            continue
        cost = estimate_plan_cost(row.get("skuName"), row.get("instances"))
        findings.append(
            finding_from_row(
                row,
                check="empty-app-service-plan",
                severity=severity_for_cost(cost),
                resource_type="microsoft.web/serverfarms",
                message=f"{row.get('skuName')} plan with {row.get('instances') or 1} "
                "instance(s) and no apps",
                est_monthly_cost_usd=cost,
                details={
                    "sku": row.get("skuName"),
                    "tier": row.get("tier"),
                    "instances": row.get("instances"),
                    "linux": bool(row.get("isLinux")),
                    "location": row.get("location"),
                },
            )
        )
    return findings
