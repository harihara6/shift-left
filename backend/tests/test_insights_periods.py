"""Team Insights over an arbitrary reporting window."""

ENT = "/api/projects/entitlements"


async def test_default_window_is_the_current_period_against_the_previous(client, admin):
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    comparison = payload["comparison"]
    assert comparison["current"]["key"] == "Q3-2026"
    assert comparison["baseline"]["key"] == "Q2-2026"
    assert comparison["preset"] == "previous"


async def test_no_period_is_hardcoded_in_the_labels(client, admin):
    """Ask for a different window and every label follows it."""
    payload = (
        await client.get(
            f"{ENT}/team-insights?preset=custom&period=Q1-2026&baseline=Q4-2025", headers=admin
        )
    ).json()
    labels = [tile["label"] for section in payload["sections"] for tile in section["tiles"]]
    assert any("Q1 2026" in label for label in labels)
    assert any("Q4 2025" in label for label in labels)
    assert not any("Q3 2026" in label or "Q2 2026" in label for label in labels)


async def test_counts_are_compared_as_rates_when_the_windows_differ(client, admin):
    """6 epics against 10 is -40% as a count and -10% per week. The rate is what gets judged."""
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    epics = next(row for row in payload["glance"] if row["row"] == "Epics done")
    reason = " ".join(epics["status"]["reasons"])
    assert "/wk" in reason
    assert "rate, not raw count" in reason


async def test_equal_windows_drop_the_rate_caveat(client, admin):
    payload = (
        await client.get(
            f"{ENT}/team-insights?preset=custom&period=Q1-2026&baseline=Q4-2025", headers=admin
        )
    ).json()
    assert payload["comparison"]["comparable_lengths"] is True
    assert "compare directly" in payload["comparison_caveat"]


async def test_partial_period_reports_only_the_weeks_it_has(client, admin):
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    current = payload["comparison"]["current"]
    assert current["complete"] is False
    assert current["weeks"] == 8.7


async def test_half_and_year_aggregate_their_quarters(client, admin):
    year = (await client.get(f"{ENT}/team-insights?granularity=year", headers=admin)).json()
    assert year["comparison"]["aggregated"] is True
    assert year["comparison"]["covered_periods"] == ["Q1-2026", "Q2-2026", "Q3-2026"]

    quarters = [
        (await client.get(f"{ENT}/team-insights?preset=custom&period={key}", headers=admin)).json()
        for key in ("Q1-2026", "Q2-2026", "Q3-2026")
    ]

    def throughput(payload):
        return next(
            t for t in payload["sections"][0]["tiles"]
            if t["label"].endswith("throughput") and payload["comparison"]["current"]["label"] in t["label"]
        )["value"]

    assert int(throughput(year)) == sum(int(throughput(q)) for q in quarters)


async def test_an_aggregate_states_that_it_has_no_median_rather_than_inventing_one(client, admin):
    payload = (await client.get(f"{ENT}/team-insights?granularity=year", headers=admin)).json()
    assert any("not recoverable" in tile["note"] for tile in payload["sections"][0]["tiles"])
    assert any("average of medians is not a median" in note for note in payload["notes"])


async def test_same_period_last_year_is_offered_and_resolves(client, admin):
    payload = (await client.get(f"{ENT}/team-insights?preset=last_year", headers=admin)).json()
    assert payload["comparison"]["baseline"]["key"] == "Q3-2025"


async def test_a_window_with_no_snapshot_is_a_gap(client, admin):
    response = await client.get(
        f"{ENT}/team-insights?granularity=year&preset=custom&period=Y-2023", headers=admin
    )
    assert response.status_code == 404
    assert "gap" in response.json()["detail"]


async def test_a_missing_baseline_still_renders_the_current_window(client, admin):
    """Losing the comparison is not losing the page — the statuses just say they have no baseline."""
    payload = (
        await client.get(
            f"{ENT}/team-insights?preset=custom&period=Q1-2025&baseline=Y-2023", headers=admin
        )
    ).json()
    assert payload["comparison"]["baseline"]["has_data"] is False
    assert any("nothing on this page has a baseline" in note for note in payload["notes"])
    statuses = [t["status"] for s in payload["sections"] for t in s["tiles"] if t["status"]]
    assert any(s["rag"] == "neutral" for s in statuses)


async def test_filter_options_flag_periods_without_data(client, admin):
    options = (await client.get(f"{ENT}/periods", headers=admin)).json()
    assert options["data_through"] == "2026-08-30"
    assert [g["key"] for g in options["granularities"]] == ["quarter", "half", "year"]
    assert {p["key"] for p in options["presets"]} == {"previous", "last_year", "custom"}
    years = {p["key"]: p["has_data"] for p in options["periods"]["year"]}
    assert years["Y-2026"] is True
    assert years["Y-2023"] is False


async def test_period_options_are_authorization_scoped(client, stranger):
    assert (await client.get(f"{ENT}/periods", headers=stranger)).status_code == 404


async def test_every_rag_state_still_carries_reasons_naming_its_threshold(client, admin):
    payload = (await client.get(f"{ENT}/team-insights", headers=admin)).json()
    statuses = [t["status"] for s in payload["sections"] for t in s["tiles"] if t["status"]]
    judged = [s for s in statuses if s["rag"] in ("good", "watch", "poor")]
    assert judged
    for status in judged:
        reasons = " ".join(status["reasons"])
        assert "On track" in reasons or "no baseline" in reasons
