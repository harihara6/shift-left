"""Authorization is enforced at the API layer, not by hiding things in the UI.

This suite is required in CI (TDD s11) - it is the launch-blocking control from PRD s8.
"""

import pytest

ENT = "/api/projects/entitlements"


async def test_no_session_is_rejected(client):
    assert (await client.get(f"{ENT}/team-insights")).status_code == 401


async def test_project_list_is_scoped_to_grants(client, admin, viewer, stranger):
    assert {p["key"] for p in (await client.get("/api/projects", headers=admin)).json()} >= {"ENT", "PAY"}
    assert [p["key"] for p in (await client.get("/api/projects", headers=viewer)).json()] == ["ENT"]
    assert (await client.get("/api/projects", headers=stranger)).json() == []


async def test_unauthorized_read_reveals_nothing(client, stranger):
    """404, not 403: a caller with no grant learns nothing about what exists."""
    assert (await client.get(f"{ENT}/team-insights", headers=stranger)).status_code == 404
    assert (await client.get(ENT, headers=stranger)).status_code == 404


async def test_viewer_cannot_write(client, viewer):
    response = await client.put(f"{ENT}/templates/portfolio", headers=viewer, json={"enabled": True})
    assert response.status_code == 404


async def test_contributor_can_edit_bindings_but_not_grant_access(client, contributor):
    templates = (await client.get(f"{ENT}/templates", headers=contributor)).json()
    widget = next(t for t in templates if t["enabled"])["widgets"][0]
    edit = await client.patch(
        f"{ENT}/templates/widgets/{widget['id']}", headers=contributor, json={"query": "x"}
    )
    assert edit.status_code == 200

    grant = await client.post(
        f"{ENT}/access", headers=contributor,
        json={"principal": "someone@backbase.com", "role": "admin", "via": "Explicit grant"},
    )
    assert grant.status_code == 404


async def test_project_cannot_be_left_without_an_admin(client, admin):
    grants = (await client.get(f"{ENT}/access", headers=admin)).json()
    only_admin = next(g for g in grants if g["role"] == "admin")
    response = await client.delete(f"{ENT}/access/{only_admin['id']}", headers=admin)
    assert response.status_code == 409


@pytest.mark.parametrize("project", ["db-payments", "nucleus"])
async def test_grants_do_not_leak_across_projects(client, viewer, project):
    """A viewer on Entitlements reaches nothing on another team's project."""
    assert (await client.get(f"/api/projects/{project}/team-insights", headers=viewer)).status_code == 404


CONNECTOR_WRITES = [
    ("put", "/api/connectors/jira", {"config": {"site_url": "https://evil.example"}}),
    ("post", "/api/connectors/jira/secrets", {"field_key": "api_token", "value": "x"}),
    ("post", "/api/connectors/jira/toggle", None),
    ("post", "/api/connectors/jira/test", None),
]


@pytest.mark.parametrize(("method", "path", "body"), CONNECTOR_WRITES)
async def test_only_a_platform_admin_changes_service_wide_connectors(
    client, contributor, method, path, body
):
    """Connectors belong to no project, so a project admin role is not enough to change one."""
    response = await client.request(method.upper(), path, headers=contributor, json=body)
    assert response.status_code == 403
    detail = (await client.get("/api/connectors/jira", headers=contributor)).json()
    assert next(f for f in detail["fields"] if f["key"] == "site_url")["value"] != "https://evil.example"


async def test_only_a_platform_admin_changes_the_kickoff_defaults(client, contributor, viewer):
    """They belong to no project either: a project admin role is not enough to change them.

    Reading them is open, unlike a connector's secrets: they hold no credential, and the kickoff
    wizard fills a new analysis in from them for whoever is running it.
    """
    assert (await client.get("/api/kickoff/settings", headers=viewer)).status_code == 200
    assert (await client.get("/api/kickoff/settings", headers=viewer)).json()["editable"] is False

    refused = await client.put(
        "/api/kickoff/settings", headers=contributor, json={"jira_project_url": "EVIL"}
    )
    assert refused.status_code == 403
    assert (await client.get("/api/kickoff/settings", headers=viewer)).json()["jira_project_url"] != "EVIL"


async def test_any_signed_in_user_can_read_connectors(client, viewer):
    assert (await client.get("/api/connectors", headers=viewer)).status_code == 200
    assert (await client.get("/api/connectors/jira", headers=viewer)).status_code == 200


async def test_platform_admin_is_configured_not_claimed(boot):
    """The operator set comes from configuration; nobody is an operator by default elsewhere."""
    async with boot(SHIFTLEFT_PLATFORM_ADMINS='["ops@backbase.com"]') as c:
        ops = {"X-ShiftLeft-User": "ops@backbase.com"}
        former = {"X-ShiftLeft-User": "h.nuti@backbase.com"}
        assert (await c.get("/api/access-model/me", headers=ops)).json()["platform_admin"] is True
        assert (await c.get("/api/access-model/me", headers=former)).json()["platform_admin"] is False
        assert (await c.post("/api/connectors/jira/toggle", headers=former)).status_code == 403


async def test_trusted_proxy_mode_ignores_identity_headers_without_the_proxy_secret(boot):
    """Behind the SSO proxy, a caller who reaches the service directly cannot name themselves."""
    async with boot(SHIFTLEFT_AUTH_MODE="trusted-proxy", SHIFTLEFT_PROXY_SHARED_SECRET="s3cret") as c:
        claimed = {"X-ShiftLeft-User": "h.nuti@backbase.com"}
        assert (await c.get("/api/projects", headers=claimed)).status_code == 401
        wrong = {**claimed, "X-ShiftLeft-Proxy-Secret": "guess"}
        assert (await c.get("/api/projects", headers=wrong)).status_code == 401
        proxied = {**claimed, "X-ShiftLeft-Proxy-Secret": "s3cret"}
        assert (await c.get("/api/projects", headers=proxied)).status_code == 200
