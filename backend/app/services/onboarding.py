"""Smart onboarding: turning a team's name into a proposed project setup.

The flow is deliberately narrow at the one point that matters. Discovery asks every source
that can search by name what it has under a hint; the resolver picks which returned candidate
fills which slot; and then the catalog template queries are rewritten by **substituting those
resolved values into the exemplar query**. The model never writes a query — it only chooses
among identifiers a source actually returned, so there is no query here that some system did
not already vouch for.

Nothing in this module writes. It produces a draft; `accept` in the route applies it, and only
with a named person attached.

Where a slot was never resolved, the widget that needed it is left with an empty query. That
is the whole point: an empty query previews empty, and empty renders as a gap. Carrying the
exemplar's own query forward would silently point a new project at the Entitlements team's
data, which would look finished and be wrong.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.atlassian_mcp import RovoMcpSource
from app.connectors.discovery import DISCOVERY_CAPABILITY, Candidate
from app.connectors.registry import get_connector
from app.models.connector import ConnectorInstance, ConnectorType
from app.models.template import Template
from app.services.onboarding_ai import ResolutionResult, resolve

logger = logging.getLogger("shiftleft.onboarding")

# How a resolved slot value is written into a catalog query. The left side is the exemplar the
# catalog template ships with (the Entitlements team); the right side is what replaces it.
#
# `project = MAINT` is deliberately absent: MAINT is a shared defect project every team files
# into, so it is the Team field that identifies the team there, not the project key.
# `detail_key` reads the value out of the candidate's detail instead of its ref, for the cases
# where the identifier and the thing the query needs are not the same — the LinearB team id and
# the repo list that team covers, for instance. A candidate missing that detail leaves the slot
# unresolved, exactly as a missing candidate would.
SUBSTITUTIONS: list[tuple[str, re.Pattern[str], str, str | None]] = [
    ("jira_project", re.compile(r"\bproject\s*=\s*ENT\b"), "project = {value}", None),
    ("jira_team", re.compile(r'"Team"\s*=\s*Entitlements'), '"Team" = {value}', None),
    ("confluence_root", re.compile(r"\bancestor\s*=\s*\d+"), "ancestor = {value}", None),
    ("repository", re.compile(r"\bbackbase/entitlements\b"), "{value}", None),
    ("sonar_component", re.compile(r"\bbb:entitlements\b"), "{value}", None),
    ("linearb_team", re.compile(r"\bteamIds=\d+"), "teamIds={value}", None),
    ("linearb_team", re.compile(r"repos:\s*[A-Z0-9,\s\-]+"), "repos: {value}", "repos"),
    ("figma_file", re.compile(r"\bBB-Entitlements\b"), "{value}", None),
]

# Anything still naming the exemplar after substitution is a value the template carries that
# discovery has no slot for — the LinearB repo list, for instance. It is surfaced, not hidden.
LEFTOVER = re.compile(r"\bENT\b|entitlements|Entitlements|4915231|teamIds=418", re.IGNORECASE)

# Programme-level perspectives roll several projects up, so they are never proposed from one
# team's sources. An admin enables them deliberately.
PROGRAMME_TEMPLATES = {"portfolio", "signal"}


@dataclass
class SourceReport:
    """What one source contributed, including when it contributed nothing and why."""

    connector_key: str
    connector_name: str
    available: bool
    state: str
    note: str
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class BindingProposal:
    template_key: str
    widget_name: str
    connector_key: str
    position: int
    catalog_query: str
    query: str
    filled_slots: list[str]
    unresolved_slots: list[str]
    leftovers: list[str]
    validated: bool = False
    row_count: int = 0
    note: str = ""

    @property
    def ready(self) -> bool:
        """Bound to something discovery actually found."""
        return bool(self.query) and bool(self.filled_slots) and not self.unresolved_slots

    @property
    def generic(self) -> bool:
        """Names no team-specific value at all — a release scope, a workflow name, a test tag.

        Carried over verbatim, and never counted as resolved: it is valid for any project,
        which also means discovery has told you nothing about whether it is right for this one.
        """
        return bool(self.query) and not self.filled_slots and not self.unresolved_slots


@dataclass
class TemplateProposal:
    template_key: str
    name: str
    perspective: str
    propose_enabled: bool
    reason: str
    bindings: list[BindingProposal] = field(default_factory=list)


@dataclass
class Draft:
    hint: str
    sources: list[SourceReport]
    resolution: ResolutionResult
    filled: dict[str, Candidate]
    templates: list[TemplateProposal]
    discovery_available: bool
    note: str


async def discover(session: AsyncSession, hint: str) -> Draft:
    """Read every source that can search by name, then draft a setup from what came back."""
    sources = await _fan_out(session, hint)
    candidates = [c for s in sources for c in s.candidates]
    resolution = await resolve(hint, candidates)

    by_id = {c.id: c for c in candidates}
    filled = {
        choice.slot: by_id[choice.candidate_id]
        for choice in resolution.resolution.slots
        if choice.candidate_id in by_id
    }
    templates = await _draft_templates(session, filled)
    return Draft(
        hint=hint,
        sources=sources,
        resolution=resolution,
        filled=filled,
        templates=templates,
        discovery_available=any(s.available for s in sources),
        note=_note(sources, filled),
    )


async def _fan_out(session: AsyncSession, hint: str) -> list[SourceReport]:
    """Ask each source what it has. A source that cannot answer says so, in its own row."""
    types = (await session.execute(select(ConnectorType).order_by(ConnectorType.name))).scalars().all()
    instances = {
        i.connector_key: i
        for i in (await session.execute(select(ConnectorInstance))).scalars().all()
    }

    reports: list[SourceReport] = []

    # Rovo MCP first, where it is configured: it authenticates the person running onboarding,
    # so it returns exactly the Jira and Confluence they can already open.
    rovo = RovoMcpSource()
    if rovo.available:
        found = await rovo.search_entities(hint)
        reports.append(
            SourceReport(
                connector_key="rovo_mcp", connector_name="Atlassian Rovo MCP", available=True,
                state="connected",
                note=(
                    f"{len(found)} candidate(s) visible to you. Rovo MCP reads with your own "
                    "Atlassian permissions, so someone else may see a different set."
                ),
                candidates=found,
            )
        )
    else:
        reports.append(
            SourceReport(
                connector_key="rovo_mcp", connector_name="Atlassian Rovo MCP", available=False,
                state="not_configured", note=rovo.unavailable_reason,
            )
        )
    covered = {c.connector_key for r in reports for c in r.candidates}

    for ctype in types:
        instance = instances.get(ctype.key)
        state = instance.state if instance else "not_configured"
        connector = get_connector(
            ctype.key, ctype.name,
            instance.config if instance else {},
            instance.secret_refs if instance else {},
        )
        capabilities = await connector.list_capabilities()
        if DISCOVERY_CAPABILITY not in capabilities:
            continue
        if state in ("not_configured", "disabled"):
            reports.append(
                SourceReport(
                    connector_key=ctype.key, connector_name=ctype.name, available=False, state=state,
                    note=f"{ctype.name} is {state.replace('_', ' ')} — nothing to search.",
                )
            )
            continue
        if ctype.key in covered:
            reports.append(
                SourceReport(
                    connector_key=ctype.key, connector_name=ctype.name, available=True, state=state,
                    note="Covered by Rovo MCP for this search.",
                )
            )
            continue

        found = await connector.search_entities(hint)  # type: ignore[attr-defined]
        reports.append(
            SourceReport(
                connector_key=ctype.key, connector_name=ctype.name, available=True, state=state,
                note=(
                    f"{len(found)} candidate(s)."
                    if found
                    else f"Nothing in {ctype.name} matched that name."
                ),
                candidates=found,
            )
        )
    return reports


async def _draft_templates(
    session: AsyncSession, filled: dict[str, Candidate]
) -> list[TemplateProposal]:
    catalog = (await session.execute(select(Template))).scalars().all()
    proposals: list[TemplateProposal] = []
    for template in sorted(catalog, key=lambda t: t.key):
        bindings = [_rewrite(template.key, widget, filled) for widget in template.widgets]
        ready = [b for b in bindings if b.ready]
        if template.key in PROGRAMME_TEMPLATES:
            propose, reason = False, (
                "Programme-level — it rolls several projects up, so it is never enabled from one "
                "team's sources."
            )
        elif ready:
            propose = True
            reason = f"{len(ready)} of {len(bindings)} widgets resolved from discovered sources."
        elif not any(b.unresolved_slots for b in bindings):
            propose, reason = False, (
                "None of its widgets name a team-specific value, so discovery has nothing to "
                "confirm here. Enable it and check the queries yourself."
            )
        else:
            propose, reason = False, (
                "Nothing was discovered for any of its widgets. Enable it and bind the widgets "
                "by hand."
            )
        proposals.append(
            TemplateProposal(
                template_key=template.key, name=template.name, perspective=template.perspective,
                propose_enabled=propose, reason=reason, bindings=bindings,
            )
        )
    return proposals


def _value(candidate: Candidate, detail_key: str | None) -> str:
    """What this candidate contributes to a query: its ref, or a named piece of its detail."""
    if detail_key is None:
        return candidate.ref
    raw = candidate.detail.get(detail_key)
    if isinstance(raw, (list, tuple)):
        return ", ".join(str(item) for item in raw)
    return str(raw) if raw else ""


def _rewrite(template_key: str, widget: Any, filled: dict[str, Candidate]) -> BindingProposal:
    """Substitute resolved values into one catalog query.

    A query needing a slot nothing filled comes back empty rather than pointing at the
    exemplar team. Missing is never green, and an inherited query is not missing — it is wrong.
    """
    query = widget.query
    used: list[str] = []
    unresolved: list[str] = []
    for slot, pattern, replacement, detail_key in SUBSTITUTIONS:
        if not pattern.search(widget.query):
            continue
        candidate = filled.get(slot)
        value = _value(candidate, detail_key) if candidate else ""
        if not value:
            if slot not in unresolved:
                unresolved.append(slot)
            continue
        query = pattern.sub(replacement.format(value=value), query)
        if slot not in used:
            used.append(slot)

    if unresolved:
        query = ""

    leftovers = sorted(set(LEFTOVER.findall(query))) if query else []
    return BindingProposal(
        template_key=template_key, widget_name=widget.name, connector_key=widget.connector_key,
        position=widget.position, catalog_query=widget.query, query=query,
        filled_slots=used, unresolved_slots=unresolved, leftovers=leftovers,
        note=(
            f"Needs {', '.join(unresolved)} — nothing was discovered for it, so this widget "
            "renders Missing until you bind it."
            if unresolved
            else (
                "Carried from the template unchanged — it names no team-specific value, so "
                "check that it applies here."
                if not used
                else ""
            )
        ),
    )


async def validate(session: AsyncSession, proposals: list[TemplateProposal]) -> None:
    """Run each resolved query through the connector's own preview. Advisory, in place.

    A query that previews empty is not blocked — the substitution is deterministic and every
    value in it came from a source — but it is flagged, because a proposal that returns nothing
    on day one usually means the team is not tagging at source yet.
    """
    types = {
        t.key: t for t in (await session.execute(select(ConnectorType))).scalars().all()
    }
    instances = {
        i.connector_key: i
        for i in (await session.execute(select(ConnectorInstance))).scalars().all()
    }
    for template in proposals:
        for binding in template.bindings:
            if not binding.ready:
                continue
            ctype = types.get(binding.connector_key)
            if ctype is None:
                binding.note = f"No connector registered for {binding.connector_key}."
                continue
            instance = instances.get(binding.connector_key)
            if instance is None or instance.state in ("not_configured", "disabled"):
                binding.note = (
                    f"{ctype.name} is not connected, so this query could not be checked. "
                    "The widget will render Missing until it is."
                )
                continue
            connector = get_connector(
                ctype.key, ctype.name, instance.config, instance.secret_refs
            )
            try:
                rows = await connector.preview_data(binding.query, limit=5)
            except Exception:  # a failed preview is a finding, not a 500
                # The exception text can name internal hosts; it goes to the log, not the draft.
                logger.warning("Preview failed for %s during onboarding", ctype.key, exc_info=True)
                binding.note = f"{ctype.name} could not preview this query. Check it before relying on it."
                continue
            binding.row_count = len(rows)
            binding.validated = bool(rows)
            binding.note = (
                f"Previewed {len(rows)} row(s) from {ctype.name}."
                if rows
                else (
                    f"{ctype.name} accepted the query but returned nothing. Usually that means "
                    "the team is not tagging at source yet — check before relying on it."
                )
            )


def _note(sources: list[SourceReport], filled: dict[str, Candidate]) -> str:
    if not any(s.available for s in sources):
        return (
            "No source could be searched, so there is nothing to propose. Set the project up by "
            "hand — the manual form does everything this would have."
        )
    if not filled:
        return (
            "The sources were searched and nothing matched that name. Try the name as it appears "
            "in Jira, or set the project up by hand."
        )
    missing = [s for s in ("jira_project", "confluence_root") if s not in filled]
    if missing:
        return (
            f"Partial: {len(filled)} source(s) resolved, but {', '.join(missing)} was not found. "
            "Widgets that need it will render Missing until you bind them."
        )
    return f"{len(filled)} source(s) resolved. Confirm each one before accepting."
