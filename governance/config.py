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


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


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

    # Idle-VM detection: a running VM is idle when average CPU over the lookback
    # window is below IDLE_CPU_AVG and it never exceeded IDLE_CPU_MAX.
    # VMs with fewer than IDLE_MIN_HOURS of metric data are skipped so a newly
    # created VM is not flagged before it has a usage history.
    idle_lookback_days: int = field(default_factory=lambda: _int("GOV_IDLE_LOOKBACK_DAYS", 14))
    idle_cpu_avg: float = field(default_factory=lambda: _float("GOV_IDLE_CPU_AVG", 5))
    idle_cpu_max: float = field(default_factory=lambda: _float("GOV_IDLE_CPU_MAX", 20))
    idle_min_hours: int = field(default_factory=lambda: _int("GOV_IDLE_MIN_HOURS", 72))

    # Principal object IDs exempt from the broad-role-assignment check, such as
    # break-glass accounts or automation identities that need subscription scope.
    rbac_allowed_principals: list[str] = field(
        default_factory=lambda: _csv("GOV_RBAC_ALLOWED_PRINCIPALS")
    )

    # Report-only mode. The scanner never modifies resources; remediation is
    # performed by Azure Policy (see scripts/apply-policy.sh).
    dry_run: bool = field(
        default_factory=lambda: os.getenv("GOV_DRY_RUN", "true").lower() != "false"
    )


def load_settings() -> Settings:
    return Settings()
