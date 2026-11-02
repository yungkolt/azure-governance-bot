"""Find resources missing required tags.

Ownership and cost-allocation tags (`owner`, `costCenter`) determine who pays
for a resource and who approves changes to it. Untagged spend cannot be
allocated.
"""

from __future__ import annotations

from governance.azure_clients import GraphQuery
from governance.config import Settings
from governance.models import Finding, Severity

# Resource types that are child/system objects, don't support tags well,
# or are auto-created by Azure. Flagging them is noise.
EXCLUDED_TYPES = {
    "microsoft.compute/virtualmachines/extensions",
    "microsoft.network/networkwatchers",
    "microsoft.alertsmanagement/smartdetectoralertrules",
    "microsoft.insights/actiongroups",
    "microsoft.operationsmanagement/solutions",
}

# KQL: pull id/name/type/tags for everything. Tag-key matching is done in
# Python because Azure treats tag NAMES as case-insensitive ("Owner" == "owner")
# and that's awkward in KQL. Trade-off: fine for thousands of resources; at
# very large scale you'd push the filter into KQL.
KQL = """
Resources
| project id, name, type = tolower(type), resourceGroup, subscriptionId, tags
| order by id asc
"""


def missing_tags(tags: dict | None, required: list[str]) -> list[str]:
    """Return required tag names that are absent or blank (case-insensitive)."""
    present = {k.lower() for k, v in (tags or {}).items() if str(v).strip()}
    return [t for t in required if t.lower() not in present]


def scan_untagged_resources(graph: GraphQuery, settings: Settings) -> list[Finding]:
    findings: list[Finding] = []
    for row in graph.query(KQL):
        if row["type"] in EXCLUDED_TYPES:
            continue
        missing = missing_tags(row.get("tags"), settings.required_tags)
        if not missing:
            continue
        # Missing *every* required tag = nobody owns this. Higher severity.
        severity = Severity.MEDIUM if len(missing) == len(settings.required_tags) else Severity.LOW
        findings.append(
            Finding(
                check="untagged-resource",
                severity=severity,
                resource_id=row["id"],
                resource_name=row["name"],
                resource_type=row["type"],
                resource_group=row["resourceGroup"],
                subscription_id=row["subscriptionId"],
                message=f"Missing required tags: {', '.join(missing)}",
                details={"missing_tags": missing},
            )
        )
    return findings
