"""Tests GraphDirectory's request batching and parsing without calling Graph."""

from urllib.parse import unquote

import pytest

pytest.importorskip("azure.identity")

from governance.azure_clients import GraphDirectory  # noqa: E402


class StubGraph(GraphDirectory):
    """GraphDirectory with the HTTP layer replaced by an in-memory directory."""

    def __init__(self, objects: dict[str, dict], enabled: dict[str, bool]):
        super().__init__(credential=object())
        self.objects, self.enabled, self.requests = objects, enabled, []

    def _request(self, method, path, body=None):
        self.requests.append((method, unquote(path), body))
        if path == "/directoryObjects/getByIds":
            assert len(body["ids"]) <= 1000
            return {"value": [self.objects[i] for i in body["ids"] if i in self.objects]}
        ids = [i for i in self.enabled if f"'{i}'" in unquote(path)]
        assert len(ids) <= 15
        return {"value": [{"id": i, "accountEnabled": self.enabled[i]} for i in ids]}


def user(i, upn):
    return {"id": i, "@odata.type": "#microsoft.graph.user",
            "displayName": upn, "userPrincipalName": upn}


def test_lookup_resolves_types_and_flags_disabled():
    g = StubGraph(
        objects={
            "u1": user("u1", "a@x.com"),
            "u2": user("u2", "b@x.com"),
            "g1": {"id": "g1", "@odata.type": "#microsoft.graph.group", "displayName": "Ops"},
            "s1": {"id": "s1", "@odata.type": "#microsoft.graph.servicePrincipal",
                   "displayName": "app", "appId": "app-1", "accountEnabled": True},
        },
        enabled={"u1": True, "u2": False},
    )
    found = g.lookup(["u1", "u2", "g1", "s1", "deleted"])
    assert set(found) == {"u1", "u2", "g1", "s1"}               # 'deleted' not returned
    assert found["u2"].account_enabled is False
    assert found["g1"].type == "group"
    assert found["s1"].sign_in_name == "app-1"


def test_batches_large_requests():
    objs = {f"u{n}": user(f"u{n}", f"{n}@x.com") for n in range(1200)}
    g = StubGraph(objs, enabled={i: True for i in objs})
    found = g.lookup(list(objs))
    assert len(found) == 1200
    by_ids = [r for r in g.requests if r[1] == "/directoryObjects/getByIds"]
    assert len(by_ids) == 2                                      # 1000 + 200
    assert len(g.requests) - len(by_ids) == 80                   # 1200 users / 15


def test_results_are_cached_within_a_run():
    g = StubGraph({"u1": user("u1", "a@x.com")}, enabled={"u1": True})
    g.lookup(["u1", "gone"])
    count = len(g.requests)
    assert set(g.lookup(["u1", "gone"])) == {"u1"}
    assert len(g.requests) == count                              # no new calls
