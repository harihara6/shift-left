"""The fiscal calendar, and the comparison windows built on it.

Nothing in the product should name a quarter literally. A page asks for "the current period and
the one before it" at some granularity, and this module resolves that against today's date.

Two things it is careful about:

* A period in progress is shorter than a completed one. Its window is clamped to how much data
  actually exists, so a partial quarter never looks like a collapse in throughput.
* Comparing windows of different lengths is only honest as a rate. `Comparison.caveat` says so
  when the windows differ, and says nothing when they match.
"""

from dataclasses import dataclass
from datetime import date, timedelta

# The fiscal year starts in January, so fiscal quarters are calendar quarters. Change this one
# constant if the finance calendar moves; nothing else knows the month names.
FISCAL_YEAR_START_MONTH = 1

QUARTER = "quarter"
HALF = "half"
YEAR = "year"
GRANULARITIES = (QUARTER, HALF, YEAR)

GRANULARITY_LABEL = {QUARTER: "Quarter", HALF: "Half", YEAR: "Year"}

# How many periods of each granularity a filter offers, counting back from the current one.
HISTORY_DEPTH = {QUARTER: 10, HALF: 6, YEAR: 4}


@dataclass(frozen=True)
class Period:
    key: str
    label: str
    granularity: str
    start: date
    end: date
    """The nominal end of the period, whether or not it has arrived."""
    effective_end: date
    """The last day data exists for. Equal to `end` once the period is complete."""

    @property
    def complete(self) -> bool:
        return self.effective_end >= self.end

    @property
    def days(self) -> int:
        return (self.effective_end - self.start).days + 1

    @property
    def weeks(self) -> float:
        return round(self.days / 7, 1)

    @property
    def window_label(self) -> str:
        span = f"{self.start:%b %-d} – {self.effective_end:%b %-d}"
        suffix = "" if self.complete else " so far"
        return f"{self.label} · {span} ({self.weeks} wks{suffix})"


def _fiscal_year_of(day: date) -> int:
    """The fiscal year a date falls in. With a January start this is just the calendar year."""
    return day.year if day.month >= FISCAL_YEAR_START_MONTH else day.year - 1


def _fiscal_month_index(day: date) -> int:
    """0-11, counting from the first month of the fiscal year."""
    return (day.month - FISCAL_YEAR_START_MONTH) % 12


def _month_start(fiscal_year: int, month_index: int) -> date:
    absolute = FISCAL_YEAR_START_MONTH - 1 + month_index
    return date(fiscal_year + absolute // 12, absolute % 12 + 1, 1)


def _day_before(day: date) -> date:
    return day - timedelta(days=1)


def _bounds(granularity: str, fiscal_year: int, index: int) -> tuple[date, date]:
    """Start and nominal end for the `index`-th period (0-based) of a fiscal year."""
    months = {QUARTER: 3, HALF: 6, YEAR: 12}[granularity]
    start = _month_start(fiscal_year, index * months)
    next_start = _month_start(fiscal_year, (index + 1) * months)
    return start, _day_before(next_start)


def _make(granularity: str, fiscal_year: int, index: int, data_through: date) -> Period:
    start, end = _bounds(granularity, fiscal_year, index)
    prefix = {QUARTER: f"Q{index + 1}", HALF: f"H{index + 1}", YEAR: "Y"}[granularity]
    key = f"{prefix}-{fiscal_year}"
    label = f"Y{fiscal_year}" if granularity == YEAR else f"{prefix} {fiscal_year}"
    return Period(
        key=key,
        label=str(fiscal_year) if granularity == YEAR else label,
        granularity=granularity,
        start=start,
        end=end,
        # Clamp to the data we actually hold: a period in progress is only as long as its data.
        effective_end=min(end, max(data_through, start)),
    )


def _index_of(granularity: str, day: date) -> tuple[int, int]:
    fiscal_year = _fiscal_year_of(day)
    month_index = _fiscal_month_index(day)
    divisor = {QUARTER: 3, HALF: 6, YEAR: 12}[granularity]
    return fiscal_year, month_index // divisor


def current(granularity: str, today: date, data_through: date | None = None) -> Period:
    fiscal_year, index = _index_of(granularity, today)
    return _make(granularity, fiscal_year, index, data_through or today)


def shift(period: Period, steps: int, data_through: date | None = None) -> Period:
    """Move `steps` periods back (negative) or forward (positive) at the same granularity."""
    per_year = {QUARTER: 4, HALF: 2, YEAR: 1}[period.granularity]
    fiscal_year, index = _index_of(period.granularity, period.start)
    absolute = fiscal_year * per_year + index + steps
    return _make(
        period.granularity,
        absolute // per_year,
        absolute % per_year,
        data_through or period.effective_end,
    )


def previous(period: Period, data_through: date | None = None) -> Period:
    return shift(period, -1, data_through)


def same_period_last_year(period: Period, data_through: date | None = None) -> Period:
    """The seasonal comparison: the same window one year back, not the window just before."""
    per_year = {QUARTER: 4, HALF: 2, YEAR: 1}[period.granularity]
    return shift(period, -per_year, data_through)


def parse(key: str, today: date, data_through: date | None = None) -> Period | None:
    prefix, _, year_text = key.partition("-")
    if not year_text.isdigit():
        return None
    fiscal_year = int(year_text)
    if prefix == "Y":
        return _make(YEAR, fiscal_year, 0, data_through or today)
    granularity = {"Q": QUARTER, "H": HALF}.get(prefix[:1])
    if granularity is None or not prefix[1:].isdigit():
        return None
    index = int(prefix[1:]) - 1
    limit = {QUARTER: 4, HALF: 2}[granularity]
    if not 0 <= index < limit:
        return None
    return _make(granularity, fiscal_year, index, data_through or today)


def recent(granularity: str, today: date, data_through: date | None = None) -> list[Period]:
    """The current period and its predecessors, newest first."""
    head = current(granularity, today, data_through)
    return [head] + [shift(head, -step, data_through) for step in range(1, HISTORY_DEPTH[granularity])]


def constituent_quarters(period: Period, data_through: date) -> list[Period]:
    """The quarters a half or year is made of - the unit facts are actually stored at."""
    if period.granularity == QUARTER:
        return [period]
    count = {HALF: 2, YEAR: 4}[period.granularity]
    fiscal_year, index = _index_of(period.granularity, period.start)
    first = index * count
    quarters = [_make(QUARTER, fiscal_year, first + offset, data_through) for offset in range(count)]
    # A quarter that has not started yet contributes nothing, and is not listed as a gap.
    return [q for q in quarters if q.start <= data_through]


@dataclass(frozen=True)
class Comparison:
    """Two periods, and what is honest to say about putting them side by side."""

    current: Period
    baseline: Period
    granularity: str
    preset: str

    @property
    def comparable_lengths(self) -> bool:
        # Within half a week of each other reads as the same window.
        return abs(self.current.weeks - self.baseline.weeks) <= 0.5

    @property
    def caveat(self) -> str:
        if self.comparable_lengths:
            return (
                f"{self.current.label} and {self.baseline.label} cover the same window "
                f"({self.current.weeks} wks) — counts compare directly."
            )
        return (
            f"{self.current.label} covers {self.current.weeks} weeks against "
            f"{self.baseline.weeks} in {self.baseline.label} — compare rates, not raw counts."
        )

    @property
    def rate_factor(self) -> float:
        """Multiply a baseline count by this to put it on the current period's window."""
        if self.baseline.weeks <= 0:
            return 1.0
        return self.current.weeks / self.baseline.weeks


PRESETS = {
    "previous": "vs the period before",
    "last_year": "vs the same period last year",
    "custom": "custom range",
}


def resolve(
    granularity: str,
    preset: str,
    today: date,
    data_through: date,
    current_key: str | None = None,
    baseline_key: str | None = None,
) -> Comparison:
    """Turn a filter selection into two concrete periods.

    An unknown granularity or preset falls back to the default rather than failing: the page
    still has to render something, and the response says which comparison it actually used.
    """
    granularity = granularity if granularity in GRANULARITIES else QUARTER
    preset = preset if preset in PRESETS else "previous"

    head = (current_key and parse(current_key, today, data_through)) or current(
        granularity, today, data_through
    )
    granularity = head.granularity

    if preset == "custom" and baseline_key:
        baseline = parse(baseline_key, today, data_through) or previous(head, data_through)
    elif preset == "last_year":
        baseline = same_period_last_year(head, data_through)
    else:
        baseline = previous(head, data_through)

    return Comparison(current=head, baseline=baseline, granularity=granularity, preset=preset)
