"""Detect unusual daily spend per resource group.

For each resource group, the most recent complete day of actual cost is
compared with the preceding baseline window (14 days by default):

    anomaly  =  latest > mean + sigma * stdev   AND   latest - mean >= min_usd

The sigma test adapts to each group's normal variability: a group that
fluctuates widely needs a bigger jump to be flagged. The minimum-dollar test
stops a $0.10 group that doubles to $0.20 from being reported. Days with no
cost inside the window count as $0, so a group that suddenly starts spending
is reported as new spend.

A rolling mean and standard deviation is deliberately simple. It needs no
training, behaves predictably on two weeks of history, and every flag can be
explained in one sentence. Azure Cost Management also has built-in anomaly
alerts; this check exists so findings arrive in the same report as everything
else and the threshold logic is visible and testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import fmean, pstdev

from governance.azure_clients import Clients
from governance.config import Settings
from governance.models import Finding
from governance.scanners._common import severity_for_cost

log = logging.getLogger(__name__)

SUBSCRIPTIONS_KQL = """
ResourceContainers
| where type =~ 'microsoft.resources/subscriptions'
| project subscriptionId
"""

# Extra days requested beyond the baseline, to cover the latest day plus the
# 8-24 hour lag before cost data is complete.
FETCH_MARGIN_DAYS = 3


@dataclass
class Anomaly:
    resource_group: str
    day: date
    cost: float
    baseline_mean: float
    baseline_stdev: float
    currency: str

    @property
    def increase(self) -> float:
        return round(self.cost - self.baseline_mean, 2)

    @property
    def new_spend(self) -> bool:
        return self.baseline_mean == 0


def detect_anomalies(
    series: dict[str, dict[date, float]],
    latest: date,
    baseline_days: int,
    sigma: float,
    min_usd: float,
    currency: str = "USD",
) -> list[Anomaly]:
    """Return anomalies on `latest` for each resource group's daily cost series."""
    window = [latest - timedelta(days=n) for n in range(baseline_days, 0, -1)]
    anomalies = []
    for rg, by_day in series.items():
        today_cost = by_day.get(latest, 0.0)
        baseline = [by_day.get(d, 0.0) for d in window]
        mean, stdev = fmean(baseline), pstdev(baseline)
        if today_cost - mean < min_usd:
            continue
        if today_cost <= mean + sigma * stdev:
            continue
        anomalies.append(Anomaly(rg, latest, round(today_cost, 2), round(mean, 2),
                                 round(stdev, 2), currency))
    return anomalies


def _subscriptions(clients: Clients, settings: Settings) -> list[str]:
    if settings.subscription_ids:
        return settings.subscription_ids
    return [r["subscriptionId"] for r in clients.graph.query(SUBSCRIPTIONS_KQL)]


def scan_cost_anomalies(clients: Clients, settings: Settings) -> list[Finding]:
    if clients.cost is None:
        log.info("No cost client configured; skipping cost-anomaly check")
        return []

    today = datetime.now(UTC).date()
    start = today - timedelta(days=settings.cost_baseline_days + FETCH_MARGIN_DAYS)
    findings: list[Finding] = []

    for sub in _subscriptions(clients, settings):
        rows = clients.cost.daily_costs(sub, start, today)
        complete_days = [r.day for r in rows if r.day < today]   # today is still accruing
        if not complete_days:
            log.info("No complete cost data yet for subscription %s", sub)
            continue
        latest = max(complete_days)

        series: dict[str, dict[date, float]] = {}
        for r in rows:
            day_costs = series.setdefault(r.resource_group, {})
            day_costs[r.day] = day_costs.get(r.day, 0.0) + r.cost
        currency = rows[0].currency if rows else "USD"

        for a in detect_anomalies(series, latest, settings.cost_baseline_days,
                                  settings.cost_anomaly_sigma, settings.cost_anomaly_min_usd,
                                  currency):
            if a.new_spend:
                message = (f"New spend: {a.cost:,.2f} {a.currency} on {a.day} with no spend "
                           f"in the previous {settings.cost_baseline_days} days")
            else:
                message = (f"Spent {a.cost:,.2f} {a.currency} on {a.day}, "
                           f"{a.cost / a.baseline_mean:.1f}x the {settings.cost_baseline_days}-day "
                           f"average of {a.baseline_mean:,.2f}")
            findings.append(Finding(
                check="cost-anomaly",
                # Rank by what the jump would cost if it became the new normal.
                severity=severity_for_cost(a.increase * 30),
                resource_id=f"/subscriptions/{sub}/resourceGroups/{a.resource_group}",
                resource_name=a.resource_group,
                resource_type="microsoft.resources/resourcegroups",
                resource_group=a.resource_group,
                subscription_id=sub,
                message=message,
                # Not waste: an anomaly may be legitimate growth. Kept out of the total.
                est_monthly_cost_usd=None,
                details={
                    "day": a.day.isoformat(),
                    "cost": a.cost,
                    "currency": a.currency,
                    "baseline_mean": a.baseline_mean,
                    "baseline_stdev": a.baseline_stdev,
                    "increase": a.increase,
                    "monthly_impact_if_sustained": round(a.increase * 30, 2),
                    "new_spend": a.new_spend,
                    "sigma": settings.cost_anomaly_sigma,
                },
            ))
    return findings
