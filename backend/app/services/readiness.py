"""Feature Readiness (Engineering Discipline) payload assembly.

This is the evidence record. Everything on it resolves to an artifact in a source system, and
every state resolves to a list of those artifacts - never to a score. Where this page and a flow
page disagree, this one governs.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.evidence import ActionRecord, ArtifactDefinition, ArtifactWaiver, FeatureEvidence
from app.models.project import Project
from app.schemas.common import Freshness, RagState
from app.schemas.insights import Tile
from app.schemas.readiness import (
    Action,
    AiDraft,
    ArtifactRow,
    Completeness,
    FeatureReadiness,
    FeatureRow,
    FlowLink,
    Waiver,
)
from app.services import drill, guides
from app.services import freshness as fresh

# The systems this page reads. Freshness is resolved against exactly these.
SOURCES = ["jira", "confluence", "xray", "ci"]

# The bar a gate conversation is held against. Below it, the gate stops being a formality.
RELEASE_BAR = 90
WATCH_BAR = 70

STATUS_RAG = {
    "present": "good",
    "drafted": "watch",
    "stale": "watch",
    "missing": "missing",
    "waived": "neutral",
}
STATUS_LABEL = {
    "present": "Present",
    "drafted": "Drafted",
    "stale": "Stale",
    "missing": "Missing",
    "waived": "Scoped out",
}
# Present or stale counts as held; drafted does not. A draft is work in progress, not evidence.
HELD_LABELS = ("Present", "Stale")

GATE_NOTE = (
    "Ready counts artifacts due before development starts; Done counts artifacts due before "
    "sign-off. Scoped-out artifacts leave both denominators and are listed as waivers. "
    "Threat models and security findings show presence and status only — content stays in the "
    "source system."
)

WAIVER_NOTE = (
    "Scoped-out artifacts are excluded from the denominators above so the percentages stay "
    "honest, and are reported here with owner, timestamp and rationale. Scoped out is not passed."
)

FLAG_NOTE = "Not an acceptable rationale — surfaced to platform owners as a planning signal."

AI_PENDING = (
    "Assistive until accepted. This draft counts toward no gate and no percentage until a "
    "named person records acceptance."
)


def is_denied(rationale: str) -> bool:
    """Rationales that are not a reason to scope an artifact out.

    A waiver carrying one still takes the artifact out of the denominator - hiding it would be
    worse - but it is flagged as a planning signal to platform owners. The list is configured
    (`SHIFTLEFT_WAIVER_RATIONALE_DENYLIST`), so it can grow without a release.
    """
    lowered = rationale.lower()
    return any(phrase.lower() in lowered for phrase in get_settings().waiver_rationale_denylist)


def _release_order(release: str) -> tuple[int, ...]:
    """2026.10 sorts after 2026.9 - release names compare as numbers, not as strings."""
    return tuple(int(part) for part in re.findall(r"\d+", release))


async def latest_release(session: AsyncSession, project_id: str) -> str | None:
    """The newest release the project tracks features in. Resolved from the data, never pinned,
    so the page does not go stale when the next release starts."""
    releases = (
        await session.execute(
            select(FeatureEvidence.release).where(FeatureEvidence.project_id == project_id).distinct()
        )
    ).scalars().all()
    return max(releases, key=_release_order, default=None)


def _completeness(rows: list[ArtifactRow], freshness: Freshness) -> Completeness:
    """Present-and-held over required for this gate. Waived artifacts never enter either side."""
    required = [r for r in rows if r.counts_toward_gate]
    held = [r for r in required if r.status_label in HELD_LABELS]
    total = len(required)
    done = len(held)
    percent = round(done / total * 100) if total else 100
    absent = [r for r in required if r.status_label not in HELD_LABELS]
    reasons = [f"{r.name}: {r.status_label.lower()}" for r in absent] or [
        "Every required artifact is held."
    ]
    return Completeness(
        done=done, total=total, percent=percent, label=f"{done} of {total}",
        status=fresh.guard(RagState.of(_bar_rag(percent), reasons), freshness),
    )


def _artifact_rows(
    feature: FeatureEvidence,
    definitions: dict[str, ArtifactDefinition],
    freshness: Freshness,
    bases: dict[str, str],
    gates: tuple[str, ...],
) -> list[ArtifactRow]:
    stale_connectors = {c.key for c in freshness.connectors if c.stale}
    rows: list[ArtifactRow] = []
    for artifact in feature.artifacts:
        definition = definitions[artifact.artifact_key]
        status = artifact.status
        note = artifact.note
        # A held artifact read through a stale connector is not evidence of a current state.
        if status == "present" and artifact.source_connector in stale_connectors:
            status = "stale"
            connector = next(c for c in freshness.connectors if c.key == artifact.source_connector)
            note = note or f"{connector.name} has not synced within its threshold."
        rag = STATUS_RAG[status]
        reasons = [note] if note else [f"{definition.name}: {STATUS_LABEL[status].lower()}."]
        rows.append(
            ArtifactRow(
                key=definition.key,
                name=definition.name,
                accountable=definition.accountable,
                gate=definition.gate,
                source=definition.source,
                status=RagState.of(rag, reasons),
                status_label=STATUS_LABEL[status],
                note=note,
                counts_toward_gate=definition.gate in gates and status != "waived",
                # A missing artifact has no record to open, and the UI says so rather than
                # offering a link that goes nowhere.
                drill=(
                    None
                    if status == "missing"
                    else drill.evidence_record(
                        bases, artifact.source_connector, feature.key, definition.name
                    )
                ),
                status_only=definition.status_only,
            )
        )
    return rows


def _feature_status(rows: list[ArtifactRow], freshness: Freshness) -> tuple[RagState, str, list[str]]:
    """The status *is* the reason list. Nothing here is weighted, summed or scored.

    Only artifacts due at the gate the feature currently stands at are evaluated: a Done-gate
    artifact is not a failure at the Ready gate, it is simply not due yet.
    """
    due = [r for r in rows if r.counts_toward_gate]
    missing = [
        f"{r.name} — {r.accountable}, due at "
        + ("Ready and Done" if r.gate == "Both" else r.gate + " gate")
        for r in due
        if r.status_label == "Missing"
    ]
    drafted = [r.name for r in due if r.status_label == "Drafted"]
    stale = [r.name for r in due if r.status_label == "Stale"]

    if missing:
        rag, reasons = "poor", list(missing)
        summary = (
            f"{len(missing)} required artifact{'s' if len(missing) > 1 else ''} missing at this gate"
        )
    elif drafted or stale:
        rag = "watch"
        reasons = [f"{name} is still a draft" for name in drafted]
        reasons += [f"{name} was read from a source past its freshness threshold" for name in stale]
        summary = "evidence present, one signal amber"
    else:
        rag, reasons = "good", ["Every required artifact is present and within threshold."]
        summary = "all required evidence present"
    return fresh.guard(RagState.of(rag, reasons), freshness), summary, missing


def _tile(label: str, value: str, note: str, rag: str, reasons: list[str],
          freshness: Freshness, drilldown=None) -> Tile:
    return Tile(
        label=label, value=value, note=note,
        status=fresh.guard(RagState.of(rag, reasons), freshness), drill=drilldown,
    )


def _bar_rag(percent: int) -> str:
    if percent >= RELEASE_BAR:
        return "good"
    return "watch" if percent >= WATCH_BAR else "poor"


async def build(session: AsyncSession, project: Project, release: str) -> FeatureReadiness | None:
    features = (
        await session.execute(
            select(FeatureEvidence)
            .where(FeatureEvidence.project_id == project.id, FeatureEvidence.release == release)
            .order_by(FeatureEvidence.position)
        )
    ).scalars().all()
    if not features:
        return None

    definitions = {
        d.key: d
        for d in (
            await session.execute(select(ArtifactDefinition).order_by(ArtifactDefinition.position))
        ).scalars().all()
    }
    freshness = await fresh.resolve(session, SOURCES)
    bases = await drill.base_urls(session)

    rows: list[FeatureRow] = []
    for feature in features:
        ready_rows = _artifact_rows(feature, definitions, freshness, bases, ("Ready", "Both"))
        done_rows = _artifact_rows(feature, definitions, freshness, bases, ("Done", "Both"))
        gate_rows = done_rows if feature.gate == "Done gate" else ready_rows
        status, summary, missing = _feature_status(gate_rows, freshness)
        accepted = feature.ai_accepted_by is not None
        rows.append(
            FeatureRow(
                key=feature.key,
                name=feature.name,
                tier=feature.tier,
                gate=feature.gate,
                owner=feature.owner,
                next_action=feature.next_action,
                action_age=feature.action_age,
                status=status,
                reason=summary,
                ready=_completeness(ready_rows, freshness),
                done=_completeness(done_rows, freshness),
                missing=missing,
                # Both passes describe the same eleven rows; only the gate flag differs.
                artifacts=gate_rows,
                ai=AiDraft(
                    text=feature.ai_draft,
                    drawn_from=feature.ai_drawn_from,
                    accepted_by=feature.ai_accepted_by,
                    accepted_at=feature.ai_accepted_at,
                    accepted=accepted,
                    note=(
                        f"Accepted by {feature.ai_accepted_by} — recorded against this feature."
                        if accepted
                        else AI_PENDING
                    ),
                ) if feature.ai_draft else None,
                drill=drill.jira_jql(
                    bases, f"issue = {feature.key}", label=f"Open {feature.key} in Jira"
                ),
                gate_note=GATE_NOTE,
            )
        )

    waiver_rows = (
        await session.execute(
            select(ArtifactWaiver).where(ArtifactWaiver.project_id == project.id)
            .order_by(ArtifactWaiver.id)
        )
    ).scalars().all()
    waivers = [
        Waiver(
            artifact=w.artifact, feature_key=w.feature_key, tier=w.tier, owner=w.owner,
            waived_at=w.waived_at, rationale=w.rationale, flagged=is_denied(w.rationale),
            flag_note=FLAG_NOTE if is_denied(w.rationale) else "",
        )
        for w in waiver_rows
    ]

    action_rows = (
        await session.execute(
            select(ActionRecord).where(ActionRecord.project_id == project.id)
            .order_by(ActionRecord.position)
        )
    ).scalars().all()
    actions = [
        Action(
            id=a.id, signal=a.signal, next_action=a.next_action, owner=a.owner, age=a.age,
            status=a.status, status_label=a.status.capitalize(),
            # Acknowledging a signal does not make it less severe. Only the status changes.
            severity=RagState.of(a.severity, [a.next_action]),
            acknowledged_by=a.acknowledged_by, acknowledged_at=a.acknowledged_at,
        )
        for a in action_rows
    ]

    done_gate = [f for f in rows if f.gate == "Done gate"]
    ready_percent = round(sum(f.ready.percent for f in rows) / len(rows))
    done_percent = round(sum(f.done.percent for f in done_gate) / len(done_gate)) if done_gate else 0
    cleared = [f for f in done_gate if f.status.rag == "good"]
    not_cleared = [f"{f.key} — {f.reason}" for f in done_gate if f.status.rag != "good"]
    flagged = [w for w in waivers if w.flagged]

    tiles = [
        _tile(
            "Definition of Ready completeness", f"{ready_percent}%",
            f"mean across {len(rows)} tracked features · release bar {RELEASE_BAR}%",
            _bar_rag(ready_percent),
            [f"{f.key}: {f.ready.label} required artifacts held" for f in rows if f.ready.percent < 100]
            or ["Every tracked feature holds its full Ready set."],
            freshness,
            drill.jira_jql(
                bases,
                f"project = {project.key} AND labels = shiftleft-tracked "
                f"AND fixVersion = {drill.jql_string(release)}",
            ),
        ),
        _tile(
            "Definition of Done completeness", f"{done_percent}%",
            f"mean across {len(done_gate)} features at the Done gate", _bar_rag(done_percent),
            [f"{f.key}: {f.done.label} required artifacts held" for f in done_gate if f.done.percent < 100]
            or ["Every feature at the Done gate holds its full set."],
            freshness,
            drill.jira_jql(
                bases,
                f"project = {project.key} AND fixVersion = {drill.jql_string(release)} "
                'AND status = "In Review"',
            ),
        ),
        _tile(
            "Cleared at the Done gate", f"{len(cleared)} of {len(done_gate)}",
            "features carrying complete evidence for this release",
            "good" if done_gate and len(cleared) == len(done_gate) else "poor" if not_cleared else "watch",
            not_cleared or ["Every feature at the Done gate is cleared."], freshness,
        ),
        _tile(
            "Scoped-out artifacts", str(len(waivers)),
            f"{len(flagged)} on a rationale that is not accepted", "watch" if flagged else "neutral",
            [f"{w.artifact} · {w.feature_key} — {w.rationale}" for w in waivers]
            or ["Nothing scoped out for this release."],
            freshness,
        ),
    ]

    return FeatureReadiness(
        project_id=project.id,
        project_label=project.name,
        release=release,
        subtitle=(
            "Is this feature allowed to start, or to ship? Composed from the evidence checklist "
            "— never from a hidden score."
        ),
        freshness=freshness,
        flow_link=FlowLink(
            label="Open the flow record for this team",
            project_id=project.id,
            note=(
                "Flow telemetry for the same team and window. It does not change any status on "
                "this page."
            ),
        ),
        tiles=tiles,
        features=rows,
        waivers=waivers,
        waiver_note=WAIVER_NOTE,
        actions=actions,
        guide=await guides.for_perspective(session, "discipline"),
    )
