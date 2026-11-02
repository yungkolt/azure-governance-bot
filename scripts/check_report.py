"""Assert that a scan report contains the findings the test environments create.

Used by scripts/e2e.sh. Exits 0 when every expectation is met, 1 otherwise,
and prints one PASS/FAIL line per expectation.

    python scripts/check_report.py report.json [--rbac]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable

LAB_RG = "rg-gov-lab"


def in_lab(f: dict) -> bool:
    return f["resource_group"].lower() == LAB_RG


def expectations(rbac: bool) -> list[tuple[str, Callable[[dict], bool]]]:
    checks: list[tuple[str, Callable[[dict], bool]]] = [
        ("orphaned disk in lab", lambda f: f["check"] == "orphaned-disk" and in_lab(f)),
        ("orphaned public IP in lab", lambda f: f["check"] == "orphaned-public-ip" and in_lab(f)),
        ("orphaned NIC in lab", lambda f: f["check"] == "orphaned-nic" and in_lab(f)),
        ("untagged resource in lab", lambda f: f["check"] == "untagged-resource" and in_lab(f)),
    ]
    if rbac:
        disabled = os.environ.get("DISABLED_ID", "")
        deleted = os.environ.get("DELETED_ASSIGNMENT", "").lower()
        role = os.environ.get("ROLE_NAME", "")
        checks += [
            ("broad role: disabled lab user (Contributor)",
             lambda f: f["check"] == "broad-role-assignment"
             and f["details"].get("principal_id") == disabled),
            ("stale role: disabled user",
             lambda f: f["check"] == "stale-role-assignment"
             and f["details"].get("reason") == "user-disabled"
             and f["details"].get("principal_id") == disabled),
            ("stale role: deleted principal",
             lambda f: f["check"] == "stale-role-assignment"
             and f["resource_id"].lower() == deleted),
            ("custom role wildcard",
             lambda f: f["check"] == "custom-role-wildcard" and f["resource_name"] == role),
        ]
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--rbac", action="store_true", help="also expect identity-lab findings")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    with open(args.report) as fh:
        findings = json.load(fh)["findings"]

    failed = 0
    for name, predicate in expectations(args.rbac):
        ok = any(predicate(f) for f in findings)
        failed += not ok
        if not args.quiet:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
