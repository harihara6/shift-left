"""Team Insights (Delivery Control) payload assembly.

Flow telemetry only. Everything here is pace, size and defect pressure - none of it is evidence,
which is why the payload carries a mandatory cross-link into the Engineering Discipline record.

No period is named in this module. The page is always "the selected window against its baseline",
and every count that crosses between the two is compared as a rate, because the two windows are
routinely different lengths.
"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.schemas.common import Freshness, RagState
from app.schemas.insights import (
    ChartSpec,
    ComparisonOut,
    DeckSection,
    EvidenceLink,
    GlanceRow,
    PeriodOut,
    Series,
    TeamInsights,
    Tile,
)
from app.services import delivery_facts, delivery_rules, drill, guides
from app.services import freshness as fresh
from app.services.delivery_rules import Window
from app.services.palette import ACCENT, GOOD, POOR, WATCH
from app.services.periods import Comparison, Period, constituent_quarters

# Connectors this page depends on when a snapshot does not name its own.
SOURCES = ["jira", "linearb"]

ABSENT = "—"


def _window(period: Period) -> Window:
    return Window(label=period.label, weeks=period.weeks)


def period_out(period: Period, has_data: bool = True) -> PeriodOut:
    return PeriodOut(
        key=period.key,
        label=period.label,
        granularity=period.granularity,
        start=period.start.isoformat(),
        end=period.end.isoformat(),
        weeks=period.weeks,
        complete=period.complete,
        window_label=period.window_label,
        has_data=has_data,
    )


def _days(value: float | None) -> str:
    return ABSENT if value is None else f"{value:g}d"


def _count(value: float | None) -> str:
    return ABSENT if value is None else f"{value:g}"


def _sub(facts: dict, keys: tuple[str, ...], sample: int | None, aggregated: bool) -> str:
    """The small print under a cycle-time tile: median, P85 and sample where they exist.

    Where they do not, it says so. An aggregated window has no median to state - averaging
    per-quarter medians would produce a number that is not a median of anything.
    """
    parts = []
    if facts.get("median_days") is not None:
        parts.append(f"median {facts['median_days']:g}d")
    elif facts:
        parts.append(
            "median not recoverable across an aggregated window" if aggregated else "median absent"
        )
    if "p85_days" in keys and facts.get("p85_days") is not None:
        parts.append(f"P85 {facts['p85_days']:g}d")
    if sample:
        parts.append(f"n={sample}")
    return " · ".join(parts)


def _rate_note(count: float, period: Period) -> str:
    if period.weeks <= 0:
        return ""
    return f"{count / period.weeks:.1f} per week over {period.weeks} wks"


def _tile(value: str, label: str, note: str, status: RagState | None, freshness: Freshness,
          drilldown=None) -> Tile:
    return Tile(
        label=label,
        value=value,
        note=note,
        status=fresh.guard(status, freshness) if status else None,
        drill=drilldown,
    )


def _bar(key: str, title: str, x: list[str], series: list[Series], caption: str) -> ChartSpec:
    return ChartSpec(key=key, title=title, kind="bar", x_labels=x, series=series, caption=caption)


def _line(key: str, title: str, x: list[str], series: list[Series], caption: str) -> ChartSpec:
    return ChartSpec(key=key, title=title, kind="line", x_labels=x, series=series, caption=caption)


def _jql_window(project_key: str, period: Period) -> str:
    return (
        f"project = {project_key} AND status changed to Done "
        f'during ("{period.start:%Y-%m-%d}","{period.effective_end:%Y-%m-%d}")'
    )


def _maint_jql(project: Project) -> str:
    """MAINT is a shared defect project; the Team field - the team's name - identifies the team."""
    return f'project = MAINT AND "Team" = {drill.jql_string(project.name)}'


async def build(
    session: AsyncSession, project: Project, comparison: Comparison, data_through: date
) -> TeamInsights | None:
    current_keys = [p.key for p in constituent_quarters(comparison.current, data_through)]
    baseline_keys = [p.key for p in constituent_quarters(comparison.baseline, data_through)]

    current = await delivery_facts.load(session, project.id, current_keys)
    if current is None:
        return None
    baseline = await delivery_facts.load(session, project.id, baseline_keys)

    # A window with no baseline still renders. It simply has nothing to compare against, and the
    # rules say so rather than inventing a zero to divide by.
    empty: dict = {}
    base_payload = baseline.payload if baseline else empty
    cur = current.payload

    cur_window, base_window = _window(comparison.current), _window(comparison.baseline)
    freshness = await fresh.resolve(session, current.connector_keys or SOURCES)
    bases = await drill.base_urls(session)

    notes: list[str] = []
    if current.partial:
        notes.append(
            f"{comparison.current.label} is assembled from {len(current.period_keys)} of "
            f"{len(current_keys)} quarters — no snapshot for {', '.join(current.missing_keys)}."
        )
    if baseline is None:
        notes.append(
            f"No snapshot for {comparison.baseline.label}, so nothing on this page has a "
            "baseline. Statuses that need one are shown without a comparison."
        )
    elif baseline.partial:
        notes.append(
            f"{comparison.baseline.label} is missing {', '.join(baseline.missing_keys)}, so the "
            "comparison covers less than the full window."
        )
    if current.aggregated:
        notes.append(
            "Medians and P85s are not shown for an aggregated window — they cannot be recovered "
            "from per-quarter summaries, and an average of medians is not a median."
        )

    glance = _build_glance(cur, base_payload, comparison, cur_window, base_window, bases, project)
    sections = _build_sections(
        cur, base_payload, comparison, cur_window, base_window, freshness, bases, project
    )

    return TeamInsights(
        project_id=project.id,
        project_label=project.name,
        comparison=ComparisonOut(
            current=period_out(comparison.current),
            baseline=period_out(comparison.baseline, has_data=baseline is not None),
            granularity=comparison.granularity,
            preset=comparison.preset,
            comparable_lengths=comparison.comparable_lengths,
            caveat=comparison.caveat,
            covered_periods=current.period_keys,
            missing_periods=current.missing_keys + (baseline.missing_keys if baseline else baseline_keys),
            aggregated=current.aggregated,
        ),
        window=f"{comparison.baseline.window_label} → {comparison.current.window_label}",
        comparison_caveat=comparison.caveat,
        freshness=freshness,
        evidence_link=EvidenceLink(
            label="Open the evidence record for this team",
            project_id=project.id,
            note=(
                "This page is flow telemetry, not evidence. Where the two disagree, the "
                "Engineering Discipline record governs."
            ),
        ),
        glance=glance,
        glance_note=comparison.caveat,
        sections=sections,
        guide=await guides.for_perspective(session, "delivery"),
        notes=notes,
    )


def _build_glance(cur: dict, base: dict, comparison: Comparison, cur_window: Window,
                  base_window: Window, bases: dict, project: Project) -> list[GlanceRow]:
    """The opening five minutes of the review: what moved, once normalised for window length."""

    def flow_row(label: str, block: str, count_key: str, cycle_key: str = "avg_cycle_days") -> GlanceRow:
        current_block, base_block = cur.get(block, {}), base.get(block, {})
        current_count = current_block.get(count_key, 0)
        base_count = base_block.get(count_key)
        return GlanceRow(
            row=label,
            current=f"{current_count:g} · avg CT {_days(current_block.get(cycle_key))}",
            baseline=(
                ABSENT if base_count is None
                else f"{base_count:g} · avg CT {_days(base_block.get(cycle_key))}"
            ),
            status=delivery_rules.throughput(
                current_count, base_count or 0, cur_window, base_window, label.lower()
            ),
            drill=drill.jira_jql(bases, _jql_window(project.key, comparison.current)),
        )

    prs, base_prs = cur.get("prs", {}), base.get("prs", {})
    maint, base_maint = cur.get("maint", {}), base.get("maint", {})

    return [
        flow_row("Epics done", "epics", "throughput"),
        flow_row("Stories done, incl. tech", "stories", "throughput"),
        GlanceRow(
            row="MAINT resolved",
            current=f"{maint.get('resolved', 0)} · backlog {maint.get('backlog_end', ABSENT)}",
            baseline=(
                ABSENT if not base_maint
                else f"{base_maint.get('resolved', 0)} · backlog {base_maint.get('backlog_end', ABSENT)}"
            ),
            status=delivery_rules.closure_rate(
                maint.get("opened", 0), maint.get("resolved", 0), cur_window
            ),
            drill=drill.jira_jql(bases, _maint_jql(project)),
        ),
        GlanceRow(
            row="PRs merged",
            current=f"{prs.get('merged', 0)} · avg CT {_days(prs.get('avg_cycle_days'))}",
            baseline=(
                ABSENT if not base_prs
                else f"{base_prs.get('merged', 0)} · avg CT {_days(base_prs.get('avg_cycle_days'))}"
            ),
            status=delivery_rules.throughput(
                prs.get("merged", 0), base_prs.get("merged", 0), cur_window, base_window, "PRs merged"
            ),
        ),
        GlanceRow(
            row="PR size mix under 500 LOC",
            current=f"{_count(prs.get('small_pct'))}%",
            baseline=ABSENT if not base_prs else f"{_count(base_prs.get('small_pct'))}%",
            status=delivery_rules.small_pr_share(prs.get("small_pct")),
        ),
    ]


def _build_sections(cur: dict, base: dict, comparison: Comparison, cur_window: Window,
                    base_window: Window, freshness: Freshness, bases: dict,
                    project: Project) -> list[DeckSection]:
    current_label, baseline_label = comparison.current.label, comparison.baseline.label
    epics, stories, maint, prs = cur["epics"], cur["stories"], cur["maint"], cur["prs"]
    base_epics = base.get("epics", {})
    base_stories = base.get("stories", {})
    base_maint = base.get("maint", {})
    base_prs = base.get("prs", {})
    detection = cur["detection"]
    maint_jql = _maint_jql(project)

    current_aggregated = comparison.current.granularity != "quarter"
    baseline_aggregated = comparison.baseline.granularity != "quarter"

    def cycle_pair(block: str, current_block: dict, base_block: dict, subject: str,
                   keys: tuple[str, ...], drilldown=None) -> list[Tile]:
        """Baseline tile then current tile — the same two tiles every section opens with."""
        return [
            _tile(
                _days(base_block.get("avg_cycle_days")),
                f"{baseline_label} average cycle time",
                _sub(base_block, keys, base_block.get("sample"), baseline_aggregated)
                if base_block else "no baseline snapshot",
                None,
                freshness,
            ),
            _tile(
                _days(current_block.get("avg_cycle_days")),
                f"{current_label} average cycle time",
                _sub(current_block, keys, current_block.get("sample"), current_aggregated),
                delivery_rules.cycle_time(
                    current_block.get("avg_cycle_days"), base_block.get("avg_cycle_days"),
                    cur_window, base_window, subject,
                ),
                freshness,
                drilldown,
            ),
        ]

    def throughput_pair(current_block: dict, base_block: dict, subject: str) -> list[Tile]:
        return [
            _tile(
                _count(base_block.get("throughput")),
                f"{baseline_label} throughput",
                _rate_note(base_block.get("throughput", 0), comparison.baseline) if base_block else "—",
                None,
                freshness,
            ),
            _tile(
                _count(current_block.get("throughput")),
                f"{current_label} throughput",
                _rate_note(current_block.get("throughput", 0), comparison.current),
                delivery_rules.throughput(
                    current_block.get("throughput", 0), base_block.get("throughput", 0),
                    cur_window, base_window, subject,
                ),
                freshness,
            ),
        ]

    return [
        DeckSection(
            key="epics",
            title="Epics",
            scope="Jira · rolled-up story points",
            tiles=[
                *cycle_pair(
                    "epics", epics, base_epics, "epic", ("median_days", "p85_days"),
                    drill.jira_jql(
                        bases,
                        f"project = {project.key} AND issuetype = Epic AND "
                        f"resolutiondate >= {comparison.current.start:%Y-%m-%d}",
                    ),
                ),
                *throughput_pair(epics, base_epics, "epic throughput"),
            ],
            charts=[
                _bar(
                    "epic-throughput", "Epic throughput", [baseline_label, current_label],
                    [Series(name="Epics done", color=ACCENT,
                            data=[base_epics.get("throughput", 0), epics["throughput"]])],
                    f"Jira epics · x-axis period · y-axis epics completed · windows differ "
                    f"({base_window.weeks} vs {cur_window.weeks} wks)",
                ),
                _bar(
                    "epic-size", "Epic size vs cycle time", epics["size"]["labels"],
                    [Series(name="Epics done", color=ACCENT, data=epics["size"]["count"]),
                     Series(name="Avg cycle time (days)", color=WATCH, data=epics["size"]["cycle"])],
                    f"Jira epics, {current_label} · x-axis size bucket · y-axis count and mean cycle time",
                ),
            ],
        ),
        DeckSection(
            key="stories",
            title="Stories",
            scope="Jira · includes technical stories",
            tiles=[
                *cycle_pair(
                    "stories", stories, base_stories, "story", ("median_days", "p85_days"),
                    drill.jira_jql(
                        bases,
                        f"project = {project.key} AND issuetype in (Story, Task) AND "
                        f"resolutiondate >= {comparison.current.start:%Y-%m-%d}",
                    ),
                ),
                *throughput_pair(stories, base_stories, "story throughput"),
            ],
            charts=[
                _line(
                    "story-cadence", f"Weekly completion cadence, {current_label}",
                    stories["weekly"]["labels"],
                    [Series(name="Stories done", color=ACCENT, data=stories["weekly"]["done"])],
                    "Jira changelog · x-axis ISO week · y-axis stories completed",
                ),
                _bar(
                    "story-size", "Story distribution by size", stories["size"]["labels"],
                    [Series(name="Stories done", color=ACCENT, data=stories["size"]["count"]),
                     Series(name="Avg cycle time (days)", color=WATCH, data=stories["size"]["cycle"])],
                    f"Jira, {current_label} · x-axis point bucket · y-axis count and mean cycle time",
                ),
            ],
        ),
        DeckSection(
            key="maint",
            title="MAINT defect flow",
            scope="Jira · MAINT issue type",
            tiles=[
                *cycle_pair(
                    "maint", maint, base_maint, "defect", ("median_days",),
                    drill.jira_jql(bases, maint_jql),
                ),
                _tile(
                    _count(maint.get("backlog_end")),
                    "Open backlog at window end",
                    f"was {_count(base_maint.get('backlog_end'))} at the end of {baseline_label}",
                    delivery_rules.backlog(
                        maint.get("backlog_end"), base_maint.get("backlog_end"), base_window
                    ),
                    freshness,
                    drill.jira_jql(bases, f"{maint_jql} AND resolution = Unresolved"),
                ),
                _tile(
                    f"{maint.get('opened', 0)} / {maint.get('resolved', 0)}",
                    "Opened / resolved",
                    _rate_note(maint.get("resolved", 0), comparison.current),
                    delivery_rules.closure_rate(
                        maint.get("opened", 0), maint.get("resolved", 0), cur_window
                    ),
                    freshness,
                ),
            ],
            charts=[
                _bar(
                    "maint-priority", "Priority mix and cycle time", maint["priority"]["labels"],
                    [Series(name="Resolved", color=ACCENT, data=maint["priority"]["count"]),
                     Series(name="Avg cycle time (days)", color=POOR, data=maint["priority"]["cycle"])],
                    f"Jira MAINT, {current_label} · x-axis priority · y-axis resolved count and "
                    "mean cycle time",
                ),
                _bar(
                    "maint-flow", "Opened against resolved", ["Opened", "Resolved"],
                    [Series(name=baseline_label, color=WATCH,
                            data=[base_maint.get("opened", 0), base_maint.get("resolved", 0)]),
                     Series(name=current_label, color=ACCENT,
                            data=[maint.get("opened", 0), maint.get("resolved", 0)])],
                    f"Jira MAINT · x-axis state · y-axis issues · windows differ "
                    f"({base_window.weeks} vs {cur_window.weeks} wks)",
                ),
            ],
        ),
        DeckSection(
            key="prs",
            title="Pull requests",
            scope=project.pr_scope or "LinearB",
            tiles=[
                _tile(
                    _days(base_prs.get("median_cycle_days")),
                    f"{baseline_label} median cycle time",
                    f"avg {_days(base_prs.get('avg_cycle_days'))} · {base_prs.get('merged', 0)} PRs"
                    if base_prs else "no baseline snapshot",
                    None,
                    freshness,
                ),
                _tile(
                    _days(prs.get("median_cycle_days")),
                    f"{current_label} median cycle time",
                    f"avg {_days(prs.get('avg_cycle_days'))} · {prs.get('merged', 0)} PRs",
                    delivery_rules.cycle_time(
                        prs.get("median_cycle_days"), base_prs.get("median_cycle_days"),
                        cur_window, base_window, "PR",
                    ),
                    freshness,
                ),
                _tile(
                    f"{_count(prs.get('small_pct'))}%",
                    "Share under 500 LOC",
                    f"{baseline_label} {_count(base_prs.get('small_pct'))}% → "
                    f"{current_label} {_count(prs.get('small_pct'))}%",
                    delivery_rules.small_pr_share(prs.get("small_pct")),
                    freshness,
                ),
                _tile(
                    _count(prs.get("huge_count")),
                    "Huge PRs, 1000 LOC and above",
                    "tail driver for review latency",
                    delivery_rules.huge_pr_share(prs.get("huge_count", 0), prs.get("merged", 0)),
                    freshness,
                ),
            ],
            charts=[
                _line(
                    "pr-throughput", f"Merge throughput, {current_label}",
                    prs["cadence"]["labels"],
                    [Series(name="PRs merged", color=ACCENT, data=prs["cadence"]["merged"])],
                    "LinearB · x-axis period start · y-axis PRs merged",
                ),
                _bar(
                    "pr-size-cycle", "Cycle time by PR size", prs["buckets"]["labels"],
                    [Series(name="Median cycle time (days)", color=WATCH, data=prs["buckets"]["cycle"])],
                    f"LinearB, {current_label} · x-axis changed lines · y-axis median cycle time",
                ),
                _line(
                    "detection", "Where defects are found", detection["labels"],
                    [Series(name="At PR", color=GOOD, data=detection["pr"]),
                     Series(name="Nightly or later", color=WATCH, data=detection["nightly"]),
                     Series(name="After deploy", color=POOR, data=detection["prod"])],
                    "Jira detection stage · x-axis reporting week · y-axis share of detected defects (%)",
                ),
            ],
        ),
    ]
