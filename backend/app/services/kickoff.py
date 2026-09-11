"""Feature Kickoff: from a PRD to a checked, tagged plan that a named person confirms.

The steps and the rule each one enforces (docs/PROPOSAL-PRD-Intake.md):

1. **start** reads the PRD and extracts facts, each quoted. The page is stored at the version
   read, so every quote stays checkable against what was actually read.
2. **update_facts** is the person correcting what was read. Every rule re-resolves, so choices
   and findings made on the old facts are cleared rather than silently kept.
3. **choose** records what to do. A recommended action can be left out only with a reason,
   because scoped-out is not passed. The selected checks run here, read-only, and what they read
   (catalog, specs, index, registry) is frozen into the session's snapshot.
4. **decide** accepts or dismisses recommended steps and leaves plan items out.
5. **apply** is the only write, and only for the person who confirms it. The plan is frozen and
   the confirmation recorded before the first write; a dry run records what would be created,
   a live run creates it. A live run that partly fails can be retried, and the retry finds what
   already exists instead of duplicating it.
"""

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import atlassian_rest, github_specs, product_index, xray_cloud
from app.core.config import get_settings
from app.models.evidence import ArtifactDefinition
from app.models.kickoff import KickoffSession
from app.models.project import Project
from app.schemas import kickoff as out
from app.services import kickoff_checks as checks_service
from app.services import kickoff_plan as planner
from app.services import kickoff_sources as sources
from app.services import kickoff_write as writing
from app.services import model_provider
from app.services.kickoff_extract import (
    Structure,
    facts_by_claude,
    facts_by_rules,
    lines_of,
    structure,
)
from app.services.kickoff_rules import (
    ACTION_BY_KEY,
    ACTIONS,
    ENUMS,
    FACT_LABELS,
    GROUP_LABELS,
    STANDARD_FOR_ACTION,
    VALUE_LABELS,
    Fact,
    Facts,
    fact_from,
    resolve,
    tier_for,
)
from app.services.kickoff_sources import Snap
from app.services.readiness import is_denied

logger = logging.getLogger("shiftleft.kickoff")

OUTCOME_LABEL = {
    "applies": "Recommended",
    "not_applicable": "Not applicable",
    "undetermined": "Needs your answer",
}
# An apply that has been "applying" this long is assumed to have died mid-way, and can be retried.
# The retry is safe: it looks up what already exists before creating anything.
STALE_APPLY = timedelta(minutes=10)
CONFIRMED = ("applying", "partial", "applied")


class Refused(Exception):
    """A step the rules don't allow. Carries the reasons as a list, like the rollout board."""

    def __init__(self, message: str, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.blockers = blockers or []


def write_mode() -> str:
    return get_settings().kickoff_write_mode


# --- Reading ----------------------------------------------------------------------------------


def prd_page(prd: dict, project: Project) -> out.PrdPage:
    return out.PrdPage(
        page_id=prd["page_id"], title=prd["title"], space=prd["space"], url=prd["url"],
        version=prd["version"], updated=prd.get("updated", ""), author=prd.get("author", ""),
        own_project=prd.get("project_key") == project.key,
    )


async def list_prds(project: Project, query: str = "") -> out.PrdList:
    try:
        found = await sources.list_prds(query)
    except sources.SourceUnavailable as exc:
        return out.PrdList(pages=[], note=f"PRD pages can't be listed: {exc}", available=False)
    pages = [prd_page(p, project) for p in found]
    pages.sort(key=lambda p: (not p.own_project, p.title))
    return out.PrdList(pages=pages, note=sources.note())


async def model_options() -> out.ModelOptions:
    providers = await model_provider.providers()
    default = next((p.key for p in providers if p.available and p.key != "rules"), "rules")
    return out.ModelOptions(
        providers=[out.ModelProvider(**asdict(p)) for p in providers], default_provider=default
    )


def connections() -> out.Connections:
    """What each read and write goes to, from configuration alone: nothing is called to answer."""
    settings = get_settings()
    rows: list[out.Connection] = []
    live_reads = sources.mode() == "live"
    atl = atlassian_rest.AtlassianRest()

    def state(ok: bool) -> str:
        return "configured" if ok else "not_configured"

    if live_reads:
        catalog_ok = atl.available and bool(settings.software_catalog_page_id)
        catalog_note = (f"Page {settings.software_catalog_page_id} on {atl.site}." if catalog_ok else
                        atl.unavailable_reason or "No catalog page (SHIFTLEFT_SOFTWARE_CATALOG_PAGE_ID).")
        github = github_specs.GitHubSpecs()
        index_state, index_note = product_index.state()
        rows += [
            out.Connection(key="confluence", name="Confluence (PRD pages)", direction="read",
                           state=state(atl.available),
                           note=(f"Pages labelled {settings.kickoff_prd_label} on {atl.site}, as "
                                 f"{atl.account}." if atl.available else atl.unavailable_reason)),
            out.Connection(key="catalog", name="Software catalog", direction="read",
                           state=state(catalog_ok), note=catalog_note),
            out.Connection(key="github", name="GitHub (API specs)", direction="read",
                           state=state(github.available),
                           note=f"{github.api}, read at a pinned commit." if github.available
                           else github.unavailable_reason),
            out.Connection(key="product_index", name="Product index", direction="read",
                           state=index_state, note=index_note),
        ]
    else:
        rows.append(out.Connection(key="examples", name="Example pages", direction="read", state="example",
                                   note=sources.FIXTURE_NOTE))
    rows.append(out.Connection(
        key="registry", name="Standards and vendor registry", direction="read", state="configured",
        note=f"{len(sources.standards())} standards, pinned; vendors reviewed by their owners.",
    ))
    if write_mode() == "live":
        xray = xray_cloud.XrayCloud()
        rows += [
            out.Connection(key="jira_write", name="Jira (epic, stories, tasks)", direction="write",
                           state=state(atl.available),
                           note=(f"As {atl.account}, into the kickoff's own project only." if atl.available
                                 else atl.unavailable_reason)),
            out.Connection(key="xray_write", name="Xray (tests, test plan)", direction="write",
                           state=state(xray.available),
                           note=xray.base if xray.available else xray.unavailable_reason),
            out.Connection(key="confluence_write", name="Confluence (pages, catalog)", direction="write",
                           state=state(atl.available),
                           note="New pages under the PRD; the catalog edited by row, version-checked."
                           if atl.available else atl.unavailable_reason),
            out.Connection(key="index_write", name="Product index", direction="write", state="not_built",
                           note="No writer yet: index rows are handed off to a person."),
        ]
    else:
        rows.append(out.Connection(
            key="dry_run", name="Jira, Xray and Confluence", direction="write", state="dry_run",
            note="Dry run: confirming records what would be created.",
        ))
    return out.Connections(sources=sources.mode(), write_mode=write_mode(), connections=rows)


async def start(
    session: AsyncSession, project: Project, actor: str, page_id: str, provider_key: str, model: str
) -> KickoffSession:
    chosen = await model_provider.choose(provider_key, model)
    if isinstance(chosen, str):
        raise Refused(chosen)
    provider, model = chosen
    prd = await sources.prd(page_id)  # SourceUnavailable propagates: the route says why
    if prd is None:
        raise LookupError("PRD page not found")

    lines = lines_of(prd["body"])
    shape = structure(lines)
    reader = "rules"
    if provider.key == "claude":
        try:
            facts = await facts_by_claude(lines, shape, model)
            reader = "claude"
            note = (
                f"Read by {model}. Every fact is quoted from the PRD; nothing is applied until you "
                "confirm."
            )
        except Exception as exc:  # any failure degrades to the keyword reader, and says so
            logger.warning("Claude couldn't read the PRD, falling back to the keyword reader: %s", exc)
            facts = facts_by_rules(lines, shape)
            note = f"{model} couldn't be reached, so the keyword reader was used instead. Check each fact."
    else:
        facts = facts_by_rules(lines, shape)
        note = "Read by the keyword reader (no model). Every fact still carries the sentence it came from."

    row = KickoffSession(
        project_id=project.id, actor=actor, page_id=prd["page_id"], page_title=prd["title"][:300],
        page_version=prd["version"], status="context", provider=provider.key, model=model,
        reader=reader, note=note,
        data={
            "source_mode": sources.mode(),
            # The page as read. PRDs are requirements, not sensitive evidence (rule 10), and the
            # quotes are only checkable against the version they came from.
            "prd": prd,
            "facts": {k: asdict(f) for k, f in facts.items()},
            "structure": asdict(shape),
            "choices": {}, "checks": [], "checked_at": None, "snapshot": None,
            "decisions": {}, "excluded": [], "results": [], "applied_plan": None,
        },
    )
    session.add(row)
    return row


# --- Deciding ---------------------------------------------------------------------------------


def _prd(row: KickoffSession) -> dict:
    stored = row.data.get("prd")
    if stored:
        return stored
    # Sessions from before pages were stored on the session read the example they came from.
    return next(p for p in sources._fixtures()["prds"] if p["page_id"] == row.page_id)


def _facts(row: KickoffSession) -> Facts:
    return {k: fact_from(v) for k, v in row.data["facts"].items()}


def _shape(row: KickoffSession) -> Structure:
    return Structure(**row.data["structure"])


def _snap(row: KickoffSession) -> Snap:
    return Snap(row.data.get("snapshot"))


def _writable(row: KickoffSession) -> None:
    if row.status in CONFIRMED:
        raise Refused("This kickoff has been confirmed. Start a new one to plan again.")


def update_facts(row: KickoffSession, edits: list[out.FactEdit], actor: str) -> None:
    _writable(row)
    data = dict(row.data)
    facts = dict(data["facts"])
    shape = dict(data["structure"])
    problems: list[str] = []
    for edit in edits:
        if edit.key not in FACT_LABELS:
            problems.append(f"{edit.key!r} is not a fact this page records.")
            continue
        values = [v.strip() for v in edit.values if v.strip()]
        if edit.key in ENUMS:
            bad = [v for v in values if v not in ENUMS[edit.key]]
            if bad:
                problems.append(f"{FACT_LABELS[edit.key]}: {', '.join(bad)} isn't an allowed value.")
                continue
        previous = fact_from(facts[edit.key])
        facts[edit.key] = asdict(Fact(
            edit.key, list(dict.fromkeys(values)), "confirmed", previous.quotes, confirmed_by=actor,
        ))
        if edit.key == "services":
            # A service the person names is checked like one the PRD named, with no operation
            # to look for until one is added to the PRD.
            kept = [d for d in shape["dependencies"] if d["service"] in values]
            named = {d["service"] for d in kept}
            kept += [
                {"service": s, "operation": "", "quote": {"text": f"Added by {actor}", "section": "Context"}}
                for s in values if s not in named
            ]
            shape["dependencies"] = kept
    if problems:
        raise Refused("Some facts couldn't be recorded.", problems)
    # New facts, new outcomes: nothing decided on the old ones carries over silently.
    data.update(facts=facts, structure=shape, choices={}, checks=[], checked_at=None, snapshot=None,
                decisions={}, excluded=[])
    row.data = data
    row.status = "context"


def _actions(row: KickoffSession, facts: Facts) -> list[out.ActionOut]:
    choices = row.data.get("choices", {})
    result = []
    for action in ACTIONS:
        resolution = resolve(action.key, facts)
        choice = choices.get(action.key)
        reason = (choice or {}).get("skip_reason", "")
        result.append(out.ActionOut(
            key=action.key, label=action.label, group=action.group,
            group_label=GROUP_LABELS[action.group], target=action.target,
            description=action.description, outcome=resolution.outcome,
            outcome_label=OUTCOME_LABEL[resolution.outcome], reason=resolution.reason,
            quotes=[out.Quote(**q) for q in resolution.quotes], question=resolution.question,
            recommended=resolution.recommended,
            selected=choice["selected"] if choice else resolution.recommended,
            skip_reason=reason, skip_flagged=bool(reason) and is_denied(reason),
        ))
    return result


def _selected(row: KickoffSession, facts: Facts) -> list[str]:
    return [a.key for a in _actions(row, facts) if a.selected]


async def choose(row: KickoffSession, choices: list[out.Choice]) -> None:
    _writable(row)
    facts = _facts(row)
    by_key = {c.key: c for c in choices}
    unknown = [k for k in by_key if k not in {a.key for a in ACTIONS}]
    if unknown:
        raise Refused("Unknown actions.", [f"{k!r} is not an action on this page." for k in unknown])

    stored: dict[str, dict] = {}
    missing_reasons: list[str] = []
    for action in ACTIONS:
        resolution = resolve(action.key, facts)
        choice = by_key.get(action.key)
        selected = choice.selected if choice else resolution.recommended
        reason = (choice.skip_reason.strip() if choice else "")
        if resolution.recommended and not selected and not reason:
            missing_reasons.append(
                f"{action.label} is {OUTCOME_LABEL[resolution.outcome].lower()}. Say why you're "
                "leaving it out; the reason goes on the feasibility record."
            )
        stored[action.key] = {"selected": selected, "skip_reason": "" if selected else reason}
    if missing_reasons:
        raise Refused("Leaving a recommended action out needs a reason.", missing_reasons)

    selected_keys = [k for k, c in stored.items() if c["selected"]]
    shape = _shape(row)
    # Only what the plan needs is read: specs for the services the PRD depends on.
    snapshot = await sources.snapshot([d["service"] for d in shape.dependencies])
    snap = Snap(snapshot)
    lines = lines_of(_prd(row)["body"])
    parties = facts["third_parties"].values if facts.get("third_parties") else []

    data = dict(row.data)
    data["choices"] = stored
    data["snapshot"] = snapshot
    data["checks"] = checks_service.dump(checks_service.run(selected_keys, shape, lines, parties, snap))
    data["checked_at"] = datetime.now(timezone.utc).isoformat()
    # Findings changed, so decisions on the suggestions they produced start again.
    data["decisions"] = {k: v for k, v in data.get("decisions", {}).items()
                         if not k.startswith(("dependency:", "deprecation:", "catalog_entry:", "spike:",
                                              "standard_gap:", "standard_access:", "conformance:"))}
    data["excluded"] = []
    row.data = data
    row.status = "planned"


def _suggestions(row: KickoffSession, project: Project, facts: Facts) -> list[planner.Suggestion]:
    tier = tier_for(facts)
    shape = _shape(row)
    found = planner.context_suggestions(facts, tier, shape, project.key)
    if row.status in ("planned", *CONFIRMED):
        found += planner.finding_suggestions(checks_service.load(row.data.get("checks", [])), _snap(row))
    # One entry per key; the first reason stands.
    return list({s.key: s for s in found}.values())


async def artifacts(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(select(ArtifactDefinition).order_by(ArtifactDefinition.position))).scalars()
    return [{"key": r.key, "name": r.name, "gate": r.gate, "accountable": r.accountable} for r in rows]


def _plan(row: KickoffSession, project: Project, facts: Facts, defs: list[dict]) -> planner.Plan:
    return planner.build(
        project_key=project.key, project_name=project.name, prd=_prd(row), facts=facts, shape=_shape(row),
        tier=tier_for(facts), selected=_selected(row, facts),
        checks=checks_service.load(row.data.get("checks", [])),
        suggestions=_suggestions(row, project, facts), decisions=row.data.get("decisions", {}),
        excluded=set(row.data.get("excluded", [])), artifacts=defs, snap=_snap(row),
    )


def decide(row: KickoffSession, project: Project, defs: list[dict], body: out.PlanUpdate) -> None:
    """Accept or dismiss recommended steps (any time before apply); leave plan items out (once planned)."""
    _writable(row)
    facts = _facts(row)
    known = {s.key for s in _suggestions(row, project, facts)}
    unknown = [k for k in body.decisions if k not in known]
    if unknown:
        raise Refused("Unknown recommended steps.", [f"{k!r} isn't recommended here." for k in unknown])
    if body.excluded is not None and row.status != "planned":
        raise Refused("Choose what to do first; plan items exist only once the plan is drafted.")
    data = {**row.data, "decisions": {**row.data.get("decisions", {}), **body.decisions}}
    row.data = data
    if body.excluded is not None:
        plan_ids = {i.id for i in _plan(row, project, facts, defs).items}
        stray = [i for i in body.excluded if i not in plan_ids]
        if stray:
            raise Refused("Unknown plan items.", [f"{i!r} isn't in the plan." for i in stray])
        row.data = {**data, "excluded": list(dict.fromkeys(body.excluded))}


# --- Confirming and applying ---------------------------------------------------------------------


def _stale(row: KickoffSession) -> bool:
    since = row.data.get("applying_since")
    return bool(since) and datetime.now(timezone.utc) - datetime.fromisoformat(since) > STALE_APPLY


def prepare_apply(row: KickoffSession, project: Project, defs: list[dict]) -> tuple[dict, list[dict]]:
    """The plan to apply (frozen, if it already was) and the results so far."""
    mode = write_mode()
    if mode == "live" and row.data.get("source_mode", "fixtures") != "live":
        raise Refused("This kickoff read example pages, so it can't write to live systems. Start a new one.")
    if row.status == "planned":
        plan = _plan(row, project, _facts(row), defs)
        if not any(item.included for item in plan.items):
            raise Refused("The plan is empty, so there is nothing to create.")
        snap = _snap(row)
        return {**planner.dump(plan), "catalog_version": snap.catalog["version"],
                "index_version": snap.index["version"]}, []
    if row.status == "partial" or (row.status == "applying" and _stale(row)):
        if row.data.get("write_mode") != mode:
            raise Refused(f"This kickoff was applied as a {row.data.get('write_mode')}; the service now "
                          f"writes as {mode}. Start a new kickoff.")
        return row.data["applied_plan"], row.data.get("results", [])
    if row.status == "applying":
        raise Refused("This plan is being applied right now. Wait for it to finish.")
    if row.status == "applied":
        raise Refused("This kickoff has been applied. Start a new one to plan again.")
    raise Refused("There is no plan to confirm yet. Choose what to do and review the plan first.")


def write_context(row: KickoffSession, project: Project, defs: list[dict], actor: str) -> writing.Context:
    """What the writers need to know, including everything the feasibility page records."""
    facts = _facts(row)
    tier = tier_for(facts)
    prd = _prd(row)
    snap = _snap(row)
    checks = checks_service.load(row.data.get("checks", []))
    selected = _selected(row, facts)
    approved_at = as_utc(row.approved_at) or datetime.now(timezone.utc)
    record = {
        "session_id": row.id, "prd": {k: prd[k] for k in ("page_id", "title", "url", "version", "space")},
        "tier": tier.tier, "tier_reason": tier.reason, "drafted_by": drafted_by(row),
        "approved_by": row.approved_by or actor, "approved_at": approved_at.strftime("%Y-%m-%d %H:%M UTC"),
        "facts": [{"label": FACT_LABELS[f.key], "values": [VALUE_LABELS.get(v, v) for v in f.values],
                   "quotes": f.quotes, "confirmed_by": f.confirmed_by} for f in facts.values()],
        "actions": [a.model_dump() for a in _actions(row, facts)],
        "checks": checks_service.dump(checks),
        "headline": checks_service.headline(checks).reasons if checks else [],
        "services": facts["services"].values if facts.get("services") else [],
        "data_classes": [VALUE_LABELS.get(v, v) for v in (facts["data_classes"].values
                                                          if facts.get("data_classes") else [])],
        "standards": [ACTION_BY_KEY[a].label for a in STANDARD_FOR_ACTION if a in selected],
    }
    return writing.Context(
        session_id=row.id, project_key=project.key, actor=row.approved_by or actor,
        feature=planner.feature_name(prd), prd=prd, own_space=prd["space"] == project.key,
        snapshot=snap.data, record=record,
    )


async def claim(db: AsyncSession, row: KickoffSession, actor: str, plan: dict, mode: str) -> None:
    """Record the confirmation and mark the session applying, atomically, before any write.

    Two confirmations racing (a double click, two tabs) can't both proceed: only the request whose
    conditional update matched the status it read goes on; the other is refused.
    """
    status = row.status
    claimed = await db.execute(
        update(KickoffSession).where(KickoffSession.id == row.id, KickoffSession.status == status)
        .values(status="applying")
    )
    if claimed.rowcount != 1:
        raise Refused("This plan is being applied right now. Wait for it to finish.")
    now = datetime.now(timezone.utc)
    data = dict(row.data)
    if status == "planned":
        # The plan as confirmed. Every retry applies exactly this, never a recomputed one.
        data["applied_plan"] = plan
        row.approved_by, row.approved_at = actor, now
    data["write_mode"] = mode
    data["applying_since"] = now.isoformat()
    data["attempts"] = [*data.get("attempts", []), {"by": actor, "at": now.isoformat(), "mode": mode}]
    row.data = data
    row.status = "applying"


def finish_apply(row: KickoffSession, items: list[dict], results: list[writing.Result]) -> dict:
    data = dict(row.data)
    data["results"] = writing.dump(results)
    data["applying_since"] = None
    row.data = data
    failed = sum(1 for r in results if r.status == "failed")
    row.status = "partial" if failed else "applied"
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return {"mode": data["write_mode"], "counts": counts, "attempt": len(data.get("attempts", []))}


def interrupted(items: list[dict], previous: list[dict], reason: str) -> list[writing.Result]:
    """Results when the writer itself broke: what was done stays done, the rest failed with why."""
    done = {r["item_id"]: r for r in previous if r["status"] in writing.DONE}
    return [
        writing.Result(**{k: v for k, v in done[i["id"]].items() if k in writing.Result.__dataclass_fields__})
        if i["id"] in done else
        writing.Result(i["id"], i["group"], i["title"], "failed", f"Not attempted: {reason}")
        for i in items
    ]


# --- The view ---------------------------------------------------------------------------------


def _fact_out(fact: Fact) -> out.FactOut:
    return out.FactOut(
        key=fact.key, label=FACT_LABELS[fact.key], values=fact.values,
        value_labels=[VALUE_LABELS.get(v, v) for v in fact.values], status=fact.status,
        quotes=[out.Quote(**q) for q in fact.quotes], confirmed_by=fact.confirmed_by,
        allowed=[out.AllowedValue(value=v, label=VALUE_LABELS.get(v, v)) for v in ENUMS.get(fact.key, ())],
    )


def as_utc(moment: datetime | None) -> datetime | None:
    """SQLite hands timestamps back without a zone; they were written in UTC, so say so."""
    return moment.replace(tzinfo=timezone.utc) if moment and moment.tzinfo is None else moment


def drafted_by(row: KickoffSession) -> str:
    return f"Claude ({row.model})" if row.reader == "claude" else "Rule-based reader"


def view(row: KickoffSession, project: Project, defs: list[dict]) -> out.KickoffOut:
    prd = _prd(row)
    facts = _facts(row)
    tier = tier_for(facts)
    decisions = row.data.get("decisions", {})
    check_results = checks_service.load(row.data.get("checks", []))
    snap = _snap(row)

    plan: out.PlanOut | None = None
    if row.status in CONFIRMED and row.data.get("applied_plan"):
        frozen = row.data["applied_plan"]
        plan = out.PlanOut(**{**frozen, "index_version": str(frozen.get("index_version", ""))})
    elif row.status == "planned":
        plan = out.PlanOut(**planner.dump(_plan(row, project, facts, defs)),
                           catalog_version=snap.catalog["version"], index_version=snap.index["version"])

    source_mode = row.data.get("source_mode", "fixtures")
    return out.KickoffOut(
        id=row.id, project_id=row.project_id, status=row.status,
        page=prd_page(prd, project), provider=row.provider, model=row.model, reader=row.reader,
        drafted_by=drafted_by(row), note=row.note,
        source_note=sources.LIVE_NOTE if source_mode == "live" else sources.FIXTURE_NOTE,
        source_mode=source_mode,
        write_mode=row.data.get("write_mode") or write_mode(),
        facts=[_fact_out(f) for f in facts.values()],
        tier=out.TierOut(tier=tier.tier, reason=tier.reason, undetermined=tier.undetermined,
                         quotes=[out.Quote(**q) for q in tier.quotes]),
        actions=_actions(row, facts),
        suggestions=[
            out.SuggestionOut(
                key=s.key, label=s.label, why=s.why, target=s.target, source=s.source, kind=s.kind,
                decision=decisions.get(s.key, "pending"),
                drawn_from=[out.DrawnFrom(**d) for d in s.drawn_from],
            )
            for s in _suggestions(row, project, facts)
        ],
        checks=[out.CheckOut(**checks_service.dump([c])[0]) for c in check_results],
        headline=checks_service.headline(check_results) if row.status != "context" else None,
        checked_at=row.data.get("checked_at"),
        plan=plan, approved_by=row.approved_by, approved_at=as_utc(row.approved_at),
        results=[out.ResultOut(**{k: v for k, v in r.items() if k != "issue_id"})
                 for r in row.data.get("results", [])],
        created_at=as_utc(row.created_at),
    )
