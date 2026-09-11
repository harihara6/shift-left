"""The product rules that are not allowed to regress."""

from datetime import datetime, timedelta, timezone

ENT = "/api/projects/entitlements"


async def test_stale_source_holds_the_page_out_of_green(client, admin):
    """A connector past its threshold can never contribute to a green state."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.connector import ConnectorInstance

    before = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    greens_before = [
        tile for section in before["sections"] for tile in section["tiles"]
        if tile["status"] and tile["status"]["rag"] == "good"
    ]
    assert greens_before, "fixture should start with at least one green tile"
    assert before["freshness"]["stale"] is False

    async with SessionLocal() as session:
        instance = (
            await session.execute(
                select(ConnectorInstance).where(ConnectorInstance.connector_key == "jira")
            )
        ).scalars().first()
        instance.last_successful_sync = datetime.now(timezone.utc) - timedelta(hours=6)
        await session.commit()

    after = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    assert after["freshness"]["stale"] is True
    assert "Jira" in after["freshness"]["note"]
    statuses = [
        tile["status"] for section in after["sections"] for tile in section["tiles"] if tile["status"]
    ]
    assert all(s["rag"] != "good" for s in statuses)
    downgraded = [s for s in statuses if any("Held out of green" in r for r in s["reasons"])]
    assert downgraded, "a downgrade must say why it was held out of green"


async def test_every_rag_state_carries_a_glyph_and_reasons(client, admin):
    """Colour is never the only carrier of meaning (WCAG 2.2 AA)."""
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    states = [row["status"] for row in payload["glance"]]
    states += [t["status"] for s in payload["sections"] for t in s["tiles"] if t["status"]]
    assert states
    for state in states:
        assert state["glyph"], "a RAG state must ship with a non-colour glyph"
        assert state["label"]


async def test_flow_view_always_links_back_to_the_evidence_record(client, admin):
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    assert payload["evidence_link"]["perspective"] == "discipline"
    assert payload["evidence_link"]["project_id"] == "entitlements"


async def test_window_caveat_travels_with_the_comparison(client, admin):
    """The caveat is on the page, and every count comparison shows the rate arithmetic behind it."""
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    assert "compare rates, not raw counts" in payload["comparison_caveat"]

    counted = [row for row in payload["glance"] if "/wk" in " ".join(row["status"]["reasons"])]
    assert counted, "throughput rows must be judged as rates, not as raw counts"
    for row in counted:
        assert "rate, not raw count" in " ".join(row["status"]["reasons"])


async def test_missing_snapshot_is_a_gap_not_an_empty_dashboard(client, admin):
    response = await client.get(
        f"{ENT}/team-insights?preset=custom&period=Q1-2020", headers=admin
    )
    assert response.status_code == 404
    assert "gap" in response.json()["detail"]


async def test_every_rendered_widget_has_its_four_guide_fields(client, admin):
    guide = (await client.get("/api/guides/delivery", headers=admin)).json()
    keys = {w["widget_key"] for w in guide["widgets"]}
    assert keys == {"glance", "epics", "stories", "maint", "prs"}
    for widget in guide["widgets"]:
        assert widget["decision"] and widget["source"] and widget["fetch"] and widget["tagging"]


async def test_every_chart_names_its_source_and_both_axes(client, admin):
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    charts = [c for s in payload["sections"] for c in s["charts"]]
    assert charts
    for chart in charts:
        assert "x-axis" in chart["caption"] and "y-axis" in chart["caption"]
