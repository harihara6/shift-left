"""Rollout thresholds and the rules that judge them.

Every threshold on the Shift-left Rollout board is a named constant here, and every rule states
its criterion in the reason it emits. The numbers are the ones docs/PROPOSAL-ShiftLeft-Pivot.md
s9-s10 commits to; change them there first.
"""

from dataclasses import dataclass

from app.schemas.common import RagState

# Detection accuracy against the manual audit (proposal s10). At or above GO, a red on someone's
# Jira issue is trustworthy enough to show; between FIX and GO, templates come before rollout.
DETECTION_GO = 90.0
DETECTION_FIX = 70.0

# Leaving Warn: the engine is wrong on fewer than this share of the warnings it fires...
FALSE_RED_MAX = 5.0
# ...for at least this many consecutive sprints spent at Warn.
WARN_SPRINTS_MIN = 2

# Leaving Soft gate takes one release cycle, which at Backbase's cadence is three sprints.
RELEASE_CYCLE_SPRINTS = 3

# The behaviour-change signal (PRD s11): a warning should end with evidence added, not waived
# or ignored.
RESOLVED_GOOD = 60.0
RESOLVED_WATCH = 40.0

STAGE_LABELS = ("Observe", "Warn", "Soft gate", "Hard gate, by tier")
STAGE_BEHAVIOUR = (
    "The engine evaluates; results show in the Jira panel only. No messages, no blocks.",
    "The validator and PR check warn and never block. The Slack digest starts.",
    "A transition is blocked unless evidence is present or a waiver is recorded in the panel.",
    "New capability and major change: no waiver path for mandatory artifacts. Minor and config "
    "stay soft.",
)

# What a gating surface should be doing at each stage.
GATING_MODE = ("off", "warn", "block", "block")


@dataclass
class Criterion:
    label: str
    met: bool | None  # None means the data to judge it is absent - never treated as met.
    status: RagState
    evidence: str


def _pct(value: float) -> str:
    return f"{value:.0f}%" if value == round(value) else f"{value:.1f}%"


def accuracy_rag(percent: float | None, what: str = "Detection accuracy") -> RagState:
    if percent is None:
        return RagState.of("missing", [f"{what}: no audit recorded. Absent is not green."])
    if percent >= DETECTION_GO:
        return RagState.of("good", [
            f"{what} {_pct(percent)}: on track at {_pct(DETECTION_GO)} or better."
        ])
    if percent >= DETECTION_FIX:
        return RagState.of("watch", [
            f"{what} {_pct(percent)}: between {_pct(DETECTION_FIX)} and {_pct(DETECTION_GO)}, so roll out "
            "Confluence templates and re-measure before going further."
        ])
    return RagState.of("poor", [
        f"{what} {_pct(percent)}: below {_pct(DETECTION_FIX)}. Evidence lives in too many "
        "unstructured places; fix source conventions first."
    ])


def false_red_rag(percent: float | None) -> RagState:
    if percent is None:
        return RagState.of("missing", ["Measured from Warn onward; no warning has fired yet."])
    if percent < FALSE_RED_MAX:
        return RagState.of("good", [f"False-red {_pct(percent)}: under the {_pct(FALSE_RED_MAX)} bar."])
    if percent < FALSE_RED_MAX * 2:
        return RagState.of("watch", [
            f"False-red {_pct(percent)}: over the {_pct(FALSE_RED_MAX)} bar. "
            f"Watch to {_pct(FALSE_RED_MAX * 2)}."
        ])
    return RagState.of("poor", [
        f"False-red {_pct(percent)}: at least twice the {_pct(FALSE_RED_MAX)} bar. Teams will learn "
        "to ignore the warnings."
    ])


def resolved_rag(percent: float | None) -> RagState:
    if percent is None:
        return RagState.of("missing", ["Measured from Warn onward; no warning has fired yet."])
    if percent >= RESOLVED_GOOD:
        return RagState.of("good", [
            f"{_pct(percent)} ended with evidence added: on track at {_pct(RESOLVED_GOOD)} or better."
        ])
    if percent >= RESOLVED_WATCH:
        return RagState.of("watch", [
            f"{_pct(percent)} ended with evidence added: below {_pct(RESOLVED_GOOD)}, "
            f"watch to {_pct(RESOLVED_WATCH)}."
        ])
    return RagState.of("poor", [
        f"{_pct(percent)} ended with evidence added: below {_pct(RESOLVED_WATCH)}. The warnings are "
        "being waived or ignored, not acted on."
    ])


def _criterion(label: str, met: bool | None, evidence: str) -> Criterion:
    rag = "missing" if met is None else "good" if met else "poor"
    return Criterion(label=label, met=met, status=RagState.of(rag, [evidence]), evidence=evidence)


def exit_criteria(
    stage: int,
    *,
    accuracy: float | None,
    sprints_in_stage: int,
    false_red_recent: list[float | None],
    team_signoff_by: str | None,
    waiver_review_on: str | None,
    denied_waivers: int,
) -> list[Criterion]:
    """What has to be true before a project may leave `stage`. Hard gate is terminal."""
    if stage == 0:
        return [
            _criterion(
                f"Detection at least {_pct(DETECTION_GO)} accurate against a manual audit",
                None if accuracy is None else accuracy >= DETECTION_GO,
                "No audit recorded yet." if accuracy is None
                else f"{_pct(accuracy)} of audited artifacts detected correctly.",
            )
        ]
    if stage == 1:
        recent = false_red_recent[-WARN_SPRINTS_MIN:]
        measured = [r for r in recent if r is not None]
        if len(measured) < WARN_SPRINTS_MIN:
            false_red_met, false_red_text = None, (
                f"{len(measured)} of {WARN_SPRINTS_MIN} sprints measured at Warn so far."
            )
        else:
            false_red_met = all(r < FALSE_RED_MAX for r in measured)
            false_red_text = "Last sprints: " + ", ".join(_pct(r) for r in measured) + "."
        return [
            _criterion(
                f"At least {WARN_SPRINTS_MIN} sprints at Warn",
                sprints_in_stage >= WARN_SPRINTS_MIN,
                f"{sprints_in_stage} sprint{'s' if sprints_in_stage != 1 else ''} completed at Warn.",
            ),
            _criterion(
                f"False-red under {_pct(FALSE_RED_MAX)} in each of the last {WARN_SPRINTS_MIN} sprints",
                false_red_met, false_red_text,
            ),
            _criterion(
                "The team agrees the reasons are fair",
                team_signoff_by is not None,
                f"Recorded by {team_signoff_by}." if team_signoff_by
                else "No sign-off recorded. The team's ETL records it on this board.",
            ),
        ]
    if stage == 2:
        return [
            _criterion(
                f"One release cycle ({RELEASE_CYCLE_SPRINTS} sprints) at Soft gate",
                sprints_in_stage >= RELEASE_CYCLE_SPRINTS,
                f"{sprints_in_stage} of {RELEASE_CYCLE_SPRINTS} sprints completed.",
            ),
            _criterion(
                "Waiver volume reviewed with the ETLs",
                waiver_review_on is not None,
                f"Reviewed on {waiver_review_on}." if waiver_review_on else "No review recorded.",
            ),
            _criterion(
                "No waiver resting on a deny-listed rationale",
                denied_waivers == 0,
                f"{denied_waivers} waiver{'s' if denied_waivers != 1 else ''} on a rationale such as "
                "'capacity pressure'." if denied_waivers else "None on the deny-list.",
            ),
        ]
    return []


def surface_status(
    *,
    name: str,
    gating: bool,
    from_stage: int,
    mode: str,
    stage: int,
    coverage_done: int,
    coverage_total: int,
    coverage_unit: str,
    gap_note: str,
    age_minutes: int | None,
    expected_every_minutes: int,
    age_label: str,
) -> RagState:
    """A surface is judged on three things: is it doing what the stage says, where, and lately."""
    stage_label = STAGE_LABELS[stage]
    expected_on = stage >= from_stage
    if gating:
        expected_mode = GATING_MODE[stage] if expected_on else "off"
        if mode == "block" and expected_mode != "block":
            return RagState.of("poor", [
                f"{name} is blocking while the project is at {stage_label}. That's ahead of what "
                "the team agreed; roll it back to warn."
            ])
        if mode != expected_mode:
            return RagState.of("poor", [
                f"{name} is {mode} but {stage_label} expects {expected_mode}."
            ])
    else:
        if expected_on and mode == "off":
            return RagState.of("poor", [f"{name} isn't switched on, and {stage_label} depends on it."])

    if mode == "off":
        # Correctly off is not the same as healthy: nothing has been shown to work yet.
        return RagState(rag="neutral", label="Not due yet", glyph="dash",
                        reasons=[f"Off, as expected at {stage_label}."])

    reasons: list[str] = []
    rag = "good"
    if coverage_total and coverage_done < coverage_total:
        rag = "watch"
        reasons.append(
            f"On {coverage_done} of {coverage_total} {coverage_unit}"
            + (f": {gap_note}" if gap_note else ".")
        )
    if age_minutes is None:
        return RagState.of("missing", [*reasons, "No event recorded since it was switched on."])
    if age_minutes > expected_every_minutes:
        rag = "watch"
        reasons.append(
            f"Last event {age_label}; expected at least every "
            f"{_every(expected_every_minutes)}. Silence is not the same as nothing to report."
        )
    return RagState.of(rag, reasons or [f"Running as {stage_label} expects, everywhere it should."])


def _every(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} day{'s' if days != 1 else ''}"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"
