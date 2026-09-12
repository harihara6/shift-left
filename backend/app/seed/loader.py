"""Seeds the store from the design prototype's data, in two layers.

* `seed_reference` - the platform's own definitions (guides, connector and template catalogs,
  canonical artifacts). Every environment needs them; production loads them too.
* `seed` - example projects, connector instances, delivery facts, evidence and rollout history.
  These rows stand in for connector output until each real adapter is built. They sit behind the
  same API contract the live connectors will fill, so nothing above this layer changes when they
  do. Never loaded in production.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector import ConnectorInstance, ConnectorType
from app.models.evidence import (
    ActionRecord,
    ArtifactDefinition,
    ArtifactWaiver,
    FeatureEvidence,
    NormalizedArtifact,
)
from app.models.guide import PerspectiveGuide, WidgetGuide
from app.models.kickoff import KickoffSettings
from app.models.metrics import MetricsSnapshot
from app.models.project import Project, ProjectAccess
from app.models.rollout import DetectionAudit, RolloutSprint, RolloutState, RolloutSurface
from app.models.template import ProjectTemplate, Template, TemplateWidget, WidgetBinding
from app.services.projects import slugify

DATA = Path(__file__).parent / "data"

# Deck data is keyed by team slug; projects are keyed by their Jira key.
DECK_FOR_PROJECT = {"ENT": "entitlements", "PAY": "payments", "NUC": "nucleus"}

# Resolved per connector instance at render time - a drill link is never a hardcoded tenant.
DRILL_TEMPLATE = "{connector_base}/browse/{source_ref}"
SNAPSHOT_KIND = "delivery_facts"
RELEASE = "2026.3"

# Which system each artifact is actually read from, so freshness and drill-downs resolve to
# the connector that produced the state rather than to a default.
ARTIFACT_CONNECTOR = {
    "requirements": "confluence", "acceptance_criteria": "jira", "test_plan": "confluence",
    "hld": "confluence", "lld": "confluence", "threat_model": "confluence",
    "traceability": "xray", "test_evidence": "xray", "performance": "confluence",
    "accessibility": "ci", "ai_evidence": "jira",
}
# Artifacts stored as presence and status only - content never leaves the source system.
STATUS_ONLY_ARTIFACTS = {"threat_model"}

# Per-connector freshness thresholds, in minutes. A connector polled hourly is not stale at 40
# minutes; one expected to stream is. Xray at 4h against a 30-minute bar is the stale case the
# design calls out.
STALENESS = {
    "jira": 30, "confluence": 60, "xray": 30, "github": 30, "bitbucket": 60, "sonarqube": 60,
    "ci": 30, "jenkins": 30, "linearb": 90, "jsm": 30, "slack": 15, "sentry": 30,
    "pagerduty": 30, "figma": 180, "datadog": 30, "security": 60,
}
# Connectors that store presence and status only - content never leaves the source system.
STATUS_ONLY = {"security", "xray", "confluence"}

STATE_MAP = {
    "Connected": "connected", "Stale": "stale", "Disabled": "disabled",
    "Not configured": "not_configured",
}

GUIDE_KEYS = {
    "delivery": ["glance", "epics", "stories", "maint", "prs"],
    "settings": ["projects", "widget_bindings", "connectors", "access"],
    "discipline": ["completeness", "cleared", "readiness_table", "status_reason", "waivers", "actions"],
    "execution": ["detection", "pr_feedback", "sdlc_stages"],
    "release": ["ship_decision", "execution_tiles", "nfr_evidence", "blockers"],
    "portfolio": ["hotspots", "cell_colouring"],
    "signal": ["completeness_trend", "dora", "counter_metric"],
    "rollout": ["gating_path", "rollout_tiles", "surfaces", "detectors", "rollout_charts"],
    "kickoff": [
        "analyses", "prd", "repos", "dependencies", "compliance", "api_docs", "third_parties", "plan",
        "backlog",
    ],
}


def _load(name: str) -> Any:
    return json.loads((DATA / f"{name}.json").read_text())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _project_id(name: str) -> str:
    """The same id the API mints on create, so seeded and created projects cannot diverge."""
    return slugify(name)


def _sync_to_datetime(label: str) -> datetime | None:
    """'6m ago' / '4h 12m ago' / 'live' / '—' -> an absolute timestamp, or None for never."""
    now = datetime.now(timezone.utc)
    if label in ("—", "", None):
        return None
    if label == "live":
        return now
    hours = re.search(r"(\d+)h", label)
    minutes = re.search(r"(\d+)m", label)
    delta = timedelta(hours=int(hours.group(1)) if hours else 0,
                      minutes=int(minutes.group(1)) if minutes else 0)
    return now - delta


def _connector_type(row: dict[str, Any]) -> ConnectorType:
    key = row["id"]
    return ConnectorType(
        key=key,
        name=row["name"],
        category=row["cat"],
        description=row["desc"],
        auth_methods=[
            {"label": a.replace(" — recommended", ""), "recommended": "recommended" in a}
            for a in row["auth"]
        ],
        fields=[
            {
                "key": _slug(label),
                "label": label,
                "help": help_text,
                # A field whose prototype value is the literal "secret" is write-only here.
                "type": "secret" if value == "secret" else "text",
                "seed_value": None if value in ("secret", "—") else value,
            }
            for label, value, help_text in row["fields"]
        ],
        scopes=row["scopes"],
        rate_limits=row["rate"],
        staleness_minutes=STALENESS.get(key, 30),
        status_only=key in STATUS_ONLY,
    )


async def _seed_connector_types(session: AsyncSession) -> None:
    for row in _load("connectors"):
        session.add(_connector_type(row))


async def _refresh_connector_types(session: AsyncSession) -> bool:
    """Bring connector definitions a store already holds up to the catalog's current ones.

    A connector's fields and auth methods are code, not configuration: app/connectors/live.py
    reads specific field keys. A store seeded from an older catalog would otherwise keep offering
    a form whose credential the service can't use (a GitHub App key where a token is read). Only
    the definition changes; an instance keeps its values, and an auth method the connector no
    longer offers is replaced by the one it does.
    """
    changed = False
    for row in _load("connectors"):
        fresh = _connector_type(row)
        stored = await session.get(ConnectorType, fresh.key)
        if stored is None:
            session.add(fresh)
            changed = True
            continue
        if stored.fields == fresh.fields and stored.auth_methods == fresh.auth_methods:
            continue
        for attr in ("name", "category", "description", "auth_methods", "fields", "scopes", "rate_limits"):
            setattr(stored, attr, getattr(fresh, attr))
        labels = {a["label"] for a in fresh.auth_methods}
        instances = (
            await session.execute(
                select(ConnectorInstance).where(ConnectorInstance.connector_key == fresh.key)
            )
        ).scalars()
        for instance in instances:
            if instance.auth_method and instance.auth_method not in labels:
                instance.auth_method = fresh.auth_methods[0]["label"] if fresh.auth_methods else None
        changed = True
    return changed


async def _seed_connector_instances(session: AsyncSession) -> None:
    """The prototype's configured connections, with sync times relative to now."""
    for row in _load("connectors"):
        key = row["id"]
        ctype = _connector_type(row)
        state = STATE_MAP.get(row["state"], "not_configured")
        if row["instances"] == 0:
            # Declared but never configured. It renders as a gap, not as a healthy zero.
            session.add(ConnectorInstance(connector_key=key, state=state, label=row["name"]))
            continue
        session.add(
            ConnectorInstance(
                connector_key=key,
                state=state,
                label=row["name"],
                auth_method=ctype.auth_methods[0]["label"] if ctype.auth_methods else None,
                config={f["key"]: f["seed_value"] for f in ctype.fields if f["seed_value"] is not None},
                # The vault reference, never the value.
                secret_refs={
                    f["key"]: f"vault://shiftleft/{key}/{f['key']}"
                    for f in ctype.fields
                    if f["type"] == "secret"
                },
                last_successful_sync=_sync_to_datetime(row["sync"]),
            )
        )


async def _seed_templates(session: AsyncSession) -> None:
    for tpl in _load("templates"):
        session.add(
            Template(
                key=tpl["id"],
                name=tpl["name"],
                perspective=tpl["perspective"],
                version=1,
                freshness_expectation="See each widget's refresh interval",
            )
        )
        guide_keys = GUIDE_KEYS.get(tpl["id"], [])
        for position, widget in enumerate(tpl["widgets"]):
            session.add(
                TemplateWidget(
                    template_key=tpl["id"],
                    position=position,
                    name=widget["w"],
                    connector_key=_slug(widget["c"]).split("_")[0],
                    query=widget["q"],
                    refresh_interval=widget["i"],
                    drill_template=DRILL_TEMPLATE,
                    # The catalog carries the guide link too, so a template enabled later
                    # deep-copies a widget that still knows its four guide answers.
                    guide_key=guide_keys[position] if position < len(guide_keys) else None,
                )
            )


async def _seed_projects(session: AsyncSession) -> None:
    templates = {t["id"]: t for t in _load("templates")}
    facts = _load("facts")
    data_through = datetime.strptime(facts["data_through"], "%Y-%m-%d").date()

    for cfg in _load("projects"):
        project_id = _project_id(cfg["name"])
        session.add(
            Project(
                id=project_id,
                key=cfg["key"],
                name=cfg["name"],
                owner=cfg["owner"],
                created_on=datetime.strptime(cfg["created"], "%d %b %Y").date(),
                pr_scope=facts["teams"].get(DECK_FOR_PROJECT.get(cfg["key"], ""), {}).get("pr_scope", ""),
            )
        )
        for principal, role, via in cfg["access"]:
            session.add(
                ProjectAccess(
                    project_id=project_id, principal=principal, role=role.lower(), via=via,
                    granted_by="seed",
                )
            )

        for template_key, tpl in templates.items():
            if template_key in cfg["off"]:
                # Not enabled means never deep-copied. There is no half-copied row to inherit.
                continue
            project_template = ProjectTemplate(
                project_id=project_id,
                template_key=template_key,
                name=tpl["name"],
                perspective=tpl["perspective"],
                enabled=True,
                copied_from_version=1,
                copied_at=datetime.now(timezone.utc),
            )
            session.add(project_template)
            await session.flush()
            guide_keys = GUIDE_KEYS.get(template_key, [])
            for position, widget in enumerate(tpl["widgets"]):
                session.add(
                    WidgetBinding(
                        project_template_id=project_template.id,
                        position=position,
                        name=widget["w"],
                        connector_key=_slug(widget["c"]).split("_")[0],
                        query=widget["q"].replace("ENT", cfg["key"]),
                        refresh_interval=widget["i"],
                        drill_template=DRILL_TEMPLATE,
                        guide_key=guide_keys[position] if position < len(guide_keys) else None,
                    )
                )

        team_key = DECK_FOR_PROJECT.get(cfg["key"])
        if not team_key:
            # A programme-level project has no delivery snapshot of its own. Team Insights
            # renders that as a gap rather than as an empty dashboard.
            continue
        for period_key, payload in facts["teams"][team_key]["periods"].items():
            session.add(
                MetricsSnapshot(
                    project_id=project_id,
                    kind=SNAPSHOT_KIND,
                    period=period_key,
                    payload=payload,
                    source_connector_keys=["jira", "linearb"],
                    computed_at=datetime.combine(data_through, datetime.min.time(), timezone.utc),
                )
            )


async def _seed_artifact_definitions(session: AsyncSession) -> None:
    """The eleven canonical artifacts. Order is the checklist order and is meaningful."""
    for definition in _load("evidence")["artifacts"]:
        session.add(
            ArtifactDefinition(
                key=definition["key"],
                position=definition["position"],
                name=definition["name"],
                accountable=definition["accountable"],
                gate=definition["gate"],
                source=definition["source"],
                status_only=definition["key"] in STATUS_ONLY_ARTIFACTS,
            )
        )


async def _seed_evidence(session: AsyncSession) -> None:
    """The evidence record: per-feature artifact states, waivers and actions."""
    data = _load("evidence")
    for cfg in _load("projects"):
        team = DECK_FOR_PROJECT.get(cfg["key"])
        if team is None:
            continue
        project_id = _project_id(cfg["name"])
        team_data = data["teams"][team]

        for position, feature in enumerate(team_data["features"]):
            row = FeatureEvidence(
                project_id=project_id,
                key=feature["key"],
                position=position,
                name=feature["name"],
                tier=feature["tier"],
                gate=feature["gate"],
                release=RELEASE,
                owner=feature["owner"],
                next_action=feature["next_action"],
                action_age=feature["action_age"],
                ai_draft=feature["ai"]["text"],
                ai_drawn_from=feature["ai"]["drawn_from"],
            )
            session.add(row)
            await session.flush()
            for artifact_position, artifact in enumerate(feature["artifacts"]):
                session.add(
                    NormalizedArtifact(
                        feature_id=row.id,
                        artifact_key=artifact["artifact_key"],
                        position=artifact_position,
                        status=artifact["status"],
                        note=artifact["note"],
                        source_ref=None if artifact["status"] == "missing" else feature["key"],
                        source_connector=ARTIFACT_CONNECTOR[artifact["artifact_key"]],
                    )
                )

        for waiver in team_data["waivers"]:
            session.add(
                ArtifactWaiver(
                    project_id=project_id,
                    feature_key=waiver["feature"],
                    artifact=waiver["artifact"],
                    tier=waiver["tier"],
                    owner=waiver["owner"],
                    waived_at=waiver["at"],
                    rationale=waiver["rationale"],
                )
            )

        for position, action in enumerate(team_data["actions"]):
            session.add(
                ActionRecord(
                    project_id=project_id,
                    position=position,
                    signal=action["signal"],
                    next_action=action["next_action"],
                    owner=action["owner"],
                    age=action["age"],
                    status=action["status"],
                    severity=action["severity"],
                )
            )


async def _seed_rollout(session: AsyncSession) -> None:
    """The shift-left rollout (docs/PROPOSAL-ShiftLeft-Pivot.md): stage, surfaces, audit, history."""
    data = _load("rollout")
    now = datetime.now(timezone.utc)
    for cfg in _load("projects"):
        team = DECK_FOR_PROJECT.get(cfg["key"])
        if team is None or team not in data["teams"]:
            # Not enrolled. The board says so rather than rendering an empty rollout.
            continue
        project_id = _project_id(cfg["name"])
        if await session.get(Project, project_id) is None:
            # Backfilling a store where this project was since removed: nothing to attach to.
            continue
        team_data = data["teams"][team]
        session.add(
            RolloutState(
                project_id=project_id,
                stage=team_data["stage"],
                stage_since=date.fromisoformat(team_data["stage_since"]),
                policy_version=team_data["policy_version"],
                policy_ref=team_data["policy_ref"],
                waiver_review_on=(
                    date.fromisoformat(team_data["waiver_review_on"])
                    if team_data["waiver_review_on"] else None
                ),
            )
        )
        for position, surface in enumerate(team_data["surfaces"]):
            done, total, unit = surface["coverage"]
            count, events_unit = surface["events"]
            minutes = surface["last_event_minutes"]
            session.add(
                RolloutSurface(
                    project_id=project_id,
                    key=surface["key"],
                    position=position,
                    name=surface["name"],
                    connector_key=surface["connector"],
                    gating=surface["gating"],
                    from_stage=surface["from_stage"],
                    mode=surface["mode"],
                    coverage_done=done,
                    coverage_total=total,
                    coverage_unit=unit,
                    gap_note=surface["gap_note"],
                    last_event_at=None if minutes is None else now - timedelta(minutes=minutes),
                    expected_every_minutes=surface["expected_every_minutes"],
                    events_14d=count,
                    events_unit=events_unit,
                    source_ref=surface["ref"],
                )
            )
        audit = team_data["audit"]
        for row in (audit or {}).get("rows", []):
            session.add(
                DetectionAudit(
                    project_id=project_id,
                    artifact_key=row["artifact"],
                    source_connector=ARTIFACT_CONNECTOR[row["artifact"]],
                    audited=row["audited"],
                    false_missing=row["false_missing"],
                    false_present=row["false_present"],
                    method=row["method"],
                    note=row["note"],
                    audited_on=date.fromisoformat(audit["audited_on"]),
                    auditor=audit["auditor"],
                    features=audit["features"],
                )
            )
        for sprint in team_data["sprints"]:
            session.add(
                RolloutSprint(
                    project_id=project_id,
                    ends=date.fromisoformat(sprint["ends"]),
                    accuracy=sprint.get("accuracy"),
                    warnings=sprint.get("warnings"),
                    evidence_added=sprint.get("evidence_added"),
                    waived=sprint.get("waived"),
                    ignored=sprint.get("ignored"),
                    false_red=sprint.get("false_red"),
                )
            )


async def _seed_guides(session: AsyncSession, only: set[str] | None = None) -> None:
    for perspective, guide in _load("guides").items():
        if only is not None and perspective not in only:
            continue
        session.add(
            PerspectiveGuide(
                perspective=perspective,
                title=guide["title"],
                subtitle=guide["sub"],
                audience=json.dumps(guide["who"]),
            )
        )
        keys = GUIDE_KEYS.get(perspective, [])
        for position, section in enumerate(guide["sections"]):
            session.add(
                WidgetGuide(
                    perspective=perspective,
                    widget_key=keys[position] if position < len(keys) else _slug(section["widget"]),
                    position=position,
                    widget=section["widget"],
                    decision=section["decision"],
                    source=section["source"],
                    fetch=section["fetch"],
                    tagging=section["labels"],
                )
            )


async def _empty(session: AsyncSession, column: Any) -> bool:
    return (await session.execute(select(column).limit(1))).first() is None


async def seed_reference(session: AsyncSession) -> bool:
    """The platform's own definitions, loaded in every environment, production included.

    Widget guides, the connector catalog, the template catalog and the eleven canonical
    artifacts are product content, not example data: the service refuses to boot without the
    guides, and Settings has nothing to configure without the catalogs. Each is added only when
    absent, so an operator's later edits are never overwritten - except connector definitions,
    which follow the catalog because the connectors' code reads their fields.
    """
    changed = False
    if await _empty(session, ConnectorType.key):
        await _seed_connector_types(session)
        changed = True
    elif await _refresh_connector_types(session):
        changed = True
    if await _empty(session, Template.key):
        await _seed_templates(session)
        changed = True
    if await _empty(session, ArtifactDefinition.key):
        await _seed_artifact_definitions(session)
        changed = True
    # Exactly one row of Feature Kickoff defaults, empty until someone fills it in. It is created
    # here as well as in the migration so a store built straight from the models has one too.
    if await session.get(KickoffSettings, 1) is None:
        session.add(KickoffSettings(id=1))
        changed = True
    have = set((await session.execute(select(PerspectiveGuide.perspective))).scalars().all())
    # A page whose widgets changed (a rebuilt page) gets its guide again: a guide describing
    # widgets that no longer exist is worse than none. Wording edits to an unchanged page stay.
    stored = (await session.execute(select(WidgetGuide.perspective, WidgetGuide.widget_key))).all()
    for perspective, keys in GUIDE_KEYS.items():
        if perspective in have and {k for p, k in stored if p == perspective} != set(keys):
            await session.execute(delete(WidgetGuide).where(WidgetGuide.perspective == perspective))
            await session.execute(delete(PerspectiveGuide).where(PerspectiveGuide.perspective == perspective))
            have.discard(perspective)
    missing = set(_load("guides")) - have
    if missing:
        # Per perspective, so a store from before a page existed gains that page's guide.
        await _seed_guides(session, only=missing)
        changed = True
    if changed:
        await session.commit()
    return changed


async def seed(session: AsyncSession) -> bool:
    """Example projects and everything hanging off them. Development and demo stores only.

    Run after `seed_reference`. Idempotent: a store that already holds projects only gains the
    rollout fixtures, for stores seeded before the rollout board existed.
    """
    if not await _empty(session, Project.id):
        if await _empty(session, RolloutState.project_id):
            await _seed_rollout(session)
            await session.commit()
            return True
        return False
    await _seed_connector_instances(session)
    await _seed_projects(session)
    await _seed_evidence(session)
    await session.flush()
    await _seed_rollout(session)
    await session.commit()
    return True
