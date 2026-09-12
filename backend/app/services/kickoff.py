"""Feature Kickoff: a PRD taken, in seven steps, to an ordered backlog a named person creates.

1. **PRD**: a Confluence page, read over REST or through the Rovo MCP server.
2. **Repos to code in**, and 3. **repos relied on**: read from GitHub at a pinned commit.
4. **Compliance**: proposed from the PRD, approved (or chosen by hand) by a named person.
5. **API docs**, and 6. **third-party providers**: read from the URLs given.
7. **The analysis**: a model (Claude, or one on the team's Cursor plan) drafts what changes in
   which repo, what each dependency must provide, and the Jira tasks in order. People edit the
   tasks, then create them in their backlog.

An analysis is saved as it goes, and can be reopened, changed and run again. The plan keeps a
fingerprint of the inputs it was drafted from, so a plan older than its inputs says which ones
changed, and can't be created in Jira until it's run again. Nothing here is example data: an
input that couldn't be read stays on the page with the reason.
"""

import asyncio
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import atlassian_rest
from app.models.kickoff import KickoffAnalysis, KickoffRun
from app.models.project import Project
from app.schemas import kickoff as out
from app.services import kickoff_ai as ai
from app.services import kickoff_backlog as backlog
from app.services import kickoff_compliance as compliance
from app.services import kickoff_settings as settings_service
from app.services import kickoff_sources as sources
from app.services import kickoff_tdd as tdd
from app.services import model_provider
from app.services.kickoff_backlog import Refused

STEPS: list[tuple[str, str]] = [
    ("prd", "PRD"),
    ("repos", "Repos to code in"),
    ("dependencies", "What we rely on"),
    ("compliance", "Compliance"),
    ("api_docs", "API docs"),
    ("third_parties", "Third-party APIs"),
    ("tdd", "Technical design"),
    ("plan", "Analysis"),
]
STALE_LABELS = {
    "prd": "the PRD",
    "repos": "the repos to code in",
    "dependencies": "what you rely on",
    "compliance": "the approved compliance",
    "api_docs": "the API docs",
    "third_parties": "the third-party APIs",
    "tdd": "the technical design sections",
}

__all__ = ["Refused"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def as_utc(moment: datetime | None) -> datetime | None:
    """SQLite hands timestamps back without a zone; they were written in UTC, so say so."""
    return moment.replace(tzinfo=timezone.utc) if moment and moment.tzinfo is None else moment


def _touch(row: KickoffAnalysis, actor: str, **changes: Any) -> None:
    row.inputs = {**row.inputs, **changes}
    row.updated_by = actor


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "item"


# --- Status and catalog -----------------------------------------------------------------------------


async def status(session: AsyncSession) -> out.KickoffStatus:
    """Where each read and write goes, from configuration alone. Never returns a credential."""
    rows: list[out.ConnectionOut] = []
    confluence = await sources.atlassian(session, ("confluence", "jira"))
    mcp = sources.rovo()
    if confluence:
        rows.append(
            out.ConnectionOut(
                key="confluence",
                name="Confluence (the PRD)",
                state="ready",
                via="REST",
                note=f"{confluence.host}, with {confluence.source}.",
            )
        )
    elif mcp:
        rows.append(
            out.ConnectionOut(
                key="confluence",
                name="Confluence (the PRD)",
                state="ready",
                via="Rovo MCP",
                note=f"Read through the Rovo MCP server on {mcp.site_url}.",
            )
        )
    else:
        rows.append(
            out.ConnectionOut(
                key="confluence",
                name="Confluence (the PRD)",
                state="not_configured",
                via="",
                note="Add the Confluence connector in Settings → Connectors, or configure Rovo MCP.",
            )
        )
    github = await sources.github(session)
    rows.append(
        out.ConnectionOut(
            key="github",
            name="GitHub (repos)",
            state="ready" if github.token else "fallback",
            via="REST",
            note=f"{github.web_host}, with {github.source}.",
        )
    )
    jira = await sources.atlassian(session, ("jira", "confluence"))
    rows.append(
        out.ConnectionOut(
            key="jira",
            name="Jira (creating the backlog)",
            state="ready" if jira else "not_configured",
            via="REST" if jira else "",
            note=f"{jira.host}, with {jira.source}."
            if jira
            else "Needed only for the last step. Add the Jira connector in Settings → Connectors.",
        )
    )
    providers = await model_provider.providers()
    ready = [p for p in providers if p.available and p.key in model_provider.AI_PROVIDERS]
    rows.append(
        out.ConnectionOut(
            key="ai",
            name="AI (the analysis)",
            state="ready" if ready else "fallback",
            via=" · ".join(p.name for p in ready),
            note="Compliance proposals and the plan are drafted by a model; a person accepts them."
            if ready
            else "No model: set SHIFTLEFT_ANTHROPIC_API_KEY, or sign in the Cursor CLI "
            "(docs/SETUP-Cursor-CLI.md). Until then drafts are rule-based and say so.",
        )
    )
    default = ready[0].key if ready else "rules"
    return out.KickoffStatus(
        connections=rows,
        providers=[out.ModelProvider(**asdict(p)) for p in providers],
        default_provider=default,
    )


def catalog() -> out.CatalogOut:
    return out.CatalogOut(
        frameworks=[
            out.FrameworkOut(**{k: f[k] for k in out.FrameworkOut.model_fields})
            for f in compliance.frameworks()
        ],
        providers=[
            out.ProviderCatalogOut(**{k: p[k] for k in out.ProviderCatalogOut.model_fields})
            for p in compliance.providers()
        ],
    )


# --- Step 1: the PRD ----------------------------------------------------------------------------------


async def _read_prd(session: AsyncSession, url: str, actor: str) -> dict[str, Any]:
    try:
        prd = await sources.read_prd(session, url)
    except sources.NotReadable as exc:
        raise Refused(str(exc)) from exc
    return {**prd, "read_by": actor}


async def create(session: AsyncSession, project: Project, actor: str, prd_url: str) -> KickoffAnalysis:
    prd = await _read_prd(session, prd_url, actor)
    # The service-wide defaults are copied in, not referenced: a later change to them never reaches
    # an analysis already under way, and every one of them stays editable here.
    inherited = settings_service.prefill(await settings_service.load(session))
    row = KickoffAnalysis(
        project_id=project.id,
        title=prd["title"][:300],
        status="draft",
        created_by=actor,
        updated_by=actor,
        inputs={**inherited, "prd": prd},
        runs=0,
    )
    session.add(row)
    return row


async def read_prd(session: AsyncSession, row: KickoffAnalysis, actor: str, prd_url: str) -> None:
    prd = await _read_prd(session, prd_url, actor)
    previous = row.inputs.get("prd") or {}
    if row.title in ("", "Untitled analysis", previous.get("title")):
        row.title = prd["title"][:300]
    _touch(row, actor, prd=prd)


def rename(row: KickoffAnalysis, actor: str, title: str) -> None:
    row.title = title.strip()[:300]
    row.updated_by = actor


# --- Steps 2 and 3: repos ------------------------------------------------------------------------------


def _clean_urls(urls: list[str]) -> list[str]:
    return list(dict.fromkeys(u.strip().rstrip("/") for u in urls if u.strip()))


async def set_repos(
    session: AsyncSession, row: KickoffAnalysis, role: str, urls: list[str], refresh: bool, actor: str
) -> None:
    """Step 2 takes repos to code in. Step 3 takes whatever we rely on — a repo, a Confluence page,
    or any other document — so the person pastes what they have and the link says which reader."""
    other = "dependencies" if role == "repos" else "repos"
    material = role == "dependencies"
    wanted = _clean_urls(urls)
    group = row.inputs.get(role) or {}
    previous = {r["url"]: r for r in group.get("items", [])}
    previous_docs = {d["url"]: d for d in group.get("docs", [])}
    access = await sources.github(session)
    atlassian = await sources.atlassian(session, ("confluence", "jira")) if material else None

    def kind(url: str) -> str:
        if not material:
            return "repo"
        return sources.classify(url, access.web_host, atlassian.host if atlassian else "")

    async def read_repo(url: str) -> dict[str, Any]:
        kept = previous.get(url)
        if kept and kept.get("ok") and not refresh:
            return kept
        try:
            read = await sources.read_repo(access, url)
            return {**read, "html_url": read["url"], "url": url}
        except sources.NotReadable as exc:
            return sources.repo_failure(url, str(exc))

    async def read_material(url: str, as_page: bool) -> dict[str, Any]:
        kept = previous_docs.get(url)
        if kept and kept.get("ok") and not refresh:
            return kept
        try:
            if as_page:
                return await sources.read_confluence_doc(session, url)
            return await sources.read_doc(url)
        except sources.NotReadable as exc:
            return sources.doc_failure(url, str(exc))

    kinds = {u: kind(u) for u in wanted}
    repo_urls = [u for u in wanted if kinds[u] == "repo"]
    doc_urls = [u for u in wanted if kinds[u] != "repo"]
    items, docs = await asyncio.gather(
        asyncio.gather(*(read_repo(u) for u in repo_urls)),
        asyncio.gather(*(read_material(u, kinds[u] == "confluence") for u in doc_urls)),
    )
    # One entry per repo, however it was written.
    seen: set[str] = set()
    unique = []
    for item in items:
        name = item["full_name"].lower()
        if name not in seen:
            seen.add(name)
            unique.append(item)
    elsewhere = {
        r["full_name"].lower() for r in (row.inputs.get(other) or {}).get("items", []) if r.get("ok")
    }
    clash = [r["full_name"] for r in unique if r.get("ok") and r["full_name"].lower() in elsewhere]
    if clash:
        where = "what we rely on" if role == "repos" else "repos to code in"
        raise Refused(f"Already listed under {where}: {', '.join(clash)}. A repo is one or the other.")
    saved = {"items": unique, "saved": True, "saved_by": actor, "saved_at": _now()}
    if material:
        saved["docs"] = list(docs)
    _touch(row, actor, **{role: saved})


# --- Step 4: compliance ---------------------------------------------------------------------------------


def _prd_mark(prd: dict[str, Any] | None) -> str:
    return f"{prd['page_id']}@{prd['version']}" if prd else ""


async def suggest_compliance(row: KickoffAnalysis, actor: str) -> None:
    prd = row.inputs.get("prd")
    if not prd:
        raise Refused("Fetch the PRD first: compliance is proposed from what it says.")
    found, by, note = await ai.suggest_compliance(prd["lines"], await model_provider.default_ai())
    current = row.inputs.get("compliance") or {}
    _touch(
        row,
        actor,
        compliance={
            **current,
            "suggestions": found,
            "suggested_by": by,
            "suggested_note": note,
            "suggested_at": _now(),
            "suggested_for": _prd_mark(prd),
        },
    )


def approve_compliance(row: KickoffAnalysis, actor: str, body: out.ComplianceApproval) -> None:
    unknown = [k for k in body.selected if compliance.framework(k) is None]
    if unknown:
        raise Refused("Unknown compliance frameworks.", [f"{k!r} isn't in the catalog." for k in unknown])
    custom = list({c.name.strip().lower(): c.model_dump() for c in body.custom if c.name.strip()}.values())
    current = row.inputs.get("compliance") or {}
    _touch(
        row,
        actor,
        compliance={
            **current,
            "selected": list(dict.fromkeys(body.selected)),
            "custom": custom,
            "approved_by": actor,
            "approved_at": _now(),
        },
    )


def _approved(row: KickoffAnalysis) -> list[dict[str, Any]]:
    c = row.inputs.get("compliance") or {}
    if not c.get("approved_by"):
        return []
    items = []
    for key in c.get("selected", []):
        entry = compliance.framework(key)
        if entry:
            items.append({"key": key, "name": entry["name"], "obligations": entry["obligations"], "note": ""})
    for custom in c.get("custom", []):
        items.append(
            {
                "key": f"custom-{_slug(custom['name'])}",
                "name": custom["name"],
                "obligations": [],
                "note": custom.get("note", ""),
            }
        )
    return items


# --- Steps 5 and 6: docs and providers -------------------------------------------------------------------


async def _read_doc(url: str) -> dict[str, Any]:
    try:
        return await sources.read_doc(url)
    except sources.NotReadable as exc:
        return sources.doc_failure(url, str(exc))


async def set_docs(row: KickoffAnalysis, urls: list[str], refresh: bool, actor: str) -> None:
    wanted = _clean_urls(urls)
    previous = {d["url"]: d for d in (row.inputs.get("api_docs") or {}).get("items", [])}

    async def read(url: str) -> dict[str, Any]:
        kept = previous.get(url)
        return kept if kept and kept.get("ok") and not refresh else await _read_doc(url)

    items = list(await asyncio.gather(*(read(u) for u in wanted)))
    _touch(row, actor, api_docs={"items": items, "saved": True, "saved_by": actor, "saved_at": _now()})


async def set_providers(row: KickoffAnalysis, body: out.ProvidersUpdate, actor: str) -> None:
    previous = {p["name"].lower(): p for p in (row.inputs.get("third_parties") or {}).get("items", [])}
    chosen: dict[str, dict[str, Any]] = {}
    for p in body.providers:
        entry = compliance.provider(p.key) if p.key else None
        name = (p.name.strip() or (entry or {}).get("name", ""))[:120]
        if p.key and entry is None:
            raise Refused(f"{p.key!r} isn't a provider in the catalog. Add it by name instead.")
        if not name:
            raise Refused("A provider added by hand needs a name.")
        chosen.setdefault(name.lower(), {"key": p.key, "name": name, "docs_url": p.docs_url.strip()})

    async def read(item: dict[str, Any]) -> dict[str, Any]:
        kept = previous.get(item["name"].lower())
        if not item["docs_url"]:
            return {**item, "doc": None}
        if (
            kept
            and kept.get("docs_url") == item["docs_url"]
            and (kept.get("doc") or {}).get("ok")
            and not body.refresh
        ):
            return {**item, "doc": kept["doc"]}
        return {**item, "doc": await _read_doc(item["docs_url"])}

    items = list(await asyncio.gather(*(read(i) for i in chosen.values())))
    _touch(row, actor, third_parties={"items": items, "saved": True, "saved_by": actor, "saved_at": _now()})


# --- Step 7: the technical design ----------------------------------------------------------------


async def read_tdd_page(session: AsyncSession, row: KickoffAnalysis, actor: str, mode: str, url: str) -> None:
    """Read the page a design is written from or into, and offer its sections to tick.

    Nothing is written here. Reading is what makes the checklist real: the sections offered are the
    ones the page actually has, plus - for a sample - the standard ones it doesn't.
    """
    try:
        page, lines, _via, via_label = await sources.read_page(session, url)
        storage = await _tdd_storage(session, page["page_id"])
    except sources.NotReadable as exc:
        raise Refused(str(exc)) from exc
    offered = tdd.page_sections(storage, mode)
    if not offered:
        raise Refused(
            "That page has no headings, so there are no sections to choose. "
            "Point at a design with headings, or at a template that has them."
        )
    current = row.inputs.get("tdd") or {}
    _touch(
        row,
        actor,
        tdd={
            **current,
            "enabled": True,
            "mode": mode,
            "source": {
                "url": page.get("url") or url,
                "page_id": page["page_id"],
                "title": page.get("title", ""),
                "space": page.get("space", ""),
                "version": int(page.get("version") or 0),
                "read_with": via_label,
                "read_at": _now(),
                "line_count": len(lines),
            },
            "sections": offered,
            # A page read again is a different page: the ticks are confirmed against what it says now.
            "selected": [k for k in current.get("selected", []) if any(o["key"] == k for o in offered)]
            or [o["key"] for o in offered if o.get("recommended")],
            "approved_by": None,
            "approved_at": None,
            "title": current.get("title") or "",
        },
    )


async def _tdd_storage(session: AsyncSession, page_id: str) -> str:
    """The page's storage markup, which is what a section is replaced inside of."""
    access = await sources.atlassian(session, ("confluence", "jira"))
    if access is None:
        raise sources.NotReadable(
            "A design is written over Confluence REST, which needs the Confluence connector in "
            "Settings → Connectors. Reading through Rovo MCP isn't enough to write a page."
        )
    try:
        return (await access.client.page(page_id)).storage
    except atlassian_rest.AtlassianError as exc:
        raise sources.NotReadable(str(exc)) from exc


def set_tdd(row: KickoffAnalysis, actor: str, body: out.TddUpdate) -> None:
    """Confirm what will be written, and where.

    This confirmation is the acceptance: the run writes these sections and no others, so it is
    recorded against a named person with the time they gave it.
    """
    current = row.inputs.get("tdd") or {}
    if not body.enabled:
        _touch(row, actor, tdd={**current, "enabled": False, "approved_by": actor, "approved_at": _now()})
        return
    if not current.get("source"):
        raise Refused("Read the page first: the sections are the ones it actually has.")
    offered = {o["key"] for o in current.get("sections", [])}
    unknown = [k for k in body.selected if k not in offered]
    if unknown:
        raise Refused("Those sections aren't on that page.", [f"{k!r} wasn't offered." for k in unknown])
    if not body.selected:
        raise Refused("Tick at least one section, or turn the design off for this analysis.")
    if current.get("mode") == "sample" and not body.space_key.strip():
        raise Refused("Say which space the design is created in.")
    _touch(
        row,
        actor,
        tdd={
            **current,
            "enabled": True,
            "selected": [k for k in [o["key"] for o in current["sections"]] if k in set(body.selected)],
            "space_key": body.space_key.strip().upper(),
            "parent_url": body.parent_url.strip(),
            "title": body.title.strip()[:250],
            "approved_by": actor,
            "approved_at": _now(),
        },
    )


def _tdd_mark(row: KickoffAnalysis) -> str:
    t = row.inputs.get("tdd") or {}
    if not t.get("enabled") or not t.get("approved_by"):
        return ""
    source = t.get("source") or {}
    return (
        f"{t.get('mode', '')}|{source.get('page_id', '')}@{source.get('version', 0)}"
        f"|{','.join(sorted(t.get('selected', [])))}|{t.get('space_key', '')}/{t.get('title', '')}"
    )


# --- Step 8: the analysis ----------------------------------------------------------------------------------


def _ok(row: KickoffAnalysis, role: str) -> list[dict[str, Any]]:
    return [r for r in (row.inputs.get(role) or {}).get("items", []) if r.get("ok")]


def _ok_docs(row: KickoffAnalysis, role: str) -> list[dict[str, Any]]:
    """The material read at a step that carries documents beside its repos (step 3)."""
    return [d for d in (row.inputs.get(role) or {}).get("docs", []) if d.get("ok")]


def fingerprints(row: KickoffAnalysis) -> dict[str, str]:
    inputs = row.inputs
    c = inputs.get("compliance") or {}
    return {
        "prd": _prd_mark(inputs.get("prd")),
        "repos": ",".join(sorted(f"{r['full_name']}@{r.get('commit')}" for r in _ok(row, "repos"))),
        "dependencies": ",".join(
            sorted(f"{r['full_name']}@{r.get('commit')}" for r in _ok(row, "dependencies"))
            + sorted(f"{d['url']}@{d.get('version', '')}" for d in _ok_docs(row, "dependencies"))
        ),
        "compliance": ",".join(sorted(c.get("selected", []) + [x["name"] for x in c.get("custom", [])]))
        if c.get("approved_by")
        else "",
        "api_docs": ",".join(sorted(d["url"] for d in _ok(row, "api_docs"))),
        # Only what was read counts, as for the API docs: a failed re-read isn't a changed input.
        "third_parties": ",".join(
            sorted(
                f"{p['name']}|{p.get('docs_url', '')}"
                for p in (inputs.get("third_parties") or {}).get("items", [])
                if not p.get("docs_url") or (p.get("doc") or {}).get("ok")
            )
        ),
        "tdd": _tdd_mark(row),
    }


def run_blockers(row: KickoffAnalysis) -> list[str]:
    inputs = row.inputs
    blockers = []
    if not inputs.get("prd"):
        blockers.append("Fetch the PRD (step 1).")
    repos = (inputs.get("repos") or {}).get("items", [])
    if not any(r.get("ok") for r in repos):
        blockers.append("Add at least one repo to code in (step 2).")
    unread = [
        r["full_name"]
        for role in ("repos", "dependencies")
        for r in (inputs.get(role) or {}).get("items", [])
        if not r.get("ok")
    ]
    if unread:
        blockers.append(f"Fix or remove the repos that couldn't be read: {', '.join(unread)}.")
    if not (inputs.get("compliance") or {}).get("approved_by"):
        blockers.append("Approve the compliance selection (step 4), even if none applies.")
    return blockers


def context(row: KickoffAnalysis, instructions: str = "") -> ai.Context:
    prd = row.inputs["prd"]
    providers = []
    for p in (row.inputs.get("third_parties") or {}).get("items", []):
        providers.append({"name": p["name"], "docs_url": p.get("docs_url", ""), "doc": p.get("doc")})
    return ai.Context(
        title=row.title or prd["title"],
        prd_url=prd["url"],
        lines=prd["lines"],
        code_repos=_ok(row, "repos"),
        dependency_repos=_ok(row, "dependencies"),
        dependency_docs=_ok_docs(row, "dependencies"),
        compliance=_approved(row),
        api_docs=_ok(row, "api_docs"),
        providers=providers,
        instructions=instructions,
    )


def _record(
    session: AsyncSession, row: KickoffAnalysis, kind: str, actor: str, instructions: str
) -> None:
    """Keep the draft whole beside the live plan, so running again never costs anyone a draft."""
    session.add(
        KickoffRun(
            analysis_id=row.id,
            run_number=row.runs,
            kind=kind,
            provider=row.plan.get("reader", ""),
            model=row.plan.get("model", ""),
            reader=row.plan.get("reader", ""),
            note=row.plan.get("note", ""),
            instructions=instructions,
            plan=row.plan,
            tdd=row.tdd,
            inputs=row.plan.get("inputs", {}),
            created_by=actor,
        )
    )


def _drafted(row: KickoffAnalysis, plan: dict[str, Any], actor: str, instructions: str) -> None:
    row.runs = (row.runs or 0) + 1
    row.plan = {
        **plan,
        "run_by": actor,
        "run_at": _now(),
        "run_number": row.runs,
        "instructions": instructions,
        "edited_by": None,
        "edited_at": None,
        "inputs": fingerprints(row),
    }
    row.analysed_at = datetime.now(timezone.utc)
    row.status = "analysed"
    row.updated_by = actor


async def run(
    session: AsyncSession,
    row: KickoffAnalysis,
    actor: str,
    provider_key: str,
    model: str,
    instructions: str = "",
) -> None:
    blockers = run_blockers(row)
    if blockers:
        raise Refused("The analysis can't run yet.", blockers)
    chosen = await model_provider.choose(provider_key, model)
    if isinstance(chosen, str):
        raise Refused(chosen)
    provider, model = chosen
    plan, reader, used, note = await ai.draft_plan(context(row, instructions), provider.key, model)
    _drafted(row, {**plan, "reader": reader, "model": used, "note": note}, actor, instructions)
    await run_tdd(session, row, actor, provider.key, model, instructions)
    _record(session, row, "run", actor, instructions)


# --- The design the run produces ------------------------------------------------------------------


def _tdd_wanted(row: KickoffAnalysis) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The TDD step as confirmed, and the sections a model is asked to write (not the built one)."""
    t = row.inputs.get("tdd") or {}
    chosen = set(t.get("selected", []))
    wanted = [s for s in t.get("sections", []) if s["key"] in chosen and s["key"] != "traceability"]
    return t, wanted


async def run_tdd(
    session: AsyncSession,
    row: KickoffAnalysis,
    actor: str,
    provider_key: str,
    model: str,
    instructions: str,
) -> None:
    """Draft the design and write it, when step 7 asked for one and a person confirmed the sections.

    A design that can't be drafted or can't be written never fails the run: the plan is what the
    backlog is made from. The failure is recorded on the page with a way to try the write again.
    """
    t, wanted = _tdd_wanted(row)
    if not t.get("enabled") or not t.get("approved_by"):
        row.tdd = None
        return
    names = {c["key"]: c["name"] for c in _approved(row)}
    try:
        existing = await _tdd_existing(session, row) if t.get("mode") == "existing" else {}
        draft = await ai.draft_tdd(
            context(row, instructions or t.get("prompt", "")),
            row.plan,
            wanted,
            existing,
            provider_key,
            model,
        )
        parts, notes = tdd.sanitize(draft.sections, t["selected"], names)
    except ai.ModelFailed as exc:
        row.tdd = {
            "sections": [],
            "notes": [],
            "drafted": False,
            "note": f"The design wasn't drafted: {exc}. The plan below is unaffected.",
            "run_number": row.runs,
            "published": None,
        }
        return
    if "traceability" in t["selected"]:
        built = tdd.traceability(row.plan, names, row.backlog)
        at = t["selected"].index("traceability")
        parts.insert(min(at, len(parts)), built)
    row.tdd = {
        "sections": parts,
        "notes": notes,
        "drafted": True,
        "note": "",
        "run_number": row.runs,
        "published": None,
    }
    await publish_tdd(session, row, actor)


async def _tdd_existing(session: AsyncSession, row: KickoffAnalysis) -> dict[str, str]:
    """What each ticked section says now, so the draft updates it rather than reinventing it."""
    t = row.inputs["tdd"]
    storage = await _tdd_storage(session, t["source"]["page_id"])
    chosen = set(t.get("selected", []))
    return {h.key: tdd.text_of_section(storage, h) for h in tdd.headings(storage) if h.key in chosen}


async def publish_tdd(session: AsyncSession, row: KickoffAnalysis, actor: str) -> None:
    """Write the drafted design to Confluence. Never raises: a failed write is recorded, not fatal."""
    if not row.tdd or not row.tdd.get("sections"):
        return
    t = row.inputs["tdd"]
    source = t.get("source") or {}
    access = await sources.atlassian(session, ("confluence", "jira"))
    if access is None:
        row.tdd = {**row.tdd, "note": tdd.NO_CREDENTIAL}
        return
    published = row.tdd.get("published") or {}
    prd_title = (row.inputs.get("prd") or {}).get("title", "")
    try:
        result = await tdd.publish(
            access,
            mode=t.get("mode", "sample"),
            parts=row.tdd["sections"],
            # An existing design is written back to itself. A sample writes the page it made last
            # time - kept on the step, not on the draft, so running again updates one page rather
            # than leaving a trail of near-identical ones.
            page_id=source["page_id"] if t.get("mode") == "existing" else t.get("page_id", ""),
            space_key=t.get("space_key", ""),
            title=t.get("title") or f"{prd_title} — TDD",
            parent_id=await _parent_id(session, t.get("parent_url", "")),
            label=backlog.label_for(row.id),
            actor=actor,
        )
    # Deliberately broad: every failure here is reported on the page, never raised past the run.
    except Exception as exc:
        row.tdd = {**row.tdd, "note": tdd.failure(exc), "published": published or None}
        return
    row.tdd = {**row.tdd, "note": "", "published": result}
    if t.get("mode") != "existing" and result["page_id"] != t.get("page_id"):
        _touch(row, actor, tdd={**t, "page_id": result["page_id"]})


async def _parent_id(session: AsyncSession, url: str) -> str:
    if not url.strip():
        return ""
    try:
        _host, page_id, _tiny = sources.page_ref(url)
    except sources.NotReadable:
        return ""
    return page_id


async def refine(
    session: AsyncSession, row: KickoffAnalysis, actor: str, provider_key: str, model: str, instructions: str
) -> None:
    """Amend the plan that is already there rather than drafting over it.

    This is the cheap iteration: a requirement moves a little, so the plan moves a little. Tasks the
    model leaves alone keep their wording, their refs and whoever edited them - which is what makes
    it safe to do repeatedly while people are still reading the draft.
    """
    if not row.plan or not row.plan.get("tasks"):
        raise Refused("There is no plan to refine yet. Run the analysis first.")
    if not instructions.strip():
        raise Refused("Say what should change: a refine needs something to act on.")
    chosen = await model_provider.choose(provider_key, model)
    if isinstance(chosen, str):
        raise Refused(chosen)
    provider, model = chosen
    try:
        plan, reader, used, note = await ai.refine_plan(
            context(row, instructions), row.plan, provider.key, model
        )
    except ai.ModelFailed as exc:
        # The plan is left exactly as it was: a failed refine must never cost anyone their draft.
        raise Refused(f"The plan wasn't changed: {exc}.") from exc
    _drafted(row, {**plan, "reader": reader, "model": used, "note": note}, actor, instructions)
    _record(session, row, "refine", actor, instructions)


def edit_plan(row: KickoffAnalysis, actor: str, body: out.PlanEdit) -> None:
    """A person editing the drafted tasks: reorder, rewrite, remove, add. Recorded as theirs."""
    if not row.plan:
        raise Refused("Run the analysis first: there are no tasks to edit yet.")
    before = {t["ref"]: t for t in row.plan["tasks"]}
    keys = {c["key"] for c in _approved(row)}
    repos = {r["full_name"] for r in _ok(row, "repos")}
    numbers = [int(r[1:]) for r in before if r[1:].isdigit()]
    next_number = max(numbers, default=0) + 1
    tasks: list[dict[str, Any]] = []
    problems: list[str] = []
    placed: set[str] = set()
    for item in body.tasks:
        ref = item.ref if item.ref in before and item.ref not in placed else ""
        if not ref:
            ref = f"T{next_number}"
            next_number += 1
        late = [d for d in item.depends_on if d not in placed]
        if late:
            problems.append(
                f"“{item.title}” depends on {', '.join(late)}, which isn't above it. "
                "Move it down, or remove the dependency."
            )
        if item.repo and item.repo not in repos:
            problems.append(f"“{item.title}” names {item.repo}, which isn't a repo to code in.")
        old = before.get(ref)
        fields = {
            "title": item.title.strip(),
            "type": item.type,
            "repo": item.repo,
            "description": item.description.strip(),
            "acceptance_criteria": [a.strip() for a in item.acceptance_criteria if a.strip()],
            "depends_on": list(dict.fromkeys(item.depends_on)),
            "estimate": item.estimate,
            "compliance": [k for k in dict.fromkeys(item.compliance) if k in keys],
        }
        if old is None:
            tasks.append({"ref": ref, **fields, "quotes": [], "origin": "person", "edited_by": actor})
        else:
            changed = any(old.get(k) != v for k, v in fields.items())
            tasks.append({**old, **fields, "edited_by": actor if changed else old.get("edited_by")})
        placed.add(ref)
    if problems:
        raise Refused("The tasks weren't saved.", problems)
    row.plan = {
        **row.plan,
        "epic_title": body.epic_title.strip(),
        "tasks": tasks,
        "edited_by": actor,
        "edited_at": _now(),
    }
    row.updated_by = actor


# --- Run history and what changed between two runs ---------------------------------------------


async def runs(session: AsyncSession, row: KickoffAnalysis) -> list[KickoffRun]:
    result = await session.execute(
        select(KickoffRun)
        .where(KickoffRun.analysis_id == row.id)
        .order_by(KickoffRun.run_number.desc(), KickoffRun.id.desc())
    )
    return list(result.scalars().all())


async def one_run(session: AsyncSession, row: KickoffAnalysis, number: int) -> KickoffRun | None:
    return next((r for r in await runs(session, row) if r.run_number == number), None)


def _task_key(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


# Not "title": tasks are matched by it, so it is equal wherever a pair was found.
COMPARED = ("type", "repo", "description", "acceptance_criteria", "estimate", "compliance", "depends_on")


def diff(before: dict[str, Any], after: dict[str, Any]) -> out.RunDiffOut:
    """What changed between two drafts, task by task.

    Tasks are matched on their title alone. A fresh run renumbers every ref, so matching on refs
    would report a task that merely moved as one whose title changed - a continuity that isn't
    there. A task whose title changed is reported as one gone and one arrived, which is all that
    can honestly be said about it.
    """
    old_tasks = before.get("tasks", [])
    new_tasks = after.get("tasks", [])
    by_title: dict[str, list[dict[str, Any]]] = {}
    for task in old_tasks:
        by_title.setdefault(_task_key(task["title"]), []).append(task)
    matched: set[int] = set()
    added: list[out.RunTaskOut] = []
    changed: list[out.RunChangeOut] = []
    for task in new_tasks:
        # Same title twice in one plan: pair them up in order rather than against each other.
        candidates = [t for t in by_title.get(_task_key(task["title"]), []) if id(t) not in matched]
        if not candidates:
            added.append(out.RunTaskOut(ref=task["ref"], title=task["title"], repo=task.get("repo", "")))
            continue
        old = candidates[0]
        matched.add(id(old))
        for key in COMPARED:
            if old.get(key) != task.get(key):
                changed.append(
                    out.RunChangeOut(
                        ref=task["ref"],
                        title=task["title"],
                        field=key,
                        before=_readable(old.get(key)),
                        after=_readable(task.get(key)),
                    )
                )
    removed = [
        out.RunTaskOut(ref=t["ref"], title=t["title"], repo=t.get("repo", ""))
        for t in old_tasks
        if id(t) not in matched
    ]
    return out.RunDiffOut(
        added=added,
        removed=removed,
        changed=changed,
        epic_title_changed=before.get("epic_title") != after.get("epic_title"),
        summary_changed=before.get("summary") != after.get("summary"),
    )


def _readable(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value) or "—"
    return str(value or "—")


def stale(row: KickoffAnalysis) -> list[str]:
    if not row.plan:
        return []
    then = row.plan.get("inputs") or {}
    current = fingerprints(row)
    return [STALE_LABELS[k] for k in STALE_LABELS if then.get(k) != current.get(k)]


async def backlog_fields(session: AsyncSession, backlog_url: str) -> out.BacklogFieldsOut:
    """What the target project offers for each ticket option, so nothing is typed blind."""
    try:
        ref = backlog.backlog_ref(backlog_url)
    except sources.NotReadable as exc:
        raise Refused(str(exc)) from exc
    jira = await sources.atlassian(session, ("jira", "confluence"))
    if jira is None:
        raise Refused("Jira isn't connected. Add the Jira connector in Settings → Connectors.")
    if ref["host"] and ref["host"] != jira.host:
        raise Refused(f"That backlog is on {ref['host']}, but Feature Kickoff is connected to {jira.host}.")
    offered = await backlog.offered(jira.client, ref["project_key"])
    return out.BacklogFieldsOut(project_key=ref["project_key"], **offered)


def set_backlog_options(row: KickoffAnalysis, actor: str, body: out.JiraDefaults) -> None:
    """What every ticket this analysis creates should carry. Applied at create time, and checked
    against the project again then: a page can be minutes old by the time it is used."""
    _touch(row, actor, backlog_options=body.model_dump())


async def create_backlog(session: AsyncSession, row: KickoffAnalysis, actor: str, backlog_url: str) -> dict:
    if not row.plan or not row.plan.get("tasks"):
        raise Refused("There are no tasks to create. Run the analysis first.")
    changed = stale(row)
    if changed:
        raise Refused(
            "The plan is older than its inputs: run the analysis again before creating it.",
            [f"Changed since it ran: {', '.join(changed)}."],
        )
    try:
        ref = backlog.backlog_ref(backlog_url)
    except sources.NotReadable as exc:
        raise Refused(str(exc)) from exc
    jira = await sources.atlassian(session, ("jira", "confluence"))
    if jira is None:
        raise Refused(
            "Jira isn't connected. Add the Jira connector in Settings → Connectors, then create again."
        )
    if ref["host"] and ref["host"] != jira.host:
        raise Refused(f"That backlog is on {ref['host']}, but Feature Kickoff is connected to {jira.host}.")
    prd = row.inputs["prd"]
    result = await backlog.create(
        jira.client,
        analysis_id=row.id,
        plan=row.plan,
        ref=ref,
        actor=actor,
        drafted_by=_drafted_by(row.plan),
        prd=prd,
        compliance_names={c["key"]: c["name"] for c in _approved(row)},
        repo_urls={r["full_name"]: r["html_url"] for r in _ok(row, "repos")},
        previous=row.backlog,
        options=row.inputs.get("backlog_options") or {},
    )
    row.backlog = result
    _touch(
        row,
        actor,
        backlog_target={"url": ref["url"], "project_key": ref["project_key"], "board_id": ref["board_id"]},
    )
    row.status = "partial" if result["failed"] else "created"
    await _refresh_traceability(session, row, actor)
    return result


async def _refresh_traceability(session: AsyncSession, row: KickoffAnalysis, actor: str) -> None:
    """Put the Jira keys into the design's traceability matrix, now that there are some.

    Same guarded write as any other: only that section is touched, and a failure is a note on the
    page rather than something that undoes a backlog that was created successfully.
    """
    if not row.tdd or not row.tdd.get("sections"):
        return
    at = next((i for i, s in enumerate(row.tdd["sections"]) if s.get("key") == "traceability"), None)
    if at is None:
        return
    names = {c["key"]: c["name"] for c in _approved(row)}
    sections = list(row.tdd["sections"])
    sections[at] = tdd.traceability(row.plan, names, row.backlog)
    row.tdd = {**row.tdd, "sections": sections}
    await publish_tdd(session, row, actor)


# --- The view -----------------------------------------------------------------------------------


def _drafted_by(plan: dict[str, Any]) -> str:
    if plan.get("reader") == "claude":
        return f"Claude ({plan['model']})"
    if plan.get("reader") == "cursor":
        return f"{plan['model']} through Cursor"
    return "the rule-based drafter (no AI)"


def _material_count(group: dict[str, Any]) -> str:
    def count(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    parts = []
    if repos := len(group.get("items", [])):
        parts.append(count(repos, "repo"))
    if docs := len(group.get("docs", [])):
        parts.append(count(docs, "document"))
    return " · ".join(parts)


def _steps(row: KickoffAnalysis) -> list[out.StepOut]:
    inputs = row.inputs
    prd = inputs.get("prd")
    repos = [r for r in (inputs.get("repos") or {}).get("items", []) if r.get("ok")]
    deps = inputs.get("dependencies") or {}
    comp = inputs.get("compliance") or {}
    docs = inputs.get("api_docs") or {}
    parties = inputs.get("third_parties") or {}
    plan = row.plan

    def count(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    approved = len(comp.get("selected", [])) + len(comp.get("custom", []))
    summaries = {
        "prd": (bool(prd), f"{prd['title']} · v{prd['version']}" if prd else "Paste a Confluence page link"),
        "repos": (bool(repos), count(len(repos), "repo") if repos else "At least one repo"),
        "dependencies": (
            bool(deps.get("saved")),
            (_material_count(deps) if deps.get("items") or deps.get("docs") else "None")
            if deps.get("saved")
            else "Optional",
        ),
        "compliance": (
            bool(comp.get("approved_by")),
            (f"{approved} approved" if approved else "None apply")
            if comp.get("approved_by")
            else "Awaiting approval",
        ),
        "api_docs": (
            bool(docs.get("saved")),
            (count(len(docs.get("items", [])), "doc") if docs.get("items") else "None")
            if docs.get("saved")
            else "Optional",
        ),
        "third_parties": (
            bool(parties.get("saved")),
            (count(len(parties.get("items", [])), "provider") if parties.get("items") else "None")
            if parties.get("saved")
            else "Optional",
        ),
        "tdd": _tdd_summary(inputs.get("tdd") or {}),
        "plan": (bool(plan), count(len(plan["tasks"]), "task") if plan else "Not run yet"),
    }
    return [
        out.StepOut(key=k, label=label, done=summaries[k][0], summary=summaries[k][1]) for k, label in STEPS
    ]


def _tdd_summary(t: dict[str, Any]) -> tuple[bool, str]:
    if not t.get("approved_by"):
        return False, "Optional"
    if not t.get("enabled"):
        return True, "None"
    n = len(t.get("selected", []))
    where = "a new page" if t.get("mode") == "sample" else (t.get("source") or {}).get("title", "the design")
    return True, f"{n} section{'' if n == 1 else 's'} → {where}"


def _tdd_out(row: KickoffAnalysis) -> out.TddOut:
    t = row.inputs.get("tdd") or {}
    return out.TddOut(
        enabled=bool(t.get("enabled")),
        mode=t.get("mode") or "sample",
        source=out.TddSourceOut(**t["source"]) if t.get("source") else None,
        sections=[out.TddSectionChoice(**s) for s in t.get("sections", [])],
        selected=t.get("selected", []),
        space_key=t.get("space_key", ""),
        parent_url=t.get("parent_url", ""),
        title=t.get("title", ""),
        approved_by=t.get("approved_by"),
        approved_at=t.get("approved_at"),
    )


def _tdd_document(row: KickoffAnalysis) -> out.TddDocumentOut | None:
    if not row.tdd:
        return None
    return out.TddDocumentOut(
        sections=[out.TddSectionOut(**{k: v for k, v in s.items() if k in out.TddSectionOut.model_fields})
                  for s in row.tdd.get("sections", [])],
        notes=row.tdd.get("notes", []),
        drafted=bool(row.tdd.get("drafted")),
        note=row.tdd.get("note", ""),
        run_number=row.tdd.get("run_number", 0),
        published=out.TddPublishedOut(**row.tdd["published"]) if row.tdd.get("published") else None,
    )


def _repo_out(r: dict[str, Any]) -> out.RepoOut:
    if not r.get("ok"):
        return out.RepoOut(
            url=r["url"],
            full_name=r.get("full_name") or r["url"],
            ok=False,
            error=r.get("error", ""),
            read_at=r.get("read_at"),
        )
    return out.RepoOut(
        **{
            k: r[k]
            for k in (
                "url",
                "html_url",
                "full_name",
                "description",
                "default_branch",
                "ref",
                "commit",
                "commit_url",
                "language",
                "topics",
                "visibility",
                "archived",
                "file_count",
                "tree_truncated",
                "top_level",
                "manifests",
                "read_with",
                "read_at",
            )
            if k in r
        },
        ok=True,
        languages=[out.LanguageShare(**lang) for lang in r.get("languages", [])],
        readme_excerpt=" ".join(r.get("readme", "").split())[:600],
        specs=[
            out.SpecOut(
                **{k: s[k] for k in ("path", "url", "ok", "error", "title", "version", "deprecated")},
                operation_count=len(s.get("operations", [])),
                operations=s.get("operations", [])[:60],
            )
            for s in r.get("specs", [])
        ],
    )


def _doc_out(d: dict[str, Any]) -> out.DocOut:
    return out.DocOut(
        **{
            k: d.get(k)
            for k in ("url", "final_url", "ok", "error", "kind", "title", "version", "summary", "read_at")
            if d.get(k) is not None
        },
        operation_count=len(d.get("operations", [])),
        operations=d.get("operations", [])[:60],
    )


def _repo_group(row: KickoffAnalysis, role: str) -> out.RepoGroupOut:
    group = row.inputs.get(role) or {}
    return out.RepoGroupOut(
        repos=[_repo_out(r) for r in group.get("items", [])],
        saved=bool(group.get("saved")),
        saved_by=group.get("saved_by"),
    )


def _material_group(row: KickoffAnalysis, role: str) -> out.MaterialGroupOut:
    """Step 3: the repos we rely on, and the documents we rely on, read the same way."""
    group = row.inputs.get(role) or {}
    return out.MaterialGroupOut(
        repos=[_repo_out(r) for r in group.get("items", [])],
        docs=[_doc_out(d) for d in group.get("docs", [])],
        saved=bool(group.get("saved")),
        saved_by=group.get("saved_by"),
    )


def view(row: KickoffAnalysis) -> out.AnalysisOut:
    inputs = row.inputs
    prd = inputs.get("prd")
    comp = inputs.get("compliance") or {}
    docs = inputs.get("api_docs") or {}
    parties = inputs.get("third_parties") or {}
    mentioned = compliance.mentioned_providers(prd["lines"]) if prd else {}
    plan = row.plan
    return out.AnalysisOut(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        status=row.status,
        created_by=row.created_by,
        created_at=as_utc(row.created_at),
        updated_by=row.updated_by,
        updated_at=as_utc(row.updated_at),
        steps=_steps(row),
        run_blockers=run_blockers(row),
        prd=out.PrdOut(**{k: prd[k] for k in out.PrdOut.model_fields}) if prd else None,
        repos=_repo_group(row, "repos"),
        dependencies=_material_group(row, "dependencies"),
        compliance=out.ComplianceOut(
            suggestions=[out.SuggestionOut(**s) for s in comp.get("suggestions", [])],
            suggested_by=comp.get("suggested_by"),
            suggested_note=comp.get("suggested_note", ""),
            suggested_at=comp.get("suggested_at"),
            suggestions_stale=bool(comp.get("suggested_for")) and comp.get("suggested_for") != _prd_mark(prd),
            selected=comp.get("selected", []),
            custom=[out.CustomCompliance(**c) for c in comp.get("custom", [])],
            approved_by=comp.get("approved_by"),
            approved_at=comp.get("approved_at"),
        ),
        api_docs=out.DocGroupOut(
            docs=[_doc_out(d) for d in docs.get("items", [])],
            saved=bool(docs.get("saved")),
            saved_by=docs.get("saved_by"),
        ),
        third_parties=out.ProvidersOut(
            providers=[
                out.ProviderOut(
                    key=p.get("key", ""),
                    name=p["name"],
                    docs_url=p.get("docs_url", ""),
                    doc=_doc_out(p["doc"]) if p.get("doc") else None,
                    mentioned=mentioned.get(p.get("key", ""), []),
                )
                for p in parties.get("items", [])
            ],
            mentioned={k: [out.Quote(**q) for q in v] for k, v in mentioned.items()},
            saved=bool(parties.get("saved")),
            saved_by=parties.get("saved_by"),
        ),
        tdd=_tdd_out(row),
        tdd_document=_tdd_document(row),
        plan=_plan_out(row, plan, stale(row)) if plan else None,
        instructions=inputs.get("instructions", ""),
        backlog_options=out.JiraDefaults(**(inputs.get("backlog_options") or {})),
        backlog_target=out.BacklogTargetOut(**inputs["backlog_target"])
        if inputs.get("backlog_target")
        else None,
        backlog=out.BacklogOut(**row.backlog) if row.backlog else None,
    )


def _plan_out(row: KickoffAnalysis, plan: dict[str, Any], stale_labels: list[str]) -> out.PlanOut:
    return out.PlanOut(
        **{k: v for k, v in plan.items() if k in out.PlanOut.model_fields and k != "stale"},
        drafted_by=_drafted_by(plan),
        stale=stale_labels,
    )


def run_summary(record: KickoffRun, current: int) -> out.RunSummaryOut:
    return out.RunSummaryOut(
        run_number=record.run_number,
        kind=record.kind,
        reader=record.reader,
        model=record.model,
        instructions=record.instructions,
        task_count=len((record.plan or {}).get("tasks", [])),
        created_by=record.created_by,
        created_at=as_utc(record.created_at),
        is_current=record.run_number == current,
    )


def run_detail(row: KickoffAnalysis, record: KickoffRun, previous: KickoffRun | None) -> out.RunDetailOut:
    return out.RunDetailOut(
        run_number=record.run_number,
        kind=record.kind,
        instructions=record.instructions,
        created_by=record.created_by,
        created_at=as_utc(record.created_at),
        # An earlier run is shown as it was drafted; staleness is only ever about the live plan.
        plan=_plan_out(row, record.plan, []),
        diff=diff(previous.plan, record.plan) if previous else None,
    )


def summary(row: KickoffAnalysis) -> out.AnalysisSummary:
    steps = _steps(row)
    return out.AnalysisSummary(
        id=row.id,
        title=row.title,
        status=row.status,
        created_by=row.created_by,
        created_at=as_utc(row.created_at),
        updated_by=row.updated_by,
        updated_at=as_utc(row.updated_at),
        steps_done=sum(1 for s in steps if s.done),
        steps_total=len(steps),
        repo_count=len(_ok(row, "repos")),
        task_count=len(row.plan["tasks"]) if row.plan else 0,
        drafted_by=_drafted_by(row.plan) if row.plan else None,
        backlog_key=(row.backlog or {}).get("project_key"),
        stale=bool(stale(row)),
    )
