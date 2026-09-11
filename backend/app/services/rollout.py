"""Shift-left Rollout payload assembly.

Tracks the move from reporting on evidence to enforcing it where work happens
(docs/PROPOSAL-ShiftLeft-Pivot.md). Three questions, in order: can the engine detect evidence
well enough to be trusted, where does it show up, and is it changing what people do.

The stage is a recorded decision. Whether a project may leave it is computed here on every read.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ArtifactDefinition, ArtifactWaiver
from app.models.project import Project
from app.models.rollout import STAGES, DetectionAudit, RolloutSprint, RolloutState, RolloutSurface
from app.schemas.common import DrillDown, Freshness, RagState
from app.schemas.insights import ChartSpec, EvidenceLink, Series, Tile
from app.schemas.rollout import (
    CriterionOut,
    DetectorRow,
    RolloutBoard,
    Signoff,
    StageOut,
    SurfaceRow,
)
from app.services import drill, guides, rollout_rules
from app.services import freshness as fresh
from app.services.palette import ACCENT, GOOD, NEUTRAL, POOR, WATCH
from app.services.readiness import is_denied

# Every system the board reads. Each widget is then guarded by the slice it depends on.
SOURCES = ["jira", "confluence", "xray", "ci", "github", "slack"]
# What detection reads when no audit names its own sources yet.
DETECTION_SOURCES = ["ci", "confluence", "jira", "xray"]
WARNING_SOURCES = ["jira", "github"]

MODE_LABEL = {"off": "Off", "live": "Live", "warn": "Warn", "block": "Block"}

AUDIT_NOTE = (
    "Each artifact the engine detected was checked by hand by the team's ETL. Correct means the "
    "engine and the audit agree. False missing is a warning someone did not deserve; false present "
    "is a gap the engine let through."
)


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}%" if value == round(value) else f"{value:.1f}%"


def _sprint_label(ends: date) -> str:
    return f"w/e {ends.day} {ends.strftime('%b')}"


def _tile(label: str, value: str, note: str, status: RagState, freshness: Freshness,
          drilldown=None) -> Tile:
    return Tile(label=label, value=value, note=note, status=fresh.guard(status, freshness),
                drill=drilldown)


async def state_for(session: AsyncSession, project: Project) -> RolloutState | None:
    return await session.get(RolloutState, project.id)


async def _history(session: AsyncSession, project_id: str) -> list[RolloutSprint]:
    return list(
        (
            await session.execute(
                select(RolloutSprint).where(RolloutSprint.project_id == project_id)
                .order_by(RolloutSprint.ends)
            )
        ).scalars().all()
    )


async def _audits(session: AsyncSession, project_id: str) -> list[DetectionAudit]:
    return list(
        (
            await session.execute(
                select(DetectionAudit).where(DetectionAudit.project_id == project_id)
            )
        ).scalars().all()
    )


def _false_red(sprint: RolloutSprint) -> float | None:
    if sprint.warnings is None or sprint.false_red is None:
        return None
    return _pct(sprint.false_red, sprint.warnings)


async def criteria(
    session: AsyncSession, project: Project, state: RolloutState
) -> list[rollout_rules.Criterion]:
    """The exit criteria for the project's current stage, evaluated now."""
    audits = await _audits(session, project.id)
    history = await _history(session, project.id)
    audited = sum(a.audited for a in audits)
    correct = sum(a.audited - a.false_missing - a.false_present for a in audits)
    waivers = (
        await session.execute(select(ArtifactWaiver).where(ArtifactWaiver.project_id == project.id))
    ).scalars().all()
    in_stage = [s for s in history if s.ends >= state.stage_since]
    return rollout_rules.exit_criteria(
        state.stage,
        accuracy=_pct(correct, audited),
        sprints_in_stage=len(in_stage),
        false_red_recent=[_false_red(s) for s in in_stage],
        team_signoff_by=state.team_signoff_by,
        waiver_review_on=state.waiver_review_on.isoformat() if state.waiver_review_on else None,
        denied_waivers=sum(1 for w in waivers if is_denied(w.rationale)),
    )


def blockers(items: list[rollout_rules.Criterion]) -> list[str]:
    return [f"{c.label}: {c.evidence}" for c in items if c.met is not True]


async def build(session: AsyncSession, project: Project) -> RolloutBoard | None:
    state = await state_for(session, project)
    if state is None:
        return None

    freshness = await fresh.resolve(session, SOURCES)
    bases = await drill.base_urls(session)
    definitions = {
        d.key: d
        for d in (
            await session.execute(select(ArtifactDefinition).order_by(ArtifactDefinition.position))
        ).scalars().all()
    }
    audits = await _audits(session, project.id)
    history = await _history(session, project.id)
    current_criteria = await criteria(session, project, state)

    # --- Detection, per artifact ------------------------------------------------------------
    detectors: list[DetectorRow] = []
    order = {key: d.position for key, d in definitions.items()}
    for audit in sorted(audits, key=lambda a: order.get(a.artifact_key, 99)):
        definition = definitions[audit.artifact_key]
        connector = audit.source_connector
        correct = audit.audited - audit.false_missing - audit.false_present
        accuracy = _pct(correct, audit.audited) or 0.0
        status = rollout_rules.accuracy_rag(accuracy, definition.name)
        if audit.note:
            status = RagState.of(status.rag, [*status.reasons, audit.note])
        detectors.append(
            DetectorRow(
                key=audit.artifact_key,
                name=definition.name,
                source=connector,
                method=audit.method,
                audited=audit.audited,
                correct=correct,
                false_missing=audit.false_missing,
                false_present=audit.false_present,
                accuracy=accuracy,
                note=audit.note,
                status=fresh.guard(status, fresh.restrict(freshness, [connector])),
                status_only=definition.status_only,
                drill=drill.jira_jql(
                    bases, f"issue in ({audit.features})",
                    label=f"Open the {audit.audited} audited features",
                ) if audit.features else None,
            )
        )

    detection_sources = sorted({a.source_connector for a in audits}) or DETECTION_SOURCES
    audited = sum(d.audited for d in detectors)
    correct = sum(d.correct for d in detectors)
    accuracy = _pct(correct, audited)
    audit_features = next((a.features for a in audits if a.features), "")
    audited_on = max((a.audited_on for a in audits), default=None)
    auditor = next((a.auditor for a in audits), None)

    # --- Warnings, latest sprint at Warn or later -------------------------------------------
    warned = [s for s in history if s.warnings is not None]
    latest = warned[-1] if warned else None
    false_red = _false_red(latest) if latest else None
    resolved = _pct(latest.evidence_added or 0, latest.warnings) if latest and latest.warnings else None

    # --- Stage path -------------------------------------------------------------------------
    stages: list[StageOut] = []
    for index, key in enumerate(STAGES):
        if index < state.stage:
            stage_state = "done"
        elif index == state.stage:
            stage_state = "current"
        else:
            stage_state = "ahead"
        stages.append(
            StageOut(
                index=index,
                key=key,
                label=rollout_rules.STAGE_LABELS[index],
                behaviour=rollout_rules.STAGE_BEHAVIOUR[index],
                state=stage_state,
                criteria=[
                    CriterionOut(label=c.label, met=c.met, status=c.status, evidence=c.evidence)
                    for c in current_criteria
                ] if index == state.stage else [],
            )
        )
    open_items = blockers(current_criteria)
    terminal = state.stage == len(STAGES) - 1
    can_advance = not terminal and not open_items

    # --- Tiles ------------------------------------------------------------------------------
    below = [f"{d.name}: {_fmt(d.accuracy)}" for d in detectors if d.accuracy < rollout_rules.DETECTION_GO]
    accuracy_state = rollout_rules.accuracy_rag(accuracy)
    if below:
        accuracy_state = RagState.of(accuracy_state.rag, [*accuracy_state.reasons, *below])

    met = sum(1 for c in current_criteria if c.met is True)
    if terminal:
        next_value, next_note = "—", "final stage: widened or narrowed per tier by leadership"
        next_state = RagState(rag="neutral", label="Final stage", glyph="dash", reasons=[
            "Hard gate is the last stage. What it covers is decided per risk tier by engineering "
            "leadership, not by a criterion on this board."
        ])
    else:
        next_value = f"{met} of {len(current_criteria)}"
        next_note = (
            f"criteria met to leave {rollout_rules.STAGE_LABELS[state.stage]} for "
            f"{rollout_rules.STAGE_LABELS[state.stage + 1]}"
        )
        if any(c.met is False for c in current_criteria):
            next_state = RagState.of("poor", open_items)
        elif open_items:
            next_state = RagState.of("missing", open_items)
        else:
            next_state = RagState.of("good", ["Every exit criterion is met. An admin can advance."])

    warn_freshness = fresh.restrict(freshness, WARNING_SOURCES)
    tiles = [
        _tile(
            "Detection accuracy",
            _fmt(accuracy),
            f"{correct} of {audited} audited artifacts · go bar {_fmt(rollout_rules.DETECTION_GO)}"
            if audited else "no manual audit recorded yet",
            accuracy_state,
            fresh.restrict(freshness, detection_sources),
            drill.jira_jql(bases, f"issue in ({audit_features})", label="Open the audited features")
            if audit_features else None,
        ),
        _tile(
            "False-red rate",
            _fmt(false_red),
            f"{latest.false_red} of {latest.warnings} warnings disputed and confirmed wrong · "
            f"bar {_fmt(rollout_rules.FALSE_RED_MAX)}" if latest else "no warning has fired yet",
            rollout_rules.false_red_rag(false_red),
            warn_freshness,
            drill.jira_jql(
                bases, f"project = {project.key} AND labels = shiftleft-disputed",
                label="Open disputed warnings",
            ) if latest else None,
        ),
        _tile(
            "Warnings resolved with evidence",
            _fmt(resolved),
            f"{latest.evidence_added} of {latest.warnings} · {latest.waived} waived · "
            f"{latest.ignored} ignored" if latest else "starts at Warn",
            rollout_rules.resolved_rag(resolved),
            warn_freshness,
            drill.jira_jql(
                bases, f"project = {project.key} AND labels = shiftleft-warned",
                label="Open warned issues",
            ) if latest else None,
        ),
        _tile(
            "Ready for the next stage",
            next_value,
            next_note,
            next_state,
            # Criteria read the audit and the warnings, so they carry both slices' freshness.
            fresh.restrict(freshness, sorted({*detection_sources, *WARNING_SOURCES})),
            _policy_drill(state),
        ),
    ]

    # --- Surfaces ---------------------------------------------------------------------------
    surface_rows = (
        await session.execute(
            select(RolloutSurface).where(RolloutSurface.project_id == project.id)
            .order_by(RolloutSurface.position)
        )
    ).scalars().all()
    surfaces: list[SurfaceRow] = []
    for surface in surface_rows:
        system = drill.SYSTEM_NAMES.get(surface.connector_key, surface.connector_key)
        age = fresh.age_minutes(surface.last_event_at)
        age_label = fresh.humanize_age(age)
        status = rollout_rules.surface_status(
            name=surface.name, gating=surface.gating, from_stage=surface.from_stage,
            mode=surface.mode, stage=state.stage, coverage_done=surface.coverage_done,
            coverage_total=surface.coverage_total, coverage_unit=surface.coverage_unit,
            gap_note=surface.gap_note, age_minutes=age,
            expected_every_minutes=surface.expected_every_minutes, age_label=age_label,
        )
        surfaces.append(
            SurfaceRow(
                key=surface.key,
                name=surface.name,
                system=system,
                gating=surface.gating,
                mode=surface.mode,
                mode_label=MODE_LABEL[surface.mode],
                coverage=(
                    f"{surface.coverage_done} of {surface.coverage_total} {surface.coverage_unit}"
                    if surface.coverage_total else "—"
                ),
                last_event="—" if surface.mode == "off" else age_label,
                events="—" if surface.mode == "off" else f"{surface.events_14d} {surface.events_unit}",
                status=fresh.guard(status, fresh.restrict(freshness, [surface.connector_key])),
                drill=drill.at(bases, surface.connector_key, surface.source_ref, f"Open in {system}"),
            )
        )

    # --- Charts -----------------------------------------------------------------------------
    charts: list[ChartSpec] = []
    measured = [s for s in history if s.accuracy is not None]
    if measured:
        charts.append(
            ChartSpec(
                key="accuracy",
                title="Detection accuracy by sprint",
                kind="line",
                x_labels=[_sprint_label(s.ends) for s in measured],
                series=[
                    Series(name="Detected correctly", color=ACCENT, data=[s.accuracy for s in measured]),
                    Series(name=f"Go bar {_fmt(rollout_rules.DETECTION_GO)}", color=NEUTRAL,
                           data=[rollout_rules.DETECTION_GO for _ in measured]),
                ],
                caption=(
                    "Source: engine detection checked against the ETL's manual audit, per sprint. "
                    "X: sprint end date. Y: % of audited artifacts detected correctly."
                ),
            )
        )
    if warned:
        charts.append(
            ChartSpec(
                key="outcomes",
                title="How warnings ended, by sprint",
                kind="bar",
                x_labels=[_sprint_label(s.ends) for s in warned],
                series=[
                    Series(name="Evidence added", color=GOOD, data=[s.evidence_added or 0 for s in warned]),
                    Series(name="Waived", color=NEUTRAL, data=[s.waived or 0 for s in warned]),
                    Series(name="Ignored", color=WATCH, data=[s.ignored or 0 for s in warned]),
                    Series(name="Engine wrong", color=POOR, data=[s.false_red or 0 for s in warned]),
                ],
                caption=(
                    "Source: Jira transition validator and GitHub check runs, outcome read from the "
                    "issue within 5 working days. X: sprint end date. Y: warnings fired."
                ),
            )
        )

    return RolloutBoard(
        project_id=project.id,
        project_label=project.name,
        subtitle=(
            "Is the evidence engine trusted enough to show up where work happens, and is it "
            "changing what people do? Each stage is earned against criteria listed here."
        ),
        stage=state.stage,
        stage_label=rollout_rules.STAGE_LABELS[state.stage],
        stage_since=state.stage_since,
        policy_version=state.policy_version,
        policy_drill=_policy_drill(state),
        audit_note=(
            f"{AUDIT_NOTE} Last audit {audited_on.isoformat()} by {auditor}."
            if audited_on else "No manual audit recorded. Detection is unmeasured, which is not "
            "the same as accurate."
        ),
        freshness=freshness,
        evidence_link=EvidenceLink(
            label="Open the evidence record",
            project_id=project.id,
            note="The checklist the engine evaluates. This board judges the rollout, not a feature.",
        ),
        tiles=tiles,
        stages=stages,
        can_advance=can_advance,
        advance_blockers=[] if terminal else open_items,
        signoff=Signoff(by=state.team_signoff_by, at=state.team_signoff_at),
        surfaces=surfaces,
        detectors=detectors,
        charts=charts,
        guide=await guides.for_perspective(session, "rollout"),
    )


def _policy_drill(state: RolloutState) -> DrillDown | None:
    """The policy pack lives in git; each evaluation names the version it ran against."""
    if not state.policy_ref.startswith("https://"):
        return None
    return DrillDown(label=f"Open policy {state.policy_version}", url=state.policy_ref, system="Git")
