"""Post a scan summary to Microsoft Teams as an Adaptive Card.

Teams note: the old "Office 365 Connectors / Incoming Webhook" is being
retired. The current way is a Teams *Workflow* (Power Automate) using the
"When a Teams webhook request is received" trigger, which gives you a URL.
It expects the {"type": "message", "attachments": [adaptive card]} shape below.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from governance.models import ScanReport

log = logging.getLogger(__name__)

CHECK_LABELS = {
    "untagged-resource": "Untagged resources",
    "orphaned-disk": "Orphaned disks",
    "orphaned-public-ip": "Orphaned public IPs",
    "orphaned-nic": "Orphaned NICs",
    "empty-app-service-plan": "Empty App Service Plans",
    "stopped-not-deallocated-vm": "Stopped (still billing) VMs",
    "idle-vm": "Idle VMs",
    "broad-role-assignment": "Broad privileged roles",
    "stale-role-assignment": "Stale role assignments",
    "custom-role-wildcard": "Wildcard custom roles",
}
TOP_N = 5  # full detail is in the JSON report


def build_card(report: ScanReport) -> dict:
    groups = report.by_check()
    facts = [
        {"title": CHECK_LABELS.get(check, check), "value": str(len(items))}
        for check, items in sorted(groups.items())
    ]
    waste = f"${report.total_est_monthly_waste:,.2f}"
    facts.append({"title": "Est. monthly waste", "value": waste})

    # Highest estimated cost first.
    top = sorted(report.findings, key=lambda f: f.est_monthly_cost_usd or 0, reverse=True)[:TOP_N]
    top_lines = []
    for f in top:
        cost = f" - ~${f.est_monthly_cost_usd:,.2f}/mo" if f.est_monthly_cost_usd else ""
        top_lines.append({
            "type": "TextBlock", "wrap": True, "spacing": "Small",
            "text": f"**{f.resource_name}** ({f.resource_group}) - {f.message}{cost}",
        })

    body = [
        {"type": "TextBlock", "size": "Large", "weight": "Bolder",
         "text": "Azure Governance Report"},
        {"type": "TextBlock", "isSubtle": True, "spacing": "None",
         "text": f"Run {report.run_id[:8]} - {report.started_at}"},
        {"type": "FactSet", "facts": facts},
    ]
    if top_lines:
        body.append({"type": "TextBlock", "weight": "Bolder", "text": "Top findings",
                     "spacing": "Medium"})
        body.extend(top_lines)
    else:
        body.append({"type": "TextBlock", "text": "No findings. Clean environment."})

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body,
                },
            }
        ],
    }


def post_to_teams(webhook_url: str, report: ScanReport, timeout: int = 15) -> int:
    # Only allow https: blocks file:// or other schemes if config is ever tampered with.
    if not webhook_url.lower().startswith("https://"):
        raise ValueError("Teams webhook URL must use https://")
    payload = json.dumps(build_card(report)).encode()
    # noqa S310: scheme validated above
    req = urllib.request.Request(  # noqa: S310
        webhook_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        log.info("Teams webhook responded %s", resp.status)
        return resp.status
