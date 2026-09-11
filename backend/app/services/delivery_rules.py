"""Delivery-control thresholds.

The prototype hand-authored a RAG letter onto every field. That cannot survive a period filter -
and it should not, because a status nobody can trace is a score in disguise. Each rule here states
its criterion in the reason it returns, so "why is this amber" is answerable from the widget.

Two of these rules exist specifically to stop a shorter period reading as a collapse:
`throughput` and `volume` compare rates per week, never raw counts.
"""

from dataclasses import dataclass

from app.schemas.common import RagState

# Cycle time: how much slower than the baseline is still acceptable.
CYCLE_TIME_WATCH = 0.10
CYCLE_TIME_POOR = 0.25

# Throughput rate: how much of a per-week drop is still acceptable.
THROUGHPUT_WATCH = -0.10
THROUGHPUT_POOR = -0.25

# Share of PRs under 500 changed lines.
SMALL_PR_GOOD = 75.0
SMALL_PR_WATCH = 50.0

# Share of merged PRs at or above 1000 changed lines.
HUGE_PR_GOOD = 10.0
HUGE_PR_WATCH = 25.0

# Resolved as a share of opened, over the same window.
CLOSURE_GOOD = 1.0
CLOSURE_WATCH = 0.85

# Backlog movement that reads as flat rather than as growth.
BACKLOG_FLAT = 0.05


@dataclass(frozen=True)
class Window:
    """Just enough of a period for a rule to normalise by its length."""

    label: str
    weeks: float


def _pct(value: float) -> str:
    return f"{value * 100:+.0f}%"


def missing(what: str) -> RagState:
    """Absent data is a gap, never a pass and never a zero."""
    return RagState.of("missing", [f"{what} is not present in this period's snapshot."])


def cycle_time(current: float | None, baseline: float | None, current_window: Window,
               baseline_window: Window, subject: str) -> RagState:
    """Slower than last period is the signal. Window length does not affect a per-item duration."""
    if current is None:
        return missing(f"{subject} cycle time")
    if not baseline:
        return RagState.of(
            "neutral",
            [f"No {baseline_window.label} baseline for {subject} cycle time — shown without a comparison."],
        )
    change = (current - baseline) / baseline
    criterion = (
        f"{current:g}d against {baseline:g}d in {baseline_window.label} ({_pct(change)}). "
        f"On track within {CYCLE_TIME_WATCH:.0%} slower, watch to {CYCLE_TIME_POOR:.0%}."
    )
    if change <= CYCLE_TIME_WATCH:
        return RagState.of("good", [criterion])
    if change <= CYCLE_TIME_POOR:
        return RagState.of("watch", [criterion])
    return RagState.of("poor", [criterion])


def throughput(current: float, baseline: float, current_window: Window,
               baseline_window: Window, subject: str) -> RagState:
    """Compared per week, so a partial period is not mistaken for a slowdown."""
    if not baseline or baseline_window.weeks <= 0 or current_window.weeks <= 0:
        return RagState.of(
            "neutral",
            [f"No {baseline_window.label} baseline for {subject} — shown without a comparison."],
        )
    current_rate = current / current_window.weeks
    baseline_rate = baseline / baseline_window.weeks
    change = (current_rate - baseline_rate) / baseline_rate if baseline_rate else 0.0
    criterion = (
        f"{current_rate:.1f}/wk against {baseline_rate:.1f}/wk in {baseline_window.label} "
        f"({_pct(change)}) — rate, not raw count, because the windows differ. "
        f"On track above {THROUGHPUT_WATCH:.0%}, watch to {THROUGHPUT_POOR:.0%}."
    )
    if change >= THROUGHPUT_WATCH:
        return RagState.of("good", [criterion])
    if change >= THROUGHPUT_POOR:
        return RagState.of("watch", [criterion])
    return RagState.of("poor", [criterion])


def small_pr_share(percent: float | None) -> RagState:
    if percent is None:
        return missing("PR size mix")
    criterion = (
        f"{percent:g}% of merged PRs are under 500 lines. "
        f"On track at {SMALL_PR_GOOD:g}% or above, watch to {SMALL_PR_WATCH:g}%."
    )
    if percent >= SMALL_PR_GOOD:
        return RagState.of("good", [criterion])
    if percent >= SMALL_PR_WATCH:
        return RagState.of("watch", [criterion])
    return RagState.of("poor", [criterion])


def huge_pr_share(huge: int, merged: int) -> RagState:
    if not merged:
        return missing("PR volume")
    percent = huge / merged * 100
    criterion = (
        f"{huge} of {merged} merged PRs are 1000 lines or more ({percent:.0f}%). "
        f"On track below {HUGE_PR_GOOD:g}%, watch to {HUGE_PR_WATCH:g}%."
    )
    if percent < HUGE_PR_GOOD:
        return RagState.of("good", [criterion])
    if percent < HUGE_PR_WATCH:
        return RagState.of("watch", [criterion])
    return RagState.of("poor", [criterion])


def closure_rate(opened: int, resolved: int, window: Window) -> RagState:
    if not opened:
        return missing("defect intake")
    rate = resolved / opened
    criterion = (
        f"{resolved} resolved against {opened} opened over {window.weeks} weeks "
        f"({rate:.0%} closure). On track at {CLOSURE_GOOD:.0%} or above, watch to {CLOSURE_WATCH:.0%}."
    )
    if rate >= CLOSURE_GOOD:
        return RagState.of("good", [criterion])
    if rate >= CLOSURE_WATCH:
        return RagState.of("watch", [criterion])
    return RagState.of("poor", [criterion])


def backlog(current: int | None, baseline: int | None, baseline_window: Window) -> RagState:
    if current is None:
        return missing("Open backlog")
    if not baseline:
        return RagState.of("neutral", ["No earlier backlog reading to compare against."])
    change = (current - baseline) / baseline
    criterion = (
        f"{current} open against {baseline} at the end of {baseline_window.label} ({_pct(change)}). "
        f"On track when it falls, watch within {BACKLOG_FLAT:.0%} either way."
    )
    if change < -BACKLOG_FLAT:
        return RagState.of("good", [criterion])
    if change <= BACKLOG_FLAT:
        return RagState.of("watch", [criterion])
    return RagState.of("poor", [criterion])
