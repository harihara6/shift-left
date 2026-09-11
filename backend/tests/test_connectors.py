"""Connector configuration, and the write-only rule for credentials."""

ADMIN = {"X-ShiftLeft-User": "h.nuti@backbase.com"}


async def test_secrets_are_never_returned(client, admin):
    detail = (await client.get("/api/connectors/jira", headers=admin)).json()
    secrets = [f for f in detail["fields"] if f["type"] == "secret"]
    assert secrets, "Jira declares at least one credential field"
    for field in secrets:
        assert field["value"] is None
        assert "vault" in field["placeholder"]


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
    connectors = (await client.get("/api/connectors", headers=admin)).json()
    xray = next(c for c in connectors if c["key"] == "xray")
    assert xray["stale"] is True
    assert xray["state_label"] == "Stale"


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
