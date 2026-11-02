import json

from governance.reporting.teams import CHECK_LABELS, build_card
from governance.runner import run_scan
from governance.scanners import SCANNERS


def test_run_scan_combines_all_scanners(clients, settings):
    report = run_scan(clients, settings, notify=False)
    assert set(report.by_check()) == set(SCANNERS)
    expected = round(sum(f.est_monthly_cost_usd or 0 for f in report.findings), 2)
    assert report.total_est_monthly_waste == expected
    json.dumps(report.to_dict())  # must be JSON-serialisable for the HTTP endpoint


def test_one_failing_scanner_does_not_kill_run(clients, settings, monkeypatch):
    def boom(_c, _s):
        raise RuntimeError("API down")

    monkeypatch.setitem(SCANNERS, "untagged-resource", boom)
    report = run_scan(clients, settings, notify=False)
    assert "untagged-resource" not in report.by_check()
    assert "orphaned-disk" in report.by_check()


def test_every_check_has_a_teams_label():
    assert set(SCANNERS) <= set(CHECK_LABELS)


def test_teams_card_shape(clients, settings):
    report = run_scan(clients, settings, notify=False)
    card = build_card(report)
    content = card["attachments"][0]["content"]
    assert card["type"] == "message"
    assert content["type"] == "AdaptiveCard"
    text = json.dumps(content)
    assert "asp-p1v3" in text                                  # most expensive item surfaces
    assert f"${report.total_est_monthly_waste:,.2f}" in text   # total waste shown


def test_teams_posts_when_webhook_set(clients, settings, monkeypatch):
    sent = {}

    def fake_post(url, report):
        sent["url"] = url

    monkeypatch.setattr("governance.runner.post_to_teams", fake_post)
    settings.teams_webhook_url = "https://example.invalid/hook"
    run_scan(clients, settings, notify=True)
    assert sent["url"] == "https://example.invalid/hook"
