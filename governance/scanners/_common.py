"""Helpers shared by scanners."""

from __future__ import annotations

from governance.models import Finding, Severity


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


def severity_for_cost(cost: float | None) -> Severity:
    """Shared cost-based severity bands, so every check ranks spend the same way."""
    if cost is None:
        return Severity.MEDIUM
    if cost >= 50:
        return Severity.HIGH
    if cost >= 10:
        return Severity.MEDIUM
    return Severity.LOW
