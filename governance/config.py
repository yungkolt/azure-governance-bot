"""Configuration loaded from environment variables.

Follows the 12-factor pattern: values come from local.settings.json locally
and from App Settings (with Key Vault references for secrets) in Azure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    # Which subscriptions to scan. Empty = every subscription the identity can see.
    subscription_ids: list[str] = field(default_factory=lambda: _csv("GOV_SUBSCRIPTION_IDS"))

    # Tags every resource must have. Tune to your org's tagging standard.
    required_tags: list[str] = field(
        default_factory=lambda: _csv("GOV_REQUIRED_TAGS", "owner,environment,costCenter")
    )

    # Teams Workflows webhook URL. Store in Key Vault in production.
    teams_webhook_url: str | None = field(default_factory=lambda: os.getenv("TEAMS_WEBHOOK_URL"))

    # Report-only mode. Phase 1 never modifies resources.
    dry_run: bool = field(
        default_factory=lambda: os.getenv("GOV_DRY_RUN", "true").lower() != "false"
    )


def load_settings() -> Settings:
    return Settings()
