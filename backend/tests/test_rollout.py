"""The Shift-left Rollout board. A stage is earned against listed criteria, never assumed."""

import pytest

from app.services import rollout_rules

ENT = "/api/projects/entitlements"
PAY = "/api/projects/db-payments"
NUC = "/api/projects/nucleus"


async def _board(client, headers, base=ENT) -> dict:
    response = await client.get(f"{base}/rollout", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_every_status_carries_reasons_and_a_glyph(client, admin):
    board = await _board(client, admin)
    states = [t["status"] for t in board["tiles"]]
    states += [s["status"] for s in board["surfaces"]]
    states += [d["status"] for d in board["detectors"]]
    states += [c["status"] for stage in board["stages"] for c in stage["criteria"]]
    assert states
    for state in states:
        assert state["reasons"], "no status is ever reduced to a colour"
        assert state["glyph"], "colour is never the only carrier (WCAG 2.2 AA)"


async def test_the_pilot_is_blocked_by_a_listed_criterion_not_a_flag(client, admin):
    board = await _board(client, admin)
    assert board["stage_label"] == "Warn"
    assert board["can_advance"] is False
    assert board["advance_blockers"] == [
        "The team agrees the reasons are fair: No sign-off recorded. The team's ETL records it on "
        "this board."
    ]
    current = next(s for s in board["stages"] if s["state"] == "current")
    assert [c["met"] for c in current["criteria"]] == [True, True, False]

    refused = await client.post(f"{ENT}/rollout/advance", headers=admin, json={})
    assert refused.status_code == 409
    assert refused.json()["detail"]["blockers"] == board["advance_blockers"]


async def test_signoff_then_advance_moves_the_stage_and_resets_signoff(client, admin, contributor):
    signed = await client.post(f"{ENT}/rollout/signoff", headers=contributor)
    assert signed.status_code == 200
    board = signed.json()
    assert board["signoff"]["by"] == "dev@backbase.com"
    assert board["can_advance"] is True
    assert board["advance_blockers"] == []

    advanced = await client.post(f"{ENT}/rollout/advance", headers=admin, json={"note": "pilot ok"})
    assert advanced.status_code == 200
    after = advanced.json()
    assert after["stage_label"] == "Soft gate"
    # Sign-off belonged to Warn; Soft gate has its own criteria.
    assert after["signoff"]["by"] is None
    # The gating surfaces still warn, and Soft gate expects them to block. The board says so.
    validator = next(s for s in after["surfaces"] if s["key"] == "transition_validator")
    assert validator["status"]["rag"] == "poor"
    assert "expects block" in validator["status"]["reasons"][0]


async def test_rollback_needs_a_reason_and_is_always_allowed(client, admin):
    blank = await client.post(f"{ENT}/rollout/rollback", headers=admin, json={"note": " "})
    assert blank.status_code == 422
    rolled = await client.post(
        f"{ENT}/rollout/rollback", headers=admin, json={"note": "Validator blocked a hotfix"}
    )
    assert rolled.status_code == 200
    assert rolled.json()["stage_label"] == "Observe"
    again = await client.post(f"{ENT}/rollout/rollback", headers=admin, json={"note": "again"})
    assert again.status_code == 409


async def test_signoff_only_applies_at_warn(client, admin):
    response = await client.post(f"{PAY}/rollout/signoff", headers=admin)
    assert response.status_code == 409
    assert "Warn" in response.json()["detail"]


async def test_unmeasured_is_missing_never_green(client, admin):
    board = await _board(client, admin, NUC)
    tiles = {t["label"]: t for t in board["tiles"]}
    assert tiles["Detection accuracy"]["status"]["rag"] == "missing"
    assert tiles["Detection accuracy"]["drill"] is None, "no audit means no record to open"
    assert tiles["False-red rate"]["status"]["rag"] == "missing"
    assert board["detectors"] == [] and board["charts"] == []
    assert "not the same as accurate" in board["audit_note"]
    panel = next(s for s in board["surfaces"] if s["key"] == "jira_panel")
    assert panel["status"]["rag"] == "poor", "Observe depends on the panel being on"


async def test_correctly_off_is_not_healthy(client, admin):
    board = await _board(client, admin, PAY)
    off = [s for s in board["surfaces"] if s["mode"] == "off"]
    assert off
    assert all(s["status"]["rag"] == "neutral" for s in off)


async def test_a_stale_source_cannot_contribute_to_green(client, admin):
    """Xray is past its threshold in the fixture. Detectors reading it may not read green."""
    board = await _board(client, admin)
    xray = [d for d in board["detectors"] if d["source"] == "xray"]
    assert xray
    for detector in xray:
        assert detector["status"]["rag"] != "good"
        assert any("threshold" in r for r in detector["status"]["reasons"])
    # A widget that doesn't read Xray is not held back by it.
    pr_check = next(s for s in board["surfaces"] if s["key"] == "pr_check")
    assert pr_check["status"]["rag"] == "good"


async def test_the_chart_and_the_audit_tell_the_same_story(client, admin):
    for base in (ENT, PAY):
        board = await _board(client, admin, base)
        accuracy = next(c for c in board["charts"] if c["key"] == "accuracy")
        tile = next(t for t in board["tiles"] if t["label"] == "Detection accuracy")
        assert f"{accuracy['series'][0]['data'][-1]:g}%" == tile["value"]


async def test_warning_outcomes_are_absent_before_warn_not_zero(client, admin):
    board = await _board(client, admin, PAY)
    assert [c["key"] for c in board["charts"]] == ["accuracy"]
    ent = await _board(client, admin)
    outcomes = next(c for c in ent["charts"] if c["key"] == "outcomes")
    assert len(outcomes["x_labels"]) == 2, "only sprints spent at Warn carry outcomes"


async def test_every_metric_drills_down(client, admin):
    board = await _board(client, admin)
    assert all(t["drill"] for t in board["tiles"])
    assert all(d["drill"] for d in board["detectors"])
    assert all(s["drill"] for s in board["surfaces"])


async def test_an_unenrolled_project_is_a_gap(client, admin):
    response = await client.get("/api/projects/platform-programme/rollout", headers=admin)
    assert response.status_code == 404
    assert "gap, not a pass" in response.json()["detail"]


async def test_writes_are_authorization_scoped(client, viewer, contributor, stranger):
    assert (await client.get(f"{ENT}/rollout", headers=stranger)).status_code == 404
    assert (await client.get(f"{ENT}/rollout", headers=viewer)).status_code == 200
    assert (await client.post(f"{ENT}/rollout/signoff", headers=viewer)).status_code == 404
    assert (await client.post(f"{ENT}/rollout/advance", headers=contributor, json={})).status_code == 404
    assert (
        await client.post(f"{ENT}/rollout/rollback", headers=contributor, json={"note": "x"})
    ).status_code == 404
    assert (await client.get(f"{PAY}/rollout", headers=viewer)).status_code == 404


async def test_every_rendered_widget_has_its_four_guide_fields(client, admin):
    guide = (await client.get("/api/guides/rollout", headers=admin)).json()
    keys = {w["widget_key"] for w in guide["widgets"]}
    assert keys == {"gating_path", "rollout_tiles", "surfaces", "detectors", "rollout_charts"}
    for widget in guide["widgets"]:
        assert widget["decision"] and widget["source"] and widget["fetch"] and widget["tagging"]


@pytest.mark.parametrize(
    ("mode", "stage", "rag"),
    [
        ("block", 1, "poor"), ("warn", 1, "good"), ("off", 1, "poor"), ("off", 0, "neutral"),
        ("warn", 2, "poor"),
    ],
)
def test_a_gating_surface_does_what_its_stage_says(mode, stage, rag):
    state = rollout_rules.surface_status(
        name="Check", gating=True, from_stage=1, mode=mode, stage=stage, coverage_done=1,
        coverage_total=1, coverage_unit="repos", gap_note="", age_minutes=5,
        expected_every_minutes=60, age_label="5m ago",
    )
    assert state.rag == rag
