"""Connector configuration, and the write-only rule for credentials."""

import httpx

ADMIN = {"X-ShiftLeft-User": "h.nuti@backbase.com"}


def _fake_transport(handle) -> None:
    """Routes this test's outbound HTTP through `handle` instead of the network.

    The `client` fixture reboots the app per test (see conftest.py's `_booted`), which reimports
    app.connectors.http fresh each time - so this has to import it *after* that boot, not at
    module scope, or it patches a stale copy nothing still in use ever reads from.
    """
    from app.connectors import http as outbound

    outbound.transport = httpx.MockTransport(handle)


async def _configure(client, admin, key: str, config: dict, secrets: dict) -> None:
    if config:
        response = await client.put(f"/api/connectors/{key}", headers=admin, json={"config": config})
        assert response.status_code == 200, response.text
    for field_key, value in secrets.items():
        response = await client.post(
            f"/api/connectors/{key}/secrets", headers=admin, json={"field_key": field_key, "value": value}
        )
        assert response.status_code == 204, response.text


async def test_secrets_are_never_returned(client, admin):
    detail = (await client.get("/api/connectors/jira", headers=admin)).json()
    secrets = [f for f in detail["fields"] if f["type"] == "secret"]
    assert secrets, "Jira declares at least one credential field"
    for field in secrets:
        assert field["value"] is None
        # Nothing stored yet, so nothing claims to be.
        assert field["placeholder"].startswith("Not set")

    await _configure(client, admin, "jira", {}, {"api_token": "a-real-token"})
    response = await client.get("/api/connectors/jira", headers=admin)
    token = next(f for f in response.json()["fields"] if f["key"] == "api_token")
    assert token["value"] is None and "stored in vault" in token["placeholder"]
    assert "a-real-token" not in response.text


async def test_a_catalog_example_is_a_placeholder_not_a_value(client, admin):
    """A value only shown, never saved, is read by nothing: it must not look configured."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.connector import ConnectorInstance

    async with SessionLocal() as session:
        query = select(ConnectorInstance).where(ConnectorInstance.connector_key == "confluence")
        instance = (await session.execute(query)).scalars().first()
        instance.config = {k: v for k, v in instance.config.items() if k != "account_email"}
        await session.commit()
    detail = (await client.get("/api/connectors/confluence", headers=admin)).json()
    email = next(f for f in detail["fields"] if f["key"] == "account_email")
    assert email["value"] is None and email["placeholder"]


async def test_credentials_cannot_be_written_through_the_config_body(client, admin):
    response = await client.put(
        "/api/connectors/jira", headers=admin, json={"config": {"api_token": "hunter2"}}
    )
    assert response.status_code == 400


async def test_rotating_a_credential_stores_a_reference_not_a_value(client, admin):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.connector import ConnectorInstance

    response = await client.post(
        "/api/connectors/jira/secrets", headers=admin,
        json={"field_key": "api_token", "value": "a-real-token"},
    )
    assert response.status_code == 204
    async with SessionLocal() as session:
        instance = (
            await session.execute(
                select(ConnectorInstance).where(ConnectorInstance.connector_key == "jira")
            )
        ).scalars().first()
        assert instance.secret_refs["api_token"].startswith("vault://")
        assert "a-real-token" not in str(instance.config) + str(instance.secret_refs)


async def test_a_stale_connector_reports_stale_regardless_of_stored_state(client, admin):
    r = await client.post("/api/connectors/xray/secrets", headers=admin,
                          json={"field_key": "client_secret", "value": "a-real-secret"})
    assert r.status_code == 204
    connectors = (await client.get("/api/connectors", headers=admin)).json()
    xray = next(c for c in connectors if c["key"] == "xray")
    assert xray["stale"] is True
    assert xray["state_label"] == "Stale"


async def test_connected_is_never_shown_without_a_stored_credential(client, admin):
    """A seeded "Connected" with nothing in the vault can read nothing, so it says so (rule 1)."""
    connectors = (await client.get("/api/connectors", headers=admin)).json()
    github = next(c for c in connectors if c["key"] == "github")
    assert github["state"] == "not_configured" and github["state_label"] == "No credential stored"
    assert github["sync_label"] == "—" and github["instances"] == 0
    # CI shares GitHub's connection, so it has none either.
    ci = next(c for c in connectors if c["key"] == "ci")
    assert ci["state"] == "not_configured"

    r = await client.post("/api/connectors/github/secrets", headers=admin,
                          json={"field_key": "personal_access_token", "value": "a-real-token"})
    assert r.status_code == 204
    detail = (await client.get("/api/connectors/github", headers=admin)).json()
    assert detail["state"] in ("connected", "stale")
    connectors = (await client.get("/api/connectors", headers=admin)).json()
    assert next(c for c in connectors if c["key"] == "ci")["state"] in ("connected", "stale")


async def test_a_store_seeded_from_an_older_catalog_gets_the_current_connector_forms(client, admin):
    """GitHub once offered an App installation; the service reads a token. The form follows the code."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.connector import ConnectorInstance, ConnectorType
    from app.seed.loader import seed_reference

    async with SessionLocal() as session:
        github = await session.get(ConnectorType, "github")
        github.auth_methods = [{"label": "GitHub App installation", "recommended": True}]
        github.fields = [{"key": "private_key", "label": "Private key", "help": "", "type": "secret",
                          "seed_value": None}]
        instance = (await session.execute(
            select(ConnectorInstance).where(ConnectorInstance.connector_key == "github"))).scalars().first()
        instance.auth_method = "GitHub App installation"
        await session.commit()
        assert await seed_reference(session) is True

    detail = (await client.get("/api/connectors/github", headers=admin)).json()
    assert "personal_access_token" in {f["key"] for f in detail["fields"]}
    assert "private_key" not in {f["key"] for f in detail["fields"]}
    assert detail["selected_auth"] == detail["auth_methods"][0]["label"]


async def test_config_accepts_only_the_connectors_own_fields(client, admin):
    """The form is data-driven from the connector's field set; nothing else is stored."""
    response = await client.put(
        "/api/connectors/jira", headers=admin, json={"config": {"not_a_field": "x"}}
    )
    assert response.status_code == 400
    assert "not_a_field" in response.json()["detail"]


async def test_auth_method_must_be_one_the_connector_declares(client, admin):
    response = await client.put(
        "/api/connectors/jira", headers=admin, json={"auth_method": "Carrier pigeon"}
    )
    assert response.status_code == 400


async def test_a_secret_value_is_never_echoed_in_a_validation_error(client, admin):
    response = await client.post(
        "/api/connectors/jira/secrets", headers=admin,
        json={"field_key": "not_a_secret_field", "value": "a-real-token"},
    )
    assert response.status_code == 400
    assert "a-real-token" not in response.text


async def test_a_non_web_base_url_yields_no_drill_link(client, admin):
    """A javascript: URL pasted into config must never become a link on a widget."""
    await client.put(
        "/api/connectors/jira", headers=admin, json={"config": {"site_url": "javascript:alert(1)"}}
    )
    payload = (await client.get("/api/projects/entitlements/team-insights", headers=admin)).json()
    # Jira was the only base behind the glance links, so every one of them is now absent.
    assert all(row["drill"] is None for row in payload["glance"])


async def test_unconfigured_connector_is_a_gap(client, admin):
    connectors = (await client.get("/api/connectors", headers=admin)).json()
    pagerduty = next(c for c in connectors if c["key"] == "pagerduty")
    assert pagerduty["state"] == "not_configured"
    assert pagerduty["sync_label"] == "—"
    assert pagerduty["instances"] == 0


# --- Test connection makes a real call ------------------------------------------------------
#
# Before app/connectors/live.py, every one of these resolved to MockConnector, whose
# test_connection() only checked that *some* config and a vault reference existed - never that
# the reference resolved to anything, because until app/services/vault.py nothing did. These
# tests pin down that a bad or missing credential now fails for real, and a good one succeeds
# only because a fake standing in for the real source said so.


async def test_a_missing_credential_never_reaches_the_network(client, admin):
    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"should never have called out to {request.url}")

    _fake_transport(explode)
    response = await client.post("/api/connectors/datadog/test", headers=admin)
    body = response.json()
    assert body["ok"] is False
    assert "Missing configuration" in body["message"]


async def test_jira_test_connection_makes_a_real_authenticated_call(client, admin):
    import base64

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.atlassian.net"
        assert request.url.path == "/rest/api/3/myself"
        expected = base64.b64encode(b"bot@backbase.com:a-real-token").decode()
        assert request.headers["authorization"] == f"Basic {expected}"
        return httpx.Response(200, json={"displayName": "ShiftLeft Bot"})

    _fake_transport(handle)
    await _configure(
        client, admin, "jira",
        config={"site_url": "https://example.atlassian.net", "account_email": "bot@backbase.com"},
        secrets={"api_token": "a-real-token"},
    )
    response = await client.post("/api/connectors/jira/test", headers=admin)
    body = response.json()
    assert body["ok"] is True
    assert "ShiftLeft Bot" in body["message"]


async def test_jira_test_connection_reports_a_real_refusal_not_success(client, admin):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorMessages": ["Unauthorized"]})

    _fake_transport(handle)
    await _configure(
        client, admin, "jira",
        config={"site_url": "https://example.atlassian.net", "account_email": "bot@backbase.com"},
        secrets={"api_token": "a-wrong-token"},
    )
    response = await client.post("/api/connectors/jira/test", headers=admin)
    body = response.json()
    assert body["ok"] is False
    assert "Unauthorized" in body["message"]


async def test_github_test_connection_checks_the_pat_and_the_org(client, admin):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer a-fine-grained-pat"
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "shiftleft-bot"})
        assert request.url.path == "/orgs/backbase"
        return httpx.Response(200, json={"login": "backbase"})

    _fake_transport(handle)
    await _configure(
        client, admin, "github",
        config={"organisation": "backbase"},
        secrets={"personal_access_token": "a-fine-grained-pat"},
    )
    response = await client.post("/api/connectors/github/test", headers=admin)
    body = response.json()
    assert body["ok"] is True
    assert "shiftleft-bot" in body["message"] and "backbase is visible" in body["message"]


async def test_slack_reads_the_body_not_just_the_status_code(client, admin):
    """Slack answers 200 even when it refuses a token - the failure is in the JSON body."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    _fake_transport(handle)
    await _configure(client, admin, "slack", config={}, secrets={"bot_token": "xoxb-bad"})
    response = await client.post("/api/connectors/slack/test", headers=admin)
    body = response.json()
    assert body["ok"] is False
    assert "invalid_auth" in body["message"]


async def test_jsm_shares_jiras_credentials(client, admin):
    """JSM has no credential field of its own; connectors.py merges Jira's in before testing."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.atlassian.net"
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(200, json={"displayName": "ShiftLeft Bot"})
        assert request.url.path == "/rest/servicedeskapi/servicedesk"
        return httpx.Response(200, json={"values": []})

    _fake_transport(handle)
    await _configure(
        client, admin, "jira",
        config={"site_url": "https://example.atlassian.net", "account_email": "bot@backbase.com"},
        secrets={"api_token": "a-real-token"},
    )
    await _configure(client, admin, "jsm", config={"service_desk_project": "OPS"}, secrets={})
    response = await client.post("/api/connectors/jsm/test", headers=admin)
    body = response.json()
    assert body["ok"] is True
    assert "via Jira" in body["message"]


async def test_a_rotated_credential_is_encrypted_at_rest_not_stored_as_plaintext(client, admin):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.secret import VaultSecret
    from app.services import vault

    await client.post(
        "/api/connectors/jira/secrets", headers=admin,
        json={"field_key": "api_token", "value": "the-actual-secret-value"},
    )
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(VaultSecret).where(VaultSecret.ref == "vault://shiftleft/jira/api_token")
            )
        ).scalars().first()
    assert row is not None
    assert "the-actual-secret-value" not in row.ciphertext
    assert await vault.read("vault://shiftleft/jira/api_token") == "the-actual-secret-value"
