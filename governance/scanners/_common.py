"""Helpers shared by scanners."""

from __future__ import annotations

import logging

from governance.models import Finding, Severity

log = logging.getLogger(__name__)


def finding_from_row(
    row: dict,
    *,
    check: str,
    severity: Severity,
    resource_type: str,
    message: str,
    est_monthly_cost_usd: float | None = None,
    details: dict | None = None,
) -> Finding:
    """Build a Finding from a Resource Graph row that projects the standard columns
    (id, name, resourceGroup, subscriptionId)."""
    return Finding(
        check=check,
        severity=severity,
        resource_id=row["id"],
        resource_name=row["name"],
        resource_type=resource_type,
        resource_group=row["resourceGroup"],
        subscription_id=row["subscriptionId"],
        message=message,
        est_monthly_cost_usd=est_monthly_cost_usd,
        details=details or {},
    )


HOURS_PER_MONTH = 730


def vm_monthly_cost(clients, vm_size: str | None, region: str | None) -> float | None:
    """Linux pay-as-you-go monthly cost of a VM size, or None if unavailable."""
    if clients.prices is None or not vm_size or not region:
        return None
    try:
        hourly = clients.prices.vm_hourly_usd(vm_size, region)
    except Exception:
        log.warning("Price lookup failed for %s in %s", vm_size, region, exc_info=True)
        return None
    return round(hourly * HOURS_PER_MONTH, 2) if hourly is not None else None


def severity_for_cost(cost: float | None) -> Severity:
    """Shared cost-based severity bands, so every check ranks spend the same way."""
    if cost is None:
        return Severity.MEDIUM
    if cost >= 50:
        return Severity.HIGH
    if cost >= 10:
        return Severity.MEDIUM
    return Severity.LOW
