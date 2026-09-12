"""The technical design an analysis can produce, and where it is written.

A design is drafted from the same inputs as the plan - the PRD, the code we have, what we rely on,
the approved compliance - plus the plan itself, so the document and the backlog say the same thing.

Two ways in, and the difference matters because one of them writes to a page a team already owns:

* **From a sample**: a template page shows the house style, and a new page is written from it.
* **Into an existing TDD**: only the sections a person ticked are replaced. Every other byte of the
  page is preserved exactly as it was, the write is refused if anyone saved in the meantime, and
  the version message names the analysis and the sections, so it is traceable and revertible.

Nothing is written for a section nobody ticked, and the ticking happens before the run - that
confirmation is the acceptance product rule 6 asks for.
"""

import contextlib
import html
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.connectors.atlassian_rest import AtlassianError
from app.services import kickoff_sources as sources

DATA = Path(__file__).resolve().parents[1] / "seed" / "data" / "tdd_sections.json"


@lru_cache(maxsize=1)
def _catalogue() -> list[dict[str, Any]]:
    return json.loads(DATA.read_text())["sections"]


def sections() -> list[dict[str, Any]]:
    """The sections a technical design is expected to carry."""
    return _catalogue()


def section(key: str) -> dict[str, Any] | None:
    return next((s for s in _catalogue() if s["key"] == key), None)


def default_keys() -> list[str]:
    return [s["key"] for s in _catalogue() if s["default"]]


def _normalise(text: str) -> str:
    """A heading as it compares: lowercase words only, with any numbering dropped."""
    stripped = re.sub(r"^[\d.\s)]+", "", text.strip())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", stripped.lower()).split())


@lru_cache(maxsize=1)
def _by_alias() -> dict[str, str]:
    index: dict[str, str] = {}
    for entry in _catalogue():
        for name in [entry["name"], entry["key"], *entry.get("aliases", [])]:
            index.setdefault(_normalise(name), entry["key"])
    return index


def match(heading: str) -> str:
    """The catalogue key a page's heading is, or a key of its own when it is something else.

    A team's TDD is not the catalogue, so a heading we don't recognise is still a section they can
    tick - it just isn't one we can say anything about in advance.
    """
    normalised = _normalise(heading)
    if not normalised:
        return ""
    if found := _by_alias().get(normalised):
        return found
    # A heading that contains a known one ("4. Low-level design (payments)") counts as it.
    for alias, key in _by_alias().items():
        if len(alias) > 6 and alias in normalised:
            return key
    return "other-" + re.sub(r"[^a-z0-9]+", "-", normalised).strip("-")[:40]


# --- Reading a page's sections ------------------------------------------------------------------

HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
TAGS = re.compile(r"<[^>]+>")


def _text_of(markup: str) -> str:
    return " ".join(html.unescape(TAGS.sub(" ", markup)).split())


@dataclass
class Heading:
    """One heading in a page's storage, and where its section's body lies."""

    level: int
    title: str
    key: str
    # Byte offsets into the storage: the heading itself, then the body that follows it.
    start: int
    body_start: int
    body_end: int


def headings(storage: str) -> list[Heading]:
    """Every heading in a page, each with the span of the body it owns.

    A section's body runs to the next heading at the same level or higher. That is what makes it
    possible to replace one section and leave the rest of the page byte for byte as it was.
    """
    found = [
        Heading(
            level=int(m.group(1)),
            title=_text_of(m.group(2)),
            key=match(_text_of(m.group(2))),
            start=m.start(),
            body_start=m.end(),
            body_end=len(storage),
        )
        for m in HEADING.finditer(storage)
    ]
    for i, h in enumerate(found):
        following = next((n for n in found[i + 1 :] if n.level <= h.level), None)
        h.body_end = following.start if following else len(storage)
    return found


def page_sections(storage: str, mode: str) -> list[dict[str, Any]]:
    """The sections to offer for ticking, for a page read as a sample or as the TDD itself.

    A page's own headings come first, in the order they appear, then the standard sections it
    doesn't have. `present` is the difference that matters, and the page says which is which: a
    section the page has is replaced where it sits, one it lacks is added at the end. Both are
    deliberate - a design missing a traceability matrix should be able to gain one - and neither
    happens unless someone ticks it.
    """
    offered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in headings(storage):
        # Only the outline levels are offered: a design is not ticked paragraph by paragraph.
        if h.level > 3 or h.key in seen:
            continue
        seen.add(h.key)
        entry = section(h.key)
        offered.append(
            {
                "key": h.key,
                "name": h.title or (entry or {}).get("name", h.key),
                "summary": (entry or {}).get("summary", ""),
                "level": h.level,
                "present": True,
                "chars": len(_text_of(storage[h.body_start : h.body_end])),
                "recommended": bool((entry or {}).get("default")),
            }
        )
    for entry in _catalogue():
        if entry["key"] not in seen:
            offered.append(
                {
                    "key": entry["key"],
                    "name": entry["name"],
                    "summary": entry["summary"],
                    "level": 2,
                    "present": False,
                    "chars": 0,
                    # A sample is a shape to follow, so its usual sections start ticked. An existing
                    # design is a page someone owns: adding to it is opt-in, every time.
                    "recommended": entry["default"] and mode == "sample",
                }
            )
    return offered


# --- Writing storage ------------------------------------------------------------------------------

# Diagrams go in as their source inside a code macro. A picture would need a marketplace app; the
# source renders everywhere, stays diffable, and turns into a picture for teams that have the app.
DIAGRAM_KINDS = ("sequence", "erd", "component", "flow", "state")
DIAGRAM_LANGUAGE = {"mermaid": "text", "plantuml": "text"}
MAX_BODY_CHARS = 20000
MAX_DIAGRAMS = 6
TABLE_ROW = re.compile(r"^\|(.+)\|$")
FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)\s*$")


def esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def code_macro(body: str, language: str = "text", title: str = "") -> str:
    """A code block. Model text goes in as CDATA, never as markup we then have to trust."""
    safe = body.replace("]]>", "]] >")
    params = f'<ac:parameter ac:name="language">{esc(language)}</ac:parameter>'
    if title:
        params += f'<ac:parameter ac:name="title">{esc(title)}</ac:parameter>'
    return (
        '<ac:structured-macro ac:name="code">'
        f"{params}<ac:plain-text-body><![CDATA[{safe}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def table(header: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th><p>{esc(c)}</p></th>" for c in header)
    body = "".join(
        "<tr>" + "".join(f"<td><p>{esc(c)}</p></td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><tbody><tr>{head}</tr>{body}</tbody></table>"


def storage_of(markdown: str) -> str:
    """A restricted Markdown subset as Confluence storage.

    Only the blocks a design needs - headings, paragraphs, lists, tables, code - and every piece of
    text escaped on the way through. Nothing a model writes is ever passed to Confluence as markup.
    """
    out: list[str] = []
    bullets: list[str] = []
    numbers: list[str] = []
    rows: list[list[str]] = []
    fence: list[str] | None = None
    language = "text"

    def flush() -> None:
        nonlocal rows
        if bullets:
            out.append("<ul>" + "".join(f"<li><p>{esc(b)}</p></li>" for b in bullets) + "</ul>")
            bullets.clear()
        if numbers:
            out.append("<ol>" + "".join(f"<li><p>{esc(n)}</p></li>" for n in numbers) + "</ol>")
            numbers.clear()
        if rows:
            # A markdown separator row (---|---) is layout, not data.
            kept = [r for r in rows if not all(set(c) <= {"-", ":", " "} for c in r)]
            if kept:
                out.append(table(kept[0], kept[1:]))
            rows = []

    for raw in (markdown or "")[:MAX_BODY_CHARS].splitlines():
        line = raw.rstrip()
        if fence is not None:
            if FENCE.match(line.strip()):
                out.append(code_macro("\n".join(fence), language))
                fence = None
            else:
                fence.append(raw)
            continue
        if found := FENCE.match(line.strip()):
            flush()
            language = found.group(1) or "text"
            fence = []
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if found := TABLE_ROW.match(stripped):
            rows.append([c.strip() for c in found.group(1).split("|")])
            continue
        if heading := re.match(r"^(#{1,6})\s+(.*)", stripped):
            flush()
            # Nested one level under the section's own heading, which the caller writes.
            depth = min(6, len(heading.group(1)) + 2)
            out.append(f"<h{depth}>{esc(heading.group(2))}</h{depth}>")
            continue
        if bullet := re.match(r"^[-*+]\s+(.*)", stripped):
            if rows:
                flush()
            bullets.append(bullet.group(1))
            continue
        if numbered := re.match(r"^\d+[.)]\s+(.*)", stripped):
            if rows:
                flush()
            numbers.append(numbered.group(1))
            continue
        flush()
        out.append(f"<p>{esc(stripped)}</p>")
    if fence is not None:
        out.append(code_macro("\n".join(fence), language))
    flush()
    return "".join(out)


def section_storage(part: dict[str, Any], level: int = 2) -> str:
    """One section: its heading, its body, and its diagrams as source."""
    body = [f"<h{level}>{esc(part['name'])}</h{level}>", storage_of(part.get("body_markdown", ""))]
    for diagram in part.get("diagrams", [])[:MAX_DIAGRAMS]:
        body.append(code_macro(diagram.get("source", ""), "text", diagram.get("title", "")))
    return "".join(body)


def splice(storage: str, parts: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    """Replace the given sections in a page and leave every other byte of it exactly as it was.

    Returns the new storage, the sections replaced, and the sections appended because the page did
    not have them. Sections nobody asked for are never touched - that is the whole point of writing
    into a page a team already owns.
    """
    found = {h.key: h for h in headings(storage) if h.level <= 3}
    replaced: list[str] = []
    appended: list[str] = []
    # Applied back to front, so each edit's offsets are still the ones that were measured.
    edits: list[tuple[int, int, str]] = []
    tail: list[str] = []
    for part in parts:
        here = found.get(part["key"])
        if here is None:
            appended.append(part["key"])
            tail.append(section_storage(part))
            continue
        replaced.append(part["key"])
        edits.append((here.start, here.body_end, section_storage(part, here.level)))
    result = storage
    for start, end, markup in sorted(edits, reverse=True):
        result = result[:start] + markup + result[end:]
    return result + "".join(tail), replaced, appended


# --- The traceability matrix ----------------------------------------------------------------------

TRACEABILITY = ("Task", "Type", "Repo", "From the PRD", "Compliance", "Depends on", "Jira")


def traceability(plan: dict[str, Any], names: dict[str, str], backlog: dict[str, Any] | None) -> dict:
    """Built from the analysis, never drafted.

    Every other section is a model's words about the design. This one is the join the evidence
    already supports - task to PRD line to compliance to repo to ticket - so it is assembled from
    the data. A drafted traceability matrix would be a claim dressed up as a record.
    """
    keys = {t["ref"]: t for t in (backlog or {}).get("tickets", [])}
    rows = []
    for task in plan.get("tasks", []):
        ticket = keys.get(task["ref"]) or {}
        rows.append(
            [
                f"{task['ref']} · {task['title']}",
                task.get("type", ""),
                task.get("repo", "") or "—",
                ", ".join(f"L{q['line']}" for q in task.get("quotes", [])) or "—",
                ", ".join(names.get(k, k) for k in task.get("compliance", [])) or "—",
                ", ".join(task.get("depends_on", [])) or "—",
                ticket.get("key") or "—",
            ]
        )
    note = (
        "One row per task in this analysis. PRD lines are the numbered lines of the page it was "
        "read from; Jira keys appear once the backlog has been created."
    )
    return {
        "key": "traceability",
        "name": section("traceability")["name"],
        "body_markdown": "",
        "diagrams": [],
        "built": True,
        "note": note,
        "header": list(TRACEABILITY),
        "rows": rows,
    }


def _built_storage(part: dict[str, Any], level: int = 2) -> str:
    return (
        f"<h{level}>{esc(part['name'])}</h{level}>"
        f"<p>{esc(part['note'])}</p>"
        + table(part["header"], part["rows"])
    )


# --- What the model drafted, held to what was asked for -------------------------------------------


def sanitize(parts: list[Any], selected: list[str], names: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Keep only the sections that were ticked, in the order they were confirmed.

    A section nobody ticked is never written, however good it looks: the ticking is the acceptance.
    """
    notes: list[str] = []
    by_key: dict[str, dict[str, Any]] = {}
    for part in parts:
        key = getattr(part, "key", "") or ""
        if key not in selected:
            title = getattr(part, "title", "") or key
            notes.append(f"It also drafted “{title}”, which wasn't ticked; that's dropped.")
            continue
        if key in by_key:
            continue
        entry = section(key)
        by_key[key] = {
            "key": key,
            "name": (entry or {}).get("name") or getattr(part, "title", key),
            "body_markdown": (getattr(part, "body_markdown", "") or "")[:MAX_BODY_CHARS],
            "diagrams": [
                {
                    "kind": d.kind,
                    "title": (d.title or "")[:120],
                    "source": (d.source or "")[:8000],
                }
                for d in getattr(part, "diagrams", [])[:MAX_DIAGRAMS]
                if d.kind in DIAGRAM_KINDS and (d.source or "").strip()
            ],
            "built": False,
        }
    missing = [k for k in selected if k not in by_key and k != "traceability"]
    if missing:
        readable = ", ".join((section(k) or {}).get("name", k) for k in missing)
        notes.append(f"It didn't draft: {readable}. Those sections are left as they are.")
    # Confirmed order, not the order it happened to answer in.
    return [by_key[k] for k in selected if k in by_key], notes


def document_storage(parts: list[dict[str, Any]]) -> str:
    return "".join(_built_storage(p) if p.get("built") else section_storage(p) for p in parts)


# --- Publishing -----------------------------------------------------------------------------------


async def publish(
    access: sources.Atlassian,
    *,
    mode: str,
    parts: list[dict[str, Any]],
    page_id: str,
    space_key: str,
    title: str,
    parent_id: str,
    label: str,
    actor: str,
) -> dict[str, Any]:
    """Write the design to Confluence.

    From a sample, a new page - or the page it made last time, so running again doesn't leave a
    trail of duplicates. Into an existing TDD, only the ticked sections are replaced and the rest
    of the page is preserved byte for byte. The update is version-guarded: if anyone saved since it
    was read, nothing is written and the result says so.
    """
    client = access.client
    if mode == "sample" and not page_id:
        try:
            existing = await client.find_page(space_key, title)
        except AtlassianError:
            existing = None
        if existing is None:
            new = await client.create_page(space_key, title, document_storage(parts), parent_id)
            await _label(client, new["id"], label)
            return {
                "url": new["url"],
                "page_id": new["id"],
                "version": 1,
                "space_key": space_key,
                "title": title,
                "written": [p["key"] for p in parts],
                "appended": [],
                "note": "",
                "published_by": actor,
                "published_at": sources.now(),
            }
        page_id = existing["id"]

    page = await client.page(page_id)
    storage, replaced, appended = splice(page.storage, parts)
    version = await client.update_page(
        page,
        storage,
        f"ShiftLeft Feature Kickoff, by {actor}: "
        + ", ".join((section(k) or {}).get("name", k) for k in replaced + appended),
    )
    await _label(client, page.page_id, label)
    return {
        "url": page.url,
        "page_id": page.page_id,
        "version": version,
        "space_key": page.space_key,
        "title": page.title,
        "written": replaced,
        "appended": appended,
        "note": "",
        "published_by": actor,
        "published_at": sources.now(),
    }


async def _label(client: Any, page_id: str, label: str) -> None:
    """Labelling is how the page is found again. It never decides whether the write succeeded."""
    with contextlib.suppress(AtlassianError):
        await client.add_labels(page_id, [label, "shiftleft-tracked"])


NO_CREDENTIAL = (
    "The design was drafted but not written: Confluence isn't connected for writing. Add the "
    "Confluence connector in Settings → Connectors, then publish it again."
)


def text_of_section(storage: str, heading: Heading) -> str:
    """What one section says now, as plain text, for a draft that updates rather than replaces."""
    return _text_of(storage[heading.body_start : heading.body_end])


def failure(exc: Exception) -> str:
    """A publish that didn't happen, in words a person can act on. Never a stack trace."""
    if isinstance(exc, AtlassianError) and exc.status == 409:
        return (
            "Someone saved the page while this ran, so nothing was written. "
            "Publish again to write onto their version."
        )
    if isinstance(exc, AtlassianError) and exc.status in (401, 403):
        return (
            "Confluence wouldn't let this account write there. Check the account in "
            "Settings → Connectors can edit that space."
        )
    if isinstance(exc, AtlassianError) and exc.status == 404:
        return "That space or page wasn't found, or this account can't see it."
    return f"Confluence didn't accept the write: {exc}"
