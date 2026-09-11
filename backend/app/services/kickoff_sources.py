"""The systems Feature Kickoff reads: the example pages, or the live ones. Never a mix.

`SHIFTLEFT_KICKOFF_SOURCES` picks one for the whole service:

* **fixtures**: `seed/data/kickoff.json`, example pages behind the same contract.
* **live**: PRDs and the software catalog from Confluence, each service's API spec from GitHub
  at a pinned commit, and the product index through its parser. A live source that isn't
  configured reads as unavailable with the reason, never as example data.

Standards and reviewed vendors come from the registry (`kickoff_registry.json`) in both modes:
pinned, dated, changed by pull request, never recalled from a model's memory.

What the checks read is frozen into a **snapshot** on the session when they run. The plan, the
diffs and the version guard on apply all work from that snapshot, so a finding stays true to what
was read, and a page that changed since is caught rather than silently overwritten.
"""

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.connectors import atlassian_rest, github_specs, openapi, product_index
from app.connectors import http as outbound
from app.core.config import get_settings
from app.services import confluence_storage as storage

DATA = Path(__file__).resolve().parent.parent / "seed" / "data"
FIXTURES = DATA / "kickoff.json"
REGISTRY = DATA / "kickoff_registry.json"

FIXTURE_NOTE = (
    "Reading example pages: Confluence, GitHub, vendor docs and the product index are stood in by "
    "fixtures. Live readers replace them without changing anything on this page."
)
LIVE_NOTE = (
    "Reading live pages: Confluence, GitHub and the product index, as the configured accounts see them."
)

logger = logging.getLogger("shiftleft.kickoff")


class SourceUnavailable(Exception):
    """A live source that can't be read. The message says why, in words a person can act on."""


@lru_cache
def _fixtures() -> dict[str, Any]:
    return json.loads(FIXTURES.read_text())


@lru_cache
def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text())


def mode() -> str:
    return get_settings().kickoff_sources


def note() -> str:
    return LIVE_NOTE if mode() == "live" else FIXTURE_NOTE


def standards() -> list[dict]:
    return _registry()["standards"]


def spec_url(item: dict[str, Any]) -> str:
    """The fixture spec file at the commit it was read at."""
    return f"https://github.com/{item['repo']}/blob/{item['commit']}/{item['spec_path']}"


# --- PRDs -------------------------------------------------------------------------------------


def _escape_cql(text: str) -> str:
    return text.replace("\\", "").replace('"', "")


async def list_prds(query: str = "") -> list[dict]:
    """PRD pages, newest first. Raises SourceUnavailable when live Confluence can't answer."""
    needle = query.strip()
    if mode() != "live":
        low = needle.lower()
        return [p for p in _fixtures()["prds"]
                if not low or low in p["title"].lower() or low in p["space"].lower()]
    confluence = atlassian_rest.AtlassianRest()
    if not confluence.available:
        raise SourceUnavailable(confluence.unavailable_reason)
    cql = f'label = "{_escape_cql(get_settings().kickoff_prd_label)}" and type = page'
    if needle:
        cql += f' and title ~ "{_escape_cql(needle)}"'
    try:
        pages = await confluence.search_pages(cql + " order by lastmodified desc")
    except atlassian_rest.AtlassianError as exc:
        raise SourceUnavailable(str(exc)) from exc
    # A PRD belongs to the project whose key matches its space: the convention, until spaces are
    # bound to projects in Settings.
    return [{**p, "project_key": p["space"]} for p in pages]


async def prd(page_id: str) -> dict | None:
    """The page with its body as lines, at the version read. None if it doesn't exist."""
    if mode() != "live":
        return next((p for p in _fixtures()["prds"] if p["page_id"] == page_id), None)
    confluence = atlassian_rest.AtlassianRest()
    if not confluence.available:
        raise SourceUnavailable(confluence.unavailable_reason)
    try:
        page = await confluence.page(page_id)
    except atlassian_rest.AtlassianError as exc:
        if exc.status == 404:
            return None
        raise SourceUnavailable(str(exc)) from exc
    return {
        "page_id": page.page_id, "project_key": page.space_key, "space": page.space_key,
        "title": page.title, "url": page.url, "version": page.version, "updated": page.updated,
        "author": "", "body": storage.body_lines(page.storage),
    }


# --- The snapshot the checks read -------------------------------------------------------------


def _spec_read(**fields) -> dict:
    return {"read": True, "note": "", **fields}


def _spec_missing(note: str, url: str = "") -> dict:
    return {"read": False, "note": note, "commit": "", "url": url, "operations": [], "deprecated": []}


def _fixture_snapshot() -> dict:
    fx = _fixtures()
    catalog = fx["software_catalog"]
    components = []
    for c in catalog["components"]:
        spec = _spec_read(commit=c["commit"], url=spec_url(c), operations=c["operations"],
                          deprecated=c["deprecated"])
        components.append({k: c[k] for k in ("name", "owner", "jira_project", "repo", "spec_path", "status")}
                          | {"planned": c.get("planned", []), "spec": spec})
    index = fx["product_index"]
    return {
        "catalog": {"available": True, "note": "", "page_id": catalog["page_id"], "title": catalog["title"],
                    "url": catalog["url"], "version": catalog["version"],
                    "columns": ["name", "owner", "jira_project", "repo", "spec_path", "status", "planned"],
                    "components": components},
        "index": {"available": True, "note": "", "title": index["title"], "url": index["url"],
                  "version": f"v{index['version']}", "features": index["features"]},
        "vendors": fx["vendors"],
    }


async def _live_catalog(services: list[str]) -> dict:
    settings = get_settings()
    empty = {"available": False, "page_id": settings.software_catalog_page_id, "title": "Software catalog",
             "url": "", "version": 0, "columns": [], "components": []}
    if not settings.software_catalog_page_id:
        return {**empty,
                "note": "No software catalog page is configured (SHIFTLEFT_SOFTWARE_CATALOG_PAGE_ID)."}
    confluence = atlassian_rest.AtlassianRest()
    if not confluence.available:
        return {**empty, "note": confluence.unavailable_reason}
    try:
        page = await confluence.page(settings.software_catalog_page_id)
        table = storage.catalog_table(page.storage)
    except (atlassian_rest.AtlassianError, storage.TableUnreadable) as exc:
        return {**empty, "note": f"Couldn't read the software catalog: {exc}"}

    github = github_specs.GitHubSpecs()
    wanted = {s.lower() for s in services}

    async def spec_for(row: dict) -> dict:
        if row["name"].lower() not in wanted:
            return _spec_missing("Not read: the PRD doesn't depend on it.")
        if not row.get("repo") or not row.get("spec_path"):
            return _spec_missing("The catalog row names no repository and spec path to read.")
        try:
            read = await github.read(row["repo"], row["spec_path"], row.get("ref") or "HEAD")
        except github_specs.SpecNotRead as exc:
            return _spec_missing(str(exc), f"https://github.com/{row['repo']}")
        return _spec_read(commit=read.commit, url=read.url, operations=read.operations,
                          deprecated=read.deprecated)

    specs = await asyncio.gather(*(spec_for(r) for r in table.rows))
    components = [
        {"name": r["name"], "owner": r.get("owner", ""), "jira_project": r.get("jira_project", ""),
         "repo": r.get("repo", ""), "spec_path": r.get("spec_path", ""), "status": r.get("status", ""),
         "planned": storage.split_list(r.get("planned", "")), "spec": spec}
        for r, spec in zip(table.rows, specs, strict=True)
    ]
    return {"available": True, "note": "", "page_id": page.page_id, "title": page.title, "url": page.url,
            "version": page.version, "columns": [k for k in table.keys if k], "components": components}


async def _vendor_spec(vendor: dict) -> dict:
    """A reviewed vendor, plus what their published OpenAPI says today, if they publish one."""
    url = vendor.get("openapi_url")
    if not url:
        return vendor
    findings = list(vendor.get("findings", []))
    try:
        async with outbound.client() as c:
            response = await c.get(url, follow_redirects=True)
        response.raise_for_status()
        spec = openapi.parse(response.text)
    except Exception as exc:  # any failure is a not-checked row, never a pass
        findings.append({"aspect": "Published API spec", "status": "not_checked",
                         "text": f"Couldn't read {url} ({type(exc).__name__})."})
        return {**vendor, "findings": findings}
    findings.append({"aspect": "Published API spec", "status": "ok",
                     "text": f"{spec.title or 'Spec'} {spec.version}: {len(spec.operations)} operation(s), "
                             f"{len(spec.deprecated)} deprecated."})
    findings.append({"aspect": "Auth model (from the spec)", "status": "ok" if spec.security else "gap",
                     "text": "; ".join(spec.security) or "The spec declares no security scheme."})
    return {**vendor, "findings": findings}


async def snapshot(services: list[str]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    if mode() != "live":
        return {"mode": "fixtures", "read_at": now, **_fixture_snapshot(), "standards": standards()}
    catalog, index, vendors = await asyncio.gather(
        _live_catalog(services), product_index.read(),
        asyncio.gather(*(_vendor_spec(v) for v in _registry()["vendors"])),
    )
    return {"mode": "live", "read_at": now, "catalog": catalog, "index": asdict(index),
            "vendors": list(vendors), "standards": standards()}


class Snap:
    """Read access to a stored snapshot. An empty one means the checks haven't run yet."""

    def __init__(self, data: dict | None) -> None:
        self.data = data or {
            "mode": mode(), "read_at": None, "vendors": [], "standards": standards(),
            "catalog": {"available": False, "note": "Not read yet: the checks haven't run.", "page_id": "",
                        "title": "Software catalog", "url": "", "version": 0, "columns": [],
                        "components": []},
            "index": {"available": False, "note": "Not read yet: the checks haven't run.",
                      "title": "Product index", "url": "", "version": "", "features": []},
        }

    @property
    def catalog(self) -> dict:
        return self.data["catalog"]

    @property
    def index(self) -> dict:
        return self.data["index"]

    def component(self, name: str) -> dict | None:
        return next((c for c in self.catalog["components"] if c["name"].lower() == name.lower()), None)

    def vendor(self, name: str) -> dict | None:
        return next((v for v in self.data["vendors"] if v["name"].lower() == name.lower()), None)

    def standard(self, key: str) -> dict | None:
        return next((s for s in self.data["standards"] if s["key"] == key), None)

    def catalog_link(self) -> dict | None:
        c = self.catalog
        return {"label": f"{c['title']} v{c['version']}", "url": c["url"]} if c.get("url") else None
