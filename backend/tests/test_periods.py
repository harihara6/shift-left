"""The fiscal calendar, and the comparisons built on it."""

from datetime import date

import pytest

from app.services import periods

TODAY = date(2026, 9, 10)
THROUGH = date(2026, 8, 30)


def test_current_quarter_is_clamped_to_the_data_it_has():
    """A period in progress is only as long as its data - otherwise a partial quarter reads
    as a throughput collapse."""
    quarter = periods.current(periods.QUARTER, TODAY, THROUGH)
    assert quarter.key == "Q3-2026"
    assert quarter.start == date(2026, 7, 1)
    assert quarter.end == date(2026, 9, 30)
    assert quarter.effective_end == THROUGH
    assert quarter.complete is False
    assert quarter.weeks == 8.7


def test_completed_quarter_uses_its_full_window():
    quarter = periods.previous(periods.current(periods.QUARTER, TODAY, THROUGH), THROUGH)
    assert quarter.key == "Q2-2026"
    assert quarter.complete is True
    assert quarter.weeks == 13.0


@pytest.mark.parametrize(
    ("granularity", "expected", "baseline"),
    [
        (periods.QUARTER, "Q3-2026", "Q2-2026"),
        (periods.HALF, "H2-2026", "H1-2026"),
        (periods.YEAR, "Y-2026", "Y-2025"),
    ],
)
def test_default_is_always_current_against_previous(granularity, expected, baseline):
    comparison = periods.resolve(granularity, "previous", TODAY, THROUGH)
    assert comparison.current.key == expected
    assert comparison.baseline.key == baseline


@pytest.mark.parametrize(
    ("granularity", "baseline"),
    [(periods.QUARTER, "Q3-2025"), (periods.HALF, "H2-2025"), (periods.YEAR, "Y-2025")],
)
def test_same_period_last_year_preset(granularity, baseline):
    comparison = periods.resolve(granularity, "last_year", TODAY, THROUGH)
    assert comparison.baseline.key == baseline


def test_custom_range_takes_both_sides():
    comparison = periods.resolve(
        periods.QUARTER, "custom", TODAY, THROUGH, current_key="Q1-2026", baseline_key="Q3-2025"
    )
    assert (comparison.current.key, comparison.baseline.key) == ("Q1-2026", "Q3-2025")


def test_year_boundary_rolls_back_correctly():
    q1 = periods.parse("Q1-2026", TODAY, THROUGH)
    assert periods.previous(q1, THROUGH).key == "Q4-2025"


def test_caveat_warns_only_when_the_windows_differ():
    differing = periods.resolve(periods.QUARTER, "previous", TODAY, THROUGH)
    assert differing.comparable_lengths is False
    assert "compare rates, not raw counts" in differing.caveat

    matching = periods.resolve(
        periods.QUARTER, "custom", TODAY, THROUGH, current_key="Q1-2026", baseline_key="Q4-2025"
    )
    assert matching.comparable_lengths is True
    assert "compare directly" in matching.caveat


def test_a_half_is_made_of_its_quarters():
    half = periods.parse("H1-2026", TODAY, THROUGH)
    assert [q.key for q in periods.constituent_quarters(half, THROUGH)] == ["Q1-2026", "Q2-2026"]


def test_quarters_that_have_not_started_are_not_counted_as_gaps():
    """H2 2026 is Q3 and Q4; Q4 has not begun, so it is absent rather than missing."""
    half = periods.current(periods.HALF, TODAY, THROUGH)
    assert [q.key for q in periods.constituent_quarters(half, THROUGH)] == ["Q3-2026"]


@pytest.mark.parametrize("bad", ["", "nonsense", "Q9-2026", "Q1-notayear", "X-2026"])
def test_unparseable_period_keys_are_rejected(bad):
    assert periods.parse(bad, TODAY, THROUGH) is None


def test_unknown_selection_falls_back_to_the_default_rather_than_failing():
    comparison = periods.resolve("fortnight", "sideways", TODAY, THROUGH)
    assert comparison.granularity == periods.QUARTER
    assert comparison.current.key == "Q3-2026"
    assert comparison.baseline.key == "Q2-2026"
