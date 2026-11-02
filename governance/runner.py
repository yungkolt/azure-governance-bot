"""Orchestrates a scan: run every scanner, build a report, send it.

Independent of Azure Functions. The CLI, the Function triggers and the test
suite all call `run_scan`, keeping trigger handlers thin.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from governance.azure_clients import GraphQuery
from governance.config import Settings
from governance.models import ScanReport
from governance.reporting.teams import post_to_teams
from governance.scanners import SCANNERS

log = logging.getLogger(__name__)


def run_scan(graph: GraphQuery, settings: Settings, notify: bool = True) -> ScanReport:
    report = ScanReport(
        run_id=str(uuid.uuid4()),
        started_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        subscriptions=settings.subscription_ids or ["<all visible>"],
    )

    for name, scanner in SCANNERS.items():
        try:
            results = scanner(graph, settings)
            log.info("%s: %d findings", name, len(results))
            report.findings.extend(results)
        except Exception:  # isolate failures so remaining scanners still report
            log.exception("Scanner %s failed", name)

    if notify and settings.teams_webhook_url:
        try:
            post_to_teams(settings.teams_webhook_url, report)
        except Exception:
            log.exception("Failed to post to Teams")

    return report
