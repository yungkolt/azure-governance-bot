import pytest

from governance.azure_clients import Clients
from governance.models import Severity
from governance.scanners.broad_role_assignments import scan_broad_role_assignments
from governance.scanners.custom_role_wildcards import scan_custom_role_wildcards, wildcard_actions
from governance.scanners.rbac import load_assignments, resource_group_of, role_guid, scope_level
from governance.scanners.stale_role_assignments import scan_stale_role_assignments
from tests.conftest import (
    FOREIGN,
    G_OPS,
    SP_POLICY,
    SUB,
    U_ALICE,
    U_DISABLED,
    U_GONE,
    FakeDirectory,
    FakeRoles,
)


def ids(findings):
    return {f.resource_id.rsplit("/", 1)[-1] for f in findings}


# --- helpers ----------------------------------------------------------------

@pytest.mark.parametrize("scope, level", [
    ("/", "root"),
    ("/providers/Microsoft.Management/managementGroups/mg1", "management-group"),
    (f"/subscriptions/{SUB}", "subscription"),
    (f"/subscriptions/{SUB}/resourceGroups/rg1", "resource-group"),
    (f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Compute/disks/d1", "resource"),
])
def test_scope_level(scope, level):
    assert scope_level(scope) == level


def test_resource_group_of():
    assert resource_group_of(f"/subscriptions/{SUB}/resourceGroups/RG-App") == "RG-App"
    assert resource_group_of(f"/subscriptions/{SUB}") is None


def test_role_guid_normalises_format():
    assert role_guid("/subscriptions/x/providers/Microsoft.Authorization/roleDefinitions/ABC/") \
        == "abc"


def test_built_in_and_custom_role_names(clients):
    names = {a.role_name for a in load_assignments(clients)}
    assert {"Owner", "Contributor", "Reader", "VM Operator Plus"} <= names


# --- broad role assignments -------------------------------------------------

def test_broad_assignments(clients, settings):
    findings = scan_broad_role_assignments(clients, settings)
    found = {f.resource_id.rsplit("/", 1)[-1]: f for f in findings}
    # 1 Owner/user/sub, 2 Contributor/group/sub, 5 policy SP, 6 deleted owner,
    # 9 foreign group, 10 management group.  3 is RG scope, 4 is Reader: excluded.
    assert set(found) == {"ra-1", "ra-2", "ra-5", "ra-6", "ra-9", "ra-10"}
    assert found["ra-1"].severity == Severity.HIGH            # Owner grants access
    assert found["ra-2"].severity == Severity.MEDIUM          # Contributor doesn't
    assert found["ra-10"].details["scope_level"] == "management-group"


def test_direct_user_assignment_is_called_out(clients, settings):
    found = {f.details["principal_id"]: f for f in scan_broad_role_assignments(clients, settings)}
    assert "directly to a user" in found[U_ALICE].message
    assert "directly to a user" not in found[G_OPS].message


def test_principal_names_resolved(clients, settings):
    found = {f.details["principal_id"]: f for f in scan_broad_role_assignments(clients, settings)}
    assert found[U_ALICE].resource_name == "alice@contoso.com"
    assert found[U_GONE].resource_name == U_GONE              # unresolved: falls back to ID


def test_allowlist(clients, settings):
    settings.rbac_allowed_principals = [SP_POLICY.upper()]   # case-insensitive
    assert "ra-5" not in ids(scan_broad_role_assignments(clients, settings))


def test_broad_check_survives_graph_failure(graph, settings):
    clients = Clients(graph=graph, directory=FakeDirectory(fail=True))
    findings = scan_broad_role_assignments(clients, settings)
    assert len(findings) == 6                                  # still reported, IDs only


# --- stale role assignments -------------------------------------------------

def test_stale_assignments(clients, settings):
    found = {f.details["principal_id"]: f for f in scan_stale_role_assignments(clients, settings)}
    assert set(found) == {U_GONE, U_DISABLED}
    assert found[U_GONE].details["reason"] == "principal-deleted"
    assert found[U_GONE].severity == Severity.HIGH            # privileged role
    assert found[U_DISABLED].details["reason"] == "user-disabled"
    assert found[U_DISABLED].severity == Severity.MEDIUM      # Reader


def test_foreign_groups_not_treated_as_deleted(clients, directory, settings):
    scan_stale_role_assignments(clients, settings)
    assert FOREIGN not in directory.calls[0]


def test_graph_failure_raises_instead_of_false_positives(graph, settings):
    clients = Clients(graph=graph, directory=FakeDirectory(fail=True))
    with pytest.raises(RuntimeError):
        scan_stale_role_assignments(clients, settings)


def test_stale_skipped_without_directory(graph, settings):
    assert scan_stale_role_assignments(Clients(graph=graph), settings) == []


# --- custom role wildcards --------------------------------------------------

def test_wildcard_detection():
    assert wildcard_actions([{"actions": ["*"]}]) == (["*"], [])
    assert wildcard_actions([{"Actions": ["Microsoft.Compute/*"]}]) == ([], ["Microsoft.Compute/*"])
    assert wildcard_actions([{"actions": ["*/read", "Microsoft.Compute/disks/read"]}]) == ([], [])
    assert wildcard_actions([{"dataActions": ["*"]}]) == (["*"], [])


def test_custom_role_wildcards(clients, settings):
    found = {f.resource_name: f for f in scan_custom_role_wildcards(clients, settings)}
    assert set(found) == {"Everything Role", "VM Operator Plus"}   # built-in Owner ignored
    assert found["Everything Role"].severity == Severity.HIGH
    assert found["VM Operator Plus"].severity == Severity.MEDIUM
    assert found["VM Operator Plus"].details["assignment_count"] == 1
    assert found["Everything Role"].details["assignment_count"] == 0


def test_role_queries_are_shared(clients, graph, settings):
    scan_broad_role_assignments(clients, settings)
    scan_custom_role_wildcards(clients, settings)
    assert all("authorizationresources" in q for q in graph.queries)


# --- role names and de-duplication -----------------------------------------

def test_built_in_role_names_from_authorization_api(clients):
    names = {a.id.rsplit("/", 1)[-1]: a.role_name for a in load_assignments(clients)}
    assert names["ra-11"] == "Key Vault Secrets User"


def test_role_names_fall_back_when_api_fails(graph):
    clients = Clients(graph=graph, roles=FakeRoles(fail=True))
    names = {a.id.rsplit("/", 1)[-1]: a.role_name for a in load_assignments(clients)}
    assert names["ra-1"] == "Owner"                       # hardcoded built-in still named
    assert names["ra-11"] == "4633458b-17de-408a-b874-0445c86b69e6"   # GUID as last resort


def test_duplicate_assignment_rows_are_collapsed(clients):
    ids = [a.id for a in load_assignments(clients)]
    assert len(ids) == len(set(ids)) == 11
