import json

from governance.reporting.teams import build_card
from governance.runner import run_scan
from governance.scanners import SCANNERS


def test_run_scan_combines_all_scanners(graph, settings):
    report = run_scan(graph, settings, notify=False)
    assert set(report.by_check()) == {"untagged-resource", "orphaned-disk"}
    assert report.total_est_monthly_waste == 69.12 + 1.44
    json.dumps(report.to_dict())  # must be JSON-serialisable for the HTTP endpoint


def test_one_failing_scanner_does_not_kill_run(graph, settings, monkeypatch):
    def boom(_g, _s):
        raise RuntimeError("API down")

    monkeypatch.setitem(SCANNERS, "untagged-resource", boom)
    report = run_scan(graph, settings, notify=False)
    assert set(report.by_check()) == {"orphaned-disk"}


def test_teams_card_shape(graph, settings):
    card = build_card(run_scan(graph, settings, notify=False))
    content = card["attachments"][0]["content"]
    assert card["type"] == "message"
    assert content["type"] == "AdaptiveCard"
    text = json.dumps(content)
    assert "old-vm_OsDisk" in text           # most expensive item surfaces
    assert "$70.56" in text                  # total waste shown


def test_teams_posts_when_webhook_set(graph, settings, monkeypatch):
    sent = {}

    def fake_post(url, report):
        sent["url"] = url

    monkeypatch.setattr("governance.runner.post_to_teams", fake_post)
    settings.teams_webhook_url = "https://example.invalid/hook"
    run_scan(graph, settings, notify=True)
    assert sent["url"] == "https://example.invalid/hook"
