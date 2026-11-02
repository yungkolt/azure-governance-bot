"""Save each scan report to Blob Storage for trend analysis.

Reports are written as `<container>/YYYY/MM/DD/<run_id>.json`, so a day's or a
month's history can be listed by prefix, and the files can be queried later
with any tool that reads JSON from storage. The Function App's managed identity
needs Storage Blob Data Contributor on the account; no keys are used.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from governance.models import ScanReport

log = logging.getLogger(__name__)


def blob_name(report: ScanReport, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now:%Y/%m/%d}/{report.run_id}.json"


def save_report(report: ScanReport, account_url: str, container: str, credential=None) -> str:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient, ContentSettings

    service = BlobServiceClient(account_url, credential=credential or DefaultAzureCredential())
    name = blob_name(report)
    service.get_container_client(container).upload_blob(
        name,
        json.dumps(report.to_dict(), indent=2),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )
    log.info("Saved report to %s/%s", container, name)
    return name
