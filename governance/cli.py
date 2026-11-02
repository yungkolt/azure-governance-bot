"""Run a scan from your laptop.

    az login
    python -m governance.cli                  # print summary
    python -m governance.cli --json out.json  # save full report
    python -m governance.cli --teams          # also post to Teams
"""

from __future__ import annotations

import argparse
import json
import logging

from governance.azure_clients import build_clients
from governance.config import load_settings
from governance.runner import run_scan


def main() -> None:
    p = argparse.ArgumentParser(description="Azure governance scan")
    p.add_argument("--json", help="write full report to this file")
    p.add_argument("--teams", action="store_true", help="post summary to Teams")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    # Azure SDK HTTP logging is very verbose at INFO; keep -v focused on scan output.
    logging.getLogger("azure").setLevel(logging.WARNING)

    settings = load_settings()
    report = run_scan(build_clients(settings.subscription_ids), settings, notify=args.teams)

    print(f"\nRun {report.run_id}  ({report.started_at})")
    for check, items in sorted(report.by_check().items()):
        print(f"  {check:<20} {len(items):>5}")
    print(f"  {'est. monthly waste':<20} ${report.total_est_monthly_waste:>9,.2f}\n")

    for f in sorted(report.findings, key=lambda f: f.est_monthly_cost_usd or 0, reverse=True)[:10]:
        cost = f"${f.est_monthly_cost_usd:,.2f}/mo" if f.est_monthly_cost_usd else ""
        print(f"  [{f.severity.value:<6}] {f.resource_group}/{f.resource_name}: {f.message} {cost}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report.to_dict(), fh, indent=2)
        print(f"\nFull report written to {args.json}")


if __name__ == "__main__":
    main()
