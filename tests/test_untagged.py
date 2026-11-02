from governance.models import Severity
from governance.scanners.untagged import missing_tags, scan_untagged_resources


def test_missing_tags_is_case_insensitive():
    assert missing_tags({"OWNER": "x", "Environment": "dev"}, ["owner", "environment"]) == []


def test_blank_tag_values_count_as_missing():
    assert missing_tags({"owner": "   "}, ["owner"]) == ["owner"]


def test_none_tags():
    assert missing_tags(None, ["owner", "env"]) == ["owner", "env"]


def test_scan_flags_only_bad_resources(clients, settings):
    findings = scan_untagged_resources(clients, settings)
    names = {f.resource_name: f for f in findings}

    assert set(names) == {"stnotags", "kv-partial"}          # good one + excluded one skipped
    assert names["stnotags"].severity == Severity.MEDIUM     # missing everything
    assert names["kv-partial"].severity == Severity.LOW      # missing some
    assert names["kv-partial"].details["missing_tags"] == ["environment", "costCenter"]
