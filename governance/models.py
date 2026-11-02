"""Data models shared by every scanner.

Every scanner returns the same `Finding` shape, so reporting code is
independent of which check produced a result. New scanners require no
changes to reporting (open/closed principle).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Finding:
    """One governance problem with one Azure resource."""

    check: str                 # e.g. "untagged-resource", "orphaned-disk"
    severity: Severity
    resource_id: str           # full ARM ID: /subscriptions/.../providers/...
    resource_name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    message: str               # human-readable explanation
    est_monthly_cost_usd: float | None = None   # FinOps: what is this costing us?
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class ScanReport:
    """All findings from one run, plus run metadata."""

    run_id: str
    started_at: str
    subscriptions: list[str]
    findings: list[Finding] = field(default_factory=list)

    @property
    def total_est_monthly_waste(self) -> float:
        return round(sum(f.est_monthly_cost_usd or 0 for f in self.findings), 2)

    def by_check(self) -> dict[str, list[Finding]]:
        groups: dict[str, list[Finding]] = {}
        for f in self.findings:
            groups.setdefault(f.check, []).append(f)
        return groups

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "subscriptions": self.subscriptions,
            "total_findings": len(self.findings),
            "total_est_monthly_waste_usd": self.total_est_monthly_waste,
            "findings": [f.to_dict() for f in self.findings],
        }
