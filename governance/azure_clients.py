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
