"""Template governance: deep copy on enable, no runtime coupling afterwards."""

ENT = "/api/projects/entitlements"


async def test_enabling_deep_copies_the_template(client, admin):
    response = await client.put(f"{ENT}/templates/portfolio", headers=admin, json={"enabled": True})
    body = response.json()
    assert body["enabled"] is True
    assert body["copied_at"] is not None
    assert body["copied_from_version"] == 1
    assert body["widgets"], "a copied template brings its widget bindings with it"


async def test_editing_a_catalog_template_never_reaches_a_project(client, admin):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.template import TemplateWidget

    before = (await client.get(f"{ENT}/templates", headers=admin)).json()
    delivery = next(t for t in before if t["template_key"] == "delivery")
    original_query = delivery["widgets"][0]["query"]

    async with SessionLocal() as session:
        widget = (
            await session.execute(
                select(TemplateWidget).where(TemplateWidget.template_key == "delivery")
                .order_by(TemplateWidget.position)
            )
        ).scalars().first()
        widget.query = "CATALOG EDIT — must not propagate"
        await session.commit()

    after = (await client.get(f"{ENT}/templates", headers=admin)).json()
    assert next(t for t in after if t["template_key"] == "delivery")["widgets"][0]["query"] == original_query


async def test_disable_then_enable_keeps_the_projects_own_edits(client, admin):
    templates = (await client.get(f"{ENT}/templates", headers=admin)).json()
    widget = next(t for t in templates if t["template_key"] == "delivery")["widgets"][0]
    await client.patch(f"{ENT}/templates/widgets/{widget['id']}", headers=admin,
                       json={"query": "project-owned query"})
    await client.put(f"{ENT}/templates/delivery", headers=admin, json={"enabled": False})
    response = await client.put(f"{ENT}/templates/delivery", headers=admin, json={"enabled": True})
    assert response.json()["widgets"][0]["query"] == "project-owned query"


async def test_preview_reports_an_empty_result_as_empty(client, admin):
    templates = (await client.get(f"{ENT}/templates", headers=admin)).json()
    widget = next(t for t in templates if t["template_key"] == "delivery")["widgets"][0]
    await client.patch(f"{ENT}/templates/widgets/{widget['id']}", headers=admin, json={"query": "   "})
    preview = (await client.post(f"{ENT}/templates/widgets/{widget['id']}/preview", headers=admin)).json()
    assert preview["row_count"] == 0
    assert "matched nothing" in preview["note"]
