"""The evidence record's rules. These are the ones the product exists to enforce."""

ENT = "/api/projects/entitlements"


async def _page(client, headers) -> dict:
    response = await client.get(f"{ENT}/feature-readiness", headers=headers)
    assert response.status_code == 200
    return response.json()


async def test_status_resolves_to_a_list_of_artifacts_never_a_score(client, admin):
    page = await _page(client, admin)
    red = [f for f in page["features"] if f["status"]["rag"] == "poor"]
    assert red, "the fixture should hold at least one feature short of its gate"
    for feature in red:
        assert feature["missing"], "a red feature names the artifacts that are absent"
        assert feature["status"]["reasons"] == feature["missing"]
        # The reason is the artifact, its accountable owner and the gate it was due at.
        assert all("due at" in reason for reason in feature["status"]["reasons"])
    for feature in page["features"]:
        assert feature["status"]["reasons"], "no status is ever reduced to a colour"
        assert feature["status"]["glyph"], "colour is never the only carrier (WCAG 2.2 AA)"


async def test_waived_artifacts_leave_the_denominator_and_are_reported(client, admin):
    page = await _page(client, admin)
    waived = {(w["feature_key"], w["artifact"]) for w in page["waivers"]}
    assert waived, "the fixture should hold scoped-out artifacts"

    feature = next(f for f in page["features"] if f["key"] == "ENT-401")
    scoped_out = [a for a in feature["artifacts"] if a["status_label"] == "Scoped out"]
    assert scoped_out
    for artifact in scoped_out:
        # Out of the denominator, so the percentage stays honest...
        assert artifact["counts_toward_gate"] is False
        # ...and never rendered as a pass.
        assert artifact["status"]["rag"] == "neutral"
    assert feature["done"]["total"] == len(
        [a for a in feature["artifacts"] if a["counts_toward_gate"]]
    )

    for waiver in page["waivers"]:
        assert waiver["owner"] and waiver["waived_at"] and waiver["rationale"]


async def test_a_deny_listed_rationale_is_flagged_not_quietly_accepted(client, admin):
    page = await _page(client, admin)
    flagged = [w for w in page["waivers"] if w["flagged"]]
    assert flagged, "'capacity pressure' is not a reason to scope an artifact out"
    assert all("capacity pressure" in w["rationale"].lower() for w in flagged)
    assert all(w["flag_note"] for w in flagged)


async def test_missing_artifacts_are_never_green_and_offer_no_dead_link(client, admin):
    page = await _page(client, admin)
    rows = [a for f in page["features"] for a in f["artifacts"]]
    missing = [a for a in rows if a["status_label"] == "Missing"]
    assert missing
    for artifact in missing:
        assert artifact["status"]["rag"] == "missing"
        assert artifact["drill"] is None, "there is no record to open, so no link is offered"
    for artifact in [a for a in rows if a["status_label"] in ("Present", "Stale", "Drafted")]:
        assert artifact["drill"], "a widget without a source link is a claim, not a signal"


async def test_a_stale_source_cannot_contribute_to_green(client, admin):
    """Xray is 4h past a 30-minute threshold in the fixture; nothing on the page may read green."""
    page = await _page(client, admin)
    assert page["freshness"]["stale"] is True
    # Every artifact read through Xray that would otherwise be held now reads Stale. A missing
    # one stays missing - staleness never upgrades an absence.
    xray_backed = [
        a for f in page["features"] for a in f["artifacts"]
        if a["key"] in ("traceability", "test_evidence")
    ]
    assert xray_backed
    assert all(a["status_label"] in ("Stale", "Missing", "Scoped out") for a in xray_backed)
    assert any(a["status_label"] == "Stale" for a in xray_backed)

    statuses = [f["status"] for f in page["features"]]
    statuses += [t["status"] for t in page["tiles"] if t["status"]]
    assert all(s["rag"] != "good" for s in statuses)
    # Whatever held a status out of green, it says so in the reason list rather than in a colour.
    assert any(
        any("threshold" in reason for reason in s["reasons"]) for s in statuses
    ), "a downgrade has to say why"


async def test_ai_draft_counts_toward_nothing_until_a_named_person_accepts(client, admin):
    page = await _page(client, admin)
    feature = next(f for f in page["features"] if f["ai"])
    assert feature["ai"]["accepted"] is False
    assert feature["ai"]["accepted_by"] is None
    assert feature["ai"]["drawn_from"], "a draft always travels with the evidence it drew from"
    assert "counts toward no gate" in feature["ai"]["note"]

    before = feature["done"]["percent"]
    accepted = await client.post(
        f"{ENT}/features/{feature['key']}/ai-draft/accept", headers=admin
    )
    assert accepted.status_code == 200
    after = next(f for f in accepted.json()["features"] if f["key"] == feature["key"])
    assert after["ai"]["accepted_by"] == "h.nuti@backbase.com"
    assert after["ai"]["accepted_at"]
    # Acceptance is recorded; it does not silently move a gate.
    assert after["done"]["percent"] == before


async def test_acknowledging_records_a_person_and_does_not_resolve_the_signal(client, admin):
    page = await _page(client, admin)
    action = next(a for a in page["actions"] if a["status"] == "open")
    severity_before = action["severity"]["rag"]

    response = await client.post(f"{ENT}/actions/{action['id']}/acknowledge", headers=admin)
    assert response.status_code == 200
    acknowledged = response.json()
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_by"] == "h.nuti@backbase.com"
    # Acknowledging says someone has seen it, not that the evidence gap has closed.
    assert acknowledged["severity"]["rag"] == severity_before

    after = await _page(client, admin)
    assert next(a for a in after["actions"] if a["id"] == action["id"])["status"] == "acknowledged"


async def test_writes_on_the_record_are_authorization_scoped(client, viewer, stranger):
    """Evaluated at the API layer. A viewer may read the record and may not write to it."""
    page = await _page(client, viewer)
    action = next(a for a in page["actions"] if a["status"] == "open")
    assert (
        await client.post(f"{ENT}/actions/{action['id']}/acknowledge", headers=viewer)
    ).status_code == 404
    assert (
        await client.get(f"{ENT}/feature-readiness", headers=stranger)
    ).status_code == 404


async def test_the_record_links_to_the_flow_view_and_carries_its_release(client, admin):
    page = await _page(client, admin)
    assert page["evidence_of_record"] is True
    assert page["flow_link"]["perspective"] == "delivery"
    assert page["flow_link"]["project_id"] == "entitlements"
    assert page["release"] == "2026.3"


async def test_an_untracked_release_is_a_gap_not_an_empty_gate(client, admin):
    response = await client.get(f"{ENT}/feature-readiness?release=1999.1", headers=admin)
    assert response.status_code == 404
    assert "gap in tagging" in response.json()["detail"]


async def test_every_rendered_widget_has_its_four_guide_fields(client, admin):
    guide = (await client.get("/api/guides/discipline", headers=admin)).json()
    keys = {w["widget_key"] for w in guide["widgets"]}
    assert keys == {"completeness", "cleared", "readiness_table", "status_reason", "waivers", "actions"}
    for widget in guide["widgets"]:
        assert widget["decision"] and widget["source"] and widget["fetch"] and widget["tagging"]
