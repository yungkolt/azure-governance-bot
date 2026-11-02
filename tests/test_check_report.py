"""The e2e assertion helper must pass on a complete report and fail on a partial one."""

import json
import subprocess
import sys

LAB = "rg-gov-lab"


def finding(check, rg=LAB, rid="x", name="n", **details):
    return {"check": check, "resource_group": rg, "resource_id": rid, "resource_name": name,
            "details": details}


def run(tmp_path, findings, *flags, env=None):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"findings": findings}))
    return subprocess.run(  # noqa: S603 (fixed interpreter and script)
        [sys.executable, "scripts/check_report.py", str(path), *flags],
        capture_output=True, text=True, env=env,
    )


WASTE = [finding("orphaned-disk"), finding("orphaned-public-ip"), finding("orphaned-nic"),
         finding("untagged-resource")]


def test_passes_on_complete_waste_report(tmp_path):
    assert run(tmp_path, WASTE).returncode == 0


def test_fails_when_a_finding_is_missing(tmp_path):
    result = run(tmp_path, WASTE[:-1])
    assert result.returncode == 1
    assert "FAIL  untagged resource in lab" in result.stdout


def test_ignores_findings_outside_the_lab(tmp_path):
    assert run(tmp_path, [finding("orphaned-disk", rg="rg-prod")] + WASTE[1:]).returncode == 1


def test_rbac_expectations(tmp_path):
    env = {"DISABLED_ID": "u1", "DELETED_ASSIGNMENT": "/RA/2", "ROLE_NAME": "Lab Role",
           "PATH": ""}
    rbac = [
        finding("broad-role-assignment", principal_id="u1"),
        finding("stale-role-assignment", principal_id="u1", reason="user-disabled"),
        finding("stale-role-assignment", rid="/ra/2", reason="principal-deleted"),
        finding("custom-role-wildcard", name="Lab Role"),
    ]
    assert run(tmp_path, WASTE + rbac, "--rbac", env=env).returncode == 0
    assert run(tmp_path, WASTE + rbac[:-1], "--rbac", env=env).returncode == 1
