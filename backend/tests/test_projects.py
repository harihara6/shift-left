"""Project lifecycle: create, duplicate, and the ids and keys they mint."""

from urllib.parse import unquote

ENT = "/api/projects/entitlements"


async def test_the_creator_is_listed_as_the_first_admin(client, contributor):
    response = await client.post(
        "/api/projects", headers=contributor,
        json={"key": "RTO", "name": "Retail  &  Onboarding", "owner": "A. Kowalski"},
    )
    assert response.status_code == 201
    body = response.json()
    # Runs of punctuation collapse to one hyphen - the same id the seed loader mints.
    assert body["id"] == "retail-onboarding"
    assert [(g["principal"], g["role"]) for g in body["access"]] == [("dev@backbase.com", "admin")]


async def test_a_name_with_nothing_to_mint_an_id_from_is_refused(client, admin):
    response = await client.post(
        "/api/projects", headers=admin, json={"key": "XX", "name": "!!!", "owner": "Someone"}
    )
    assert response.status_code == 422


async def test_duplicating_twice_is_a_conflict_not_a_crash(client, admin):
    first = await client.post(f"{ENT}/duplicate", headers=admin)
    assert first.status_code == 201
    assert first.json()["key"] == "ENTC"
    second = await client.post(f"{ENT}/duplicate", headers=admin)
    assert second.status_code == 409


async def test_a_duplicate_key_always_fits_the_limit(client, admin):
    created = await client.post(
        "/api/projects", headers=admin,
        json={"key": "ABCDEFGHIJKLMNOP", "name": "Long Key Team", "owner": "Someone"},
    )
    assert created.status_code == 201
    copy = await client.post("/api/projects/long-key-team/duplicate", headers=admin)
    assert copy.status_code == 201
    assert len(copy.json()["key"]) <= 16


async def test_the_maint_drill_filters_by_the_team_name_everywhere(client, admin):
    """MAINT is shared by every team; the Team field holds the team's name, never its key."""
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    glance = next(row for row in payload["glance"] if row["row"] == "MAINT resolved")
    maint = next(s for s in payload["sections"] if s["key"] == "maint")
    urls = [glance["drill"]["url"], *(t["drill"]["url"] for t in maint["tiles"] if t.get("drill"))]
    assert urls
    for url in urls:
        assert '"Team" = "Entitlements"' in unquote(url)


async def test_enabling_a_template_later_still_carries_its_widget_guides(client, admin):
    """Every widget ships with its guide - including one deep-copied long after seeding."""
    created = await client.post(
        "/api/projects", headers=admin, json={"key": "NEW", "name": "New Team", "owner": "Someone"}
    )
    assert created.status_code == 201
    enabled = await client.put(
        "/api/projects/new-team/templates/delivery", headers=admin, json={"enabled": True}
    )
    widgets = enabled.json()["widgets"]
    assert widgets
    assert all(w["guide_key"] for w in widgets)


def test_release_names_compare_as_numbers():
    from app.services.readiness import _release_order

    assert max(["2026.9", "2026.10", "2025.12"], key=_release_order) == "2026.10"


def test_a_quote_cannot_end_a_jql_string_early():
    from app.services.drill import jql_string

    assert jql_string('Team "A"') == '"Team \\"A\\""'
