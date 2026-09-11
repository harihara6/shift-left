"""Guided onboarding: what it may propose, and what only a person may do.

The rules under test are the product's, not the endpoint's: discovery writes nothing, a draft
is private to whoever ran it, an unresolved widget is left empty rather than inheriting another
team's query, and a project exists only once a named person has accepted the draft.
"""

import httpx


async def _discover(client: httpx.AsyncClient, headers: dict, hint: str) -> dict:
    response = await client.post("/api/onboarding/discover", json={"hint": hint}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _binding(draft: dict, template_key: str, widget_name: str) -> dict:
    template = next(t for t in draft["templates"] if t["template_key"] == template_key)
    return next(b for b in template["bindings"] if b["widget_name"] == widget_name)


async def test_discovery_proposes_without_creating_anything(client, admin):
    before = (await client.get("/api/projects", headers=admin)).json()

    draft = await _discover(client, admin, "Retail Onboarding")

    after = (await client.get("/api/projects", headers=admin)).json()
    assert [p["id"] for p in after] == [p["id"] for p in before]
    assert draft["status"] == "draft"
    assert draft["project_key"] == "RTO"
    slots = {s["slot"]: s for s in draft["slots"]}
    assert "jira_project" in slots
    # A proposal without a source link is a claim, not a signal.
    assert slots["jira_project"]["candidate"]["url"].startswith("http")


async def test_resolved_slots_are_substituted_into_the_catalog_query(client, admin):
    draft = await _discover(client, admin, "Retail Onboarding")

    checklist = _binding(draft, "discipline", "Evidence checklist")
    assert "project = RTO" in checklist["query"]
    assert "ENT" not in checklist["query"]
    assert checklist["ready"] is True

    pages = _binding(draft, "discipline", "Artifact pages")
    assert "ancestor = 5218804" in pages["query"]


async def test_an_unresolved_slot_empties_the_query_rather_than_inheriting_one(client, admin):
    # Identity Platform has no LinearB team in any source, so the PR widget cannot be bound.
    draft = await _discover(client, admin, "Identity Platform")

    prs = _binding(draft, "delivery", "PR size & latency")
    assert prs["unresolved_slots"] == ["linearb_team"]
    assert prs["query"] == ""
    assert prs["ready"] is False
    assert "Missing" in prs["note"]


async def test_rovo_mcp_reports_why_it_is_unavailable(client, admin):
    draft = await _discover(client, admin, "Retail Onboarding")

    rovo = next(s for s in draft["sources"] if s["connector_key"] == "rovo_mcp")
    assert rovo["available"] is False
    # Unavailable is an expected state and has to say what to do about it.
    assert rovo["note"]
    # The connectors still answered, so the manual form is not the only path left.
    assert draft["discovery_available"] is True


async def test_an_unknown_name_proposes_nothing_and_says_so(client, admin):
    draft = await _discover(client, admin, "Nonexistent Squad")

    assert draft["slots"] == []
    assert not any(b["ready"] for t in draft["templates"] for b in t["bindings"])
    assert "by hand" in draft["note"]


async def test_a_draft_is_private_to_whoever_ran_it(client, contributor, viewer):
    draft = await _discover(client, contributor, "Retail Onboarding")

    # Discovery reads with the actor's own source permissions, so the draft is theirs alone.
    assert (await client.get(f"/api/onboarding/{draft['id']}", headers=viewer)).status_code == 404
    assert (await client.get(f"/api/onboarding/{draft['id']}", headers=contributor)).status_code == 200


async def test_accept_creates_the_project_and_records_who_accepted_it(client, contributor):
    draft = await _discover(client, contributor, "Retail Onboarding")
    body = {
        "key": draft["project_key"],
        "name": draft["project_name"],
        "owner": draft["owner"] or "A. Kowalski",
        "templates": [t["template_key"] for t in draft["templates"] if t["propose_enabled"]],
        "bindings": [
            {"template_key": t["template_key"], "widget_name": b["widget_name"], "query": b["query"]}
            for t in draft["templates"]
            if t["propose_enabled"]
            for b in t["bindings"]
        ],
    }

    response = await client.post(
        f"/api/onboarding/{draft['id']}/accept", json=body, headers=contributor
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["accepted_by"] == "dev@backbase.com"
    assert result["bindings_applied"] > 0
    assert result["templates_enabled"]

    project_id = result["project"]["id"]
    templates = (
        await client.get(f"/api/projects/{project_id}/templates", headers=contributor)
    ).json()
    enabled = [t for t in templates if t["enabled"]]
    assert enabled
    # Deep copy, and bound to the discovered sources — never to the catalog's exemplar team.
    queries = [w["query"] for t in enabled for w in t["widgets"]]
    assert any("project = RTO" in q for q in queries)
    assert not any("project = ENT" in q for q in queries)

    # A draft is spent once accepted.
    again = await client.post(
        f"/api/onboarding/{draft['id']}/accept", json=body, headers=contributor
    )
    assert again.status_code == 409


async def test_a_widget_nobody_accepted_a_query_for_is_left_empty(client, contributor):
    draft = await _discover(client, contributor, "Identity Platform")
    body = {
        "key": "IDP",
        "name": "Identity Platform",
        "owner": "S. Haugen",
        "templates": ["delivery"],
        # Only the epic widget is accepted; every other copied widget must end up empty.
        "bindings": [
            {
                "template_key": "delivery",
                "widget_name": "Cycle time & throughput",
                "query": _binding(draft, "delivery", "Cycle time & throughput")["query"],
            }
        ],
    }
    result = (
        await client.post(f"/api/onboarding/{draft['id']}/accept", json=body, headers=contributor)
    ).json()
    assert result["bindings_applied"] == 1
    assert result["bindings_left_empty"] >= 1

    templates = (
        await client.get(f"/api/projects/{result['project']['id']}/templates", headers=contributor)
    ).json()
    widgets = [w for t in templates if t["enabled"] for w in t["widgets"]]
    unbound = [w for w in widgets if not w["query"]]
    assert unbound, "widgets nobody bound have to be empty, not inherited"
    assert all("entitlements" not in (w["query"] or "").lower() for w in widgets)


async def test_accepting_a_name_that_already_exists_is_refused(client, admin):
    draft = await _discover(client, admin, "Entitlements")
    body = {
        "key": "ENT2", "name": "Entitlements", "owner": "M. Okonjo",
        "templates": [], "bindings": [],
    }
    response = await client.post(
        f"/api/onboarding/{draft['id']}/accept", json=body, headers=admin
    )
    assert response.status_code == 409


async def test_discovery_requires_a_session(client):
    response = await client.post("/api/onboarding/discover", json={"hint": "Retail Onboarding"})
    assert response.status_code == 401


async def test_a_slot_can_fill_more_than_its_own_identifier(client, admin):
    """The LinearB team id and the repos it covers are one slot but two values in the query.

    A repo list carried over from the exemplar would scope a new team's PR metrics to another
    team's repositories — and PR counts are meaningless without knowing which repos were in scope.
    """
    draft = await _discover(client, admin, "Retail Onboarding")

    prs = _binding(draft, "delivery", "PR size & latency")
    assert "teamIds=631" in prs["query"]
    assert "repos: RTO, RTO-BFF" in prs["query"]
    assert "APPR" not in prs["query"]


async def test_a_template_naming_nothing_team_specific_says_so(client, admin):
    draft = await _discover(client, admin, "Retail Onboarding")

    release = next(t for t in draft["templates"] if t["template_key"] == "release")
    assert release["propose_enabled"] is False
    assert "team-specific" in release["reason"]
    assert all(b["generic"] for b in release["bindings"])
