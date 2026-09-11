"""Feature Kickoff: the rules are the product's, not the endpoint's.

What runs is decided from what the PRD says, and every decision carries its reason. Nothing that
should run is skipped silently, nothing is called feasible, every fact and plan item traces back
to a source, and nothing is written until a named person confirms it.
"""

import httpx
import pytest

ENT = "/api/projects/entitlements"
PAY = "/api/projects/db-payments"
NUC = "/api/projects/nucleus"

EU_PAYMENTS = "7340021"   # Instant credit transfers, NL and DE
UK_AIS = "7418806"        # Account information API for TPPs, UK
COPY_CHANGE = "7502117"   # Wording on the confirmation screen


async def _start(client: httpx.AsyncClient, base: str, headers: dict, page_id: str) -> dict:
    response = await client.post(
        f"{base}/kickoff", headers=headers,
        json={"page_id": page_id, "provider": "rules", "model": "rules"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _action(session: dict, key: str) -> dict:
    return next(a for a in session["actions"] if a["key"] == key)


def _fact(session: dict, key: str) -> dict:
    return next(f for f in session["facts"] if f["key"] == key)


async def _choose(client, base, headers, session, **overrides) -> httpx.Response:
    """Keep every default choice, except the overrides: key=(selected, skip_reason)."""
    choices = []
    for action in session["actions"]:
        selected, reason = overrides.get(action["key"], (action["selected"], ""))
        choices.append({"key": action["key"], "selected": selected, "skip_reason": reason})
    return await client.put(f"{base}/kickoff/{session['id']}/actions", headers=headers,
                            json={"choices": choices})


# --- Reading ----------------------------------------------------------------------------------


async def test_every_stated_fact_quotes_a_sentence_that_is_in_the_prd(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)
    prd_lines = [
        line.removeprefix("- ") for line in (await _prd_body(EU_PAYMENTS)) if not line.startswith("## ")
    ]
    for fact in session["facts"]:
        if fact["status"] == "stated":
            assert fact["quotes"], fact["key"]
            for quote in fact["quotes"]:
                assert quote["text"] in prd_lines, (fact["key"], quote)
        else:
            assert fact["values"] == []

    assert set(_fact(session, "regions")["values"]) == {"NL", "DE"}
    assert _fact(session, "third_party_access")["values"] == ["none"]
    assert session["reader"] == "rules"
    assert session["drafted_by"] == "Rule-based reader"


async def _prd_body(page_id: str) -> list[str]:
    from app.services import kickoff_sources

    return (await kickoff_sources.prd(page_id))["body"]


async def test_the_model_list_comes_from_the_providers_and_says_what_is_missing(client, admin):
    options = (await client.get(f"{PAY}/kickoff/models", headers=admin)).json()
    providers = {p["key"]: p for p in options["providers"]}

    # No key in tests: Claude is listed as unavailable with the reason, never silently absent.
    assert providers["claude"]["available"] is False
    assert "SHIFTLEFT_ANTHROPIC_API_KEY" in providers["claude"]["note"]
    assert providers["cursor"]["available"] is False
    assert providers["rules"]["available"] is True
    assert options["default_provider"] == "rules"


async def test_an_unavailable_model_is_refused_rather_than_quietly_swapped(client, admin):
    response = await client.post(
        f"{PAY}/kickoff", headers=admin,
        json={"page_id": EU_PAYMENTS, "provider": "claude", "model": "claude-opus-5"},
    )
    assert response.status_code == 422
    assert "isn't available" in response.json()["detail"]


# --- What runs is decided by the PRD --------------------------------------------------------------


async def test_an_eu_payments_prd_gets_iso20022_but_not_open_banking_standards(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)

    assert _action(session, "std_iso20022")["outcome"] == "applies"
    berlin = _action(session, "std_berlin_group")
    assert berlin["outcome"] == "not_applicable"
    # Ruled out by a named fact, and the reason says which.
    assert "Third-party access: None" in berlin["reason"]
    assert _action(session, "std_obie")["outcome"] == "not_applicable"
    assert _action(session, "std_fdx")["outcome"] == "not_applicable"
    assert session["tier"]["tier"] == "New capability"


async def test_a_uk_third_party_api_gets_open_banking_and_not_berlin_group(client, admin):
    session = await _start(client, ENT, admin, UK_AIS)

    assert _action(session, "std_obie")["outcome"] == "applies"
    assert "United Kingdom" in _action(session, "std_berlin_group")["reason"]
    assert _action(session, "std_berlin_group")["outcome"] == "not_applicable"
    assert _action(session, "std_iso20022")["outcome"] == "not_applicable"
    assert _action(session, "std_bian")["outcome"] == "applies"
    assert _action(session, "software_catalog")["outcome"] == "applies"
    assert session["tier"]["tier"] == "Major change"


async def test_a_copy_change_runs_almost_nothing_and_says_why(client, admin):
    session = await _start(client, NUC, admin, COPY_CHANGE)

    applies = {a["key"] for a in session["actions"] if a["outcome"] != "not_applicable"}
    assert applies == {"jira_backlog", "xray_plan", "feasibility_page"}
    assert all(a["reason"] for a in session["actions"])
    assert session["tier"]["tier"] == "Config / copy"


async def test_a_missing_fact_runs_the_check_and_asks_the_question(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)

    # The PRD never says whether it adds an API: undetermined runs, with a question.
    bian = _action(session, "std_bian")
    assert bian["outcome"] == "undetermined"
    assert bian["recommended"] is True and bian["selected"] is True
    assert bian["question"]
    # Nor does it name the scheme that carries the payments.
    assert _action(session, "third_party_check")["outcome"] == "undetermined"


async def test_correcting_a_fact_re_resolves_the_rules_and_is_attributed(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)
    response = await client.put(
        f"{PAY}/kickoff/{session['id']}/facts", headers=admin,
        json={"facts": [{"key": "introduces_api", "values": ["no"]}]},
    )
    assert response.status_code == 200, response.text
    updated = response.json()

    assert _action(updated, "std_bian")["outcome"] == "not_applicable"
    assert _fact(updated, "introduces_api")["status"] == "confirmed"
    assert _fact(updated, "introduces_api")["confirmed_by"] == admin["X-ShiftLeft-User"]


async def test_a_fact_outside_the_vocabulary_is_refused(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)
    response = await client.put(
        f"{PAY}/kickoff/{session['id']}/facts", headers=admin,
        json={"facts": [{"key": "regions", "values": ["Atlantis"]}]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["blockers"]


# --- Choosing: scoped-out is not passed ------------------------------------------------------------


async def test_leaving_a_recommended_action_out_needs_a_reason(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)

    refused = await _choose(client, PAY, admin, session, std_iso20022=(False, ""))
    assert refused.status_code == 409
    assert any("ISO 20022" in b for b in refused.json()["detail"]["blockers"])

    accepted = await _choose(client, PAY, admin, session,
                             std_iso20022=(False, "Covered by the payments platform's own mapping"))
    assert accepted.status_code == 200
    iso = _action(accepted.json(), "std_iso20022")
    assert iso["selected"] is False
    assert iso["skip_reason"].startswith("Covered")


async def test_a_deny_listed_reason_is_recorded_but_flagged(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)
    response = await _choose(client, PAY, admin, session,
                             std_iso20022=(False, "Capacity pressure this sprint"))
    assert response.status_code == 200
    assert _action(response.json(), "std_iso20022")["skip_flagged"] is True


# --- Checks: never "feasible" -----------------------------------------------------------------------


async def test_a_missing_operation_is_a_blocker_with_a_link_and_a_dependency_suggestion(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)
    planned = (await _choose(client, PAY, admin, session)).json()

    dependency = next(c for c in planned["checks"] if c["key"] == "dependency_check")
    blocker = next(f for f in dependency["findings"] if f["status"] == "blocker")
    assert "POST /payment-orders/instant" in blocker["title"]
    assert "/blob/4f2c9e1/" in blocker["link"]["url"]  # the spec at the commit it was read at
    assert planned["headline"]["rag"] == "poor"
    assert any(s["key"].startswith("dependency:payment-order-service") for s in planned["suggestions"])


async def test_the_headline_never_says_feasible_and_lists_what_was_not_checked(client, admin):
    session = await _start(client, ENT, admin, UK_AIS)
    planned = (await _choose(client, ENT, admin, session)).json()

    reasons = " ".join(planned["headline"]["reasons"])
    assert "feasible" not in reasons.lower()
    assert "Not checked:" in reasons
    # transaction-service isn't in the catalog, so it can't be read: a gap, never a pass.
    dependency = next(c for c in planned["checks"] if c["key"] == "dependency_check")
    unchecked = [f for f in dependency["findings"] if f["status"] == "not_checked"]
    assert any("transaction-service" in f["title"] for f in unchecked)
    # And a deprecated operation is a gap, not an ok.
    assert any(f["status"] == "gap" and "deprecated" in f["title"] for f in dependency["findings"])


async def test_an_unpinned_standard_is_not_checked_rather_than_passed(client, admin):
    session = await _start(client, ENT, admin, UK_AIS)
    # Ask for FDX even though it doesn't apply: it still can't be checked, and says so.
    planned = (await _choose(client, ENT, admin, session, std_fdx=(True, ""))).json()
    fdx = next(c for c in planned["checks"] if c["key"] == "std_fdx")
    assert [f["status"] for f in fdx["findings"]] == ["not_checked"]


# --- The plan -----------------------------------------------------------------------------------------


async def test_every_plan_item_says_what_it_was_drawn_from(client, admin):
    session = await _start(client, ENT, admin, UK_AIS)
    planned = (await _choose(client, ENT, admin, session)).json()

    items = planned["plan"]["items"]
    assert items
    assert all(item["drawn_from"] for item in items), [i["id"] for i in items if not i["drawn_from"]]
    tests = [i for i in items if i["kind"] == "Test"]
    assert len(tests) == 4  # one per acceptance criterion
    epic = next(i for i in items if i["id"] == "epic")
    assert "shiftleft-tracked" in epic["labels"]


async def test_every_artifact_the_tier_requires_is_covered_or_ruled_out_with_a_reason(client, admin):
    session = await _start(client, ENT, admin, UK_AIS)
    planned = (await _choose(client, ENT, admin, session)).json()

    coverage = {c["artifact"]: c for c in planned["plan"]["coverage"]}
    assert len(coverage) == 11
    # API only: accessibility is ruled out by the channel fact, not quietly dropped.
    assert coverage["accessibility"]["state"] == "not_applicable"
    assert coverage["accessibility"]["note"]
    assert all(c["state"] == "covered" for k, c in coverage.items() if k != "accessibility")


async def test_a_copy_change_scopes_down_as_waiver_drafts_not_silence(client, admin):
    session = await _start(client, NUC, admin, COPY_CHANGE)
    planned = (await _choose(client, NUC, admin, session)).json()

    coverage = {c["artifact"]: c for c in planned["plan"]["coverage"]}
    assert coverage["acceptance_criteria"]["state"] == "covered"
    assert coverage["hld"]["state"] == "waiver_draft"
    waiver = next(i for i in planned["plan"]["items"] if i["id"] == "waiver:hld")
    assert "Capacity pressure" in waiver["detail"]


async def test_accepting_a_recommended_step_adds_it_to_the_plan(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)
    await _choose(client, PAY, admin, session)
    response = await client.put(
        f"{PAY}/kickoff/{session['id']}/plan", headers=admin,
        json={"decisions": {"hld_page": "accepted", "lld_page": "dismissed"}},
    )
    assert response.status_code == 200, response.text
    ids = {i["id"] for i in response.json()["plan"]["items"]}
    assert "suggestion:hld_page" in ids
    assert "suggestion:lld_page" not in ids


async def test_the_catalog_is_changed_by_diff_against_the_version_read(client, admin):
    session = await _start(client, ENT, admin, UK_AIS)
    planned = (await _choose(client, ENT, admin, session)).json()

    rows = [i for i in planned["plan"]["items"] if i["group"] == "software_catalog"]
    added = next(r for r in rows if r["diff"]["op"] == "add")
    assert added["diff"]["fields"]["name"] == "Account Information API"
    assert "UK Open Banking (OBIE)" in added["diff"]["fields"]["standards"]
    assert planned["plan"]["catalog_version"] == 31


# --- Confirming ---------------------------------------------------------------------------------------


async def test_nothing_is_created_until_a_named_person_confirms_and_then_only_as_a_dry_run(client, admin):
    session = await _start(client, PAY, admin, EU_PAYMENTS)
    assert session["results"] == [] and session["approved_by"] is None

    early = await client.post(f"{PAY}/kickoff/{session['id']}/apply", headers=admin)
    assert early.status_code == 409  # no plan yet

    planned = (await _choose(client, PAY, admin, session)).json()
    left_out = planned["plan"]["items"][-1]["id"]
    await client.put(f"{PAY}/kickoff/{session['id']}/plan", headers=admin, json={"excluded": [left_out]})

    applied = (await client.post(f"{PAY}/kickoff/{session['id']}/apply", headers=admin)).json()
    assert applied["status"] == "applied"
    assert applied["approved_by"] == admin["X-ShiftLeft-User"]
    assert applied["write_mode"] == "dry-run"
    by_id = {r["item_id"]: r for r in applied["results"]}
    assert by_id[left_out]["status"] == "skipped"
    assert all(r["message"].startswith("Would ") for r in applied["results"] if r["status"] == "dry_run")

    again = await client.post(f"{PAY}/kickoff/{session['id']}/apply", headers=admin)
    assert again.status_code == 409


async def test_the_confirmation_is_audited_with_the_model_that_drafted_it(client, admin):
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.audit import AuditLog

    session = await _start(client, PAY, admin, EU_PAYMENTS)
    await _choose(client, PAY, admin, session)
    await client.post(f"{PAY}/kickoff/{session['id']}/apply", headers=admin)

    async with SessionLocal() as db:
        entries = (await db.execute(
            select(AuditLog).where(AuditLog.resource_type == "kickoff_session")
        )).scalars().all()
    actions = {e.action: e for e in entries}
    assert set(actions) == {"kickoff_start", "kickoff_apply"}
    assert actions["kickoff_apply"].detail["model"] == "rules"
    assert actions["kickoff_apply"].detail["mode"] == "dry-run"


# --- Access -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["viewer", "stranger"])
async def test_kickoff_needs_a_contributor_on_the_project(client, request, who):
    headers = request.getfixturevalue(who)
    assert (await client.get(f"{ENT}/kickoff/prds", headers=headers)).status_code == 404
    response = await client.post(
        f"{ENT}/kickoff", headers=headers, json={"page_id": UK_AIS, "provider": "rules", "model": "rules"}
    )
    assert response.status_code == 404


async def test_a_kickoff_is_private_to_whoever_ran_it(client, admin, contributor):
    session = await _start(client, ENT, contributor, UK_AIS)
    other = {"X-ShiftLeft-User": "dev2@backbase.com", "X-ShiftLeft-Groups": "bb-eng-entitlements"}

    assert (await client.get(f"{ENT}/kickoff/{session['id']}", headers=other)).status_code == 404
    assert (await client.post(f"{ENT}/kickoff/{session['id']}/apply", headers=other)).status_code == 404
    # The audited platform-admin set can still read it, as with onboarding drafts.
    assert (await client.get(f"{ENT}/kickoff/{session['id']}", headers=admin)).status_code == 200


async def test_a_session_cannot_be_reached_through_another_project(client, admin):
    session = await _start(client, ENT, admin, UK_AIS)
    assert (await client.get(f"{PAY}/kickoff/{session['id']}", headers=admin)).status_code == 404


# --- The model proposes; the sanitizer decides ------------------------------------------------------


def test_model_output_outside_the_vocabulary_or_the_prd_is_dropped():
    from app.services.kickoff_extract import ExtractedFact, Extraction, _sanitize, lines_of

    lines = lines_of(["## Summary", "Customers in the Netherlands can send transfers."])
    extraction = Extraction(facts=[
        ExtractedFact(key="regions", values=["NL", "Atlantis"], line=1),  # one invented value
        ExtractedFact(key="domain", values=["payments"], line=42),         # a line that doesn't exist
        ExtractedFact(key="services", values=["made-up-service"], line=1),  # not a model fact
    ])
    facts = _sanitize(extraction, lines)

    assert facts["regions"].values == ["NL"]
    assert facts["regions"].quotes == [{"text": lines[0].text, "section": "Summary"}]
    assert facts["domain"].status == "not_stated" and facts["domain"].values == []
    assert "services" not in facts
