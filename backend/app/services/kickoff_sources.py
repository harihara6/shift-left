"""What Feature Kickoff reads, and with which credentials. Never example data.

* **Credentials** come from Settings -> Connectors first (the Confluence, Jira and GitHub
  instances, their secrets resolved from the vault at call time), then from the service's
  environment. Which one was used is recorded beside what it read, never the value.
* **The PRD** is read over Confluence REST when a credential for its site exists, and through the
  Rovo MCP server otherwise. Reads through MCP are fine; it is MCP *edits* that are lossy.
* **Repos** are read from GitHub at a pinned commit: metadata, languages, the README, the file
  tree, and any OpenAPI specs in it. Public repos read without a token, at a lower rate limit.
* **Docs** (our API docs, a provider's docs) are fetched from the URL given. The fetch refuses
  loopback and link-local hosts, so a URL typed into the page can't reach the service's own
  machine or a cloud metadata endpoint.

Every reader raises `NotReadable` with a message a person can act on. A step that can't read an
input shows it as unread with that reason; it never carries on as if the input were empty.
"""

import asyncio
import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import atlassian_mcp, atlassian_rest, openapi
from app.connectors import http as outbound
from app.core.config import get_settings
from app.models.connector import ConnectorInstance
from app.services import confluence_storage as storage
from app.services import vault


class NotReadable(Exception):
    """One input couldn't be read. The message says why, in words a person can act on."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Credentials --------------------------------------------------------------------------------


@dataclass
class Atlassian:
    client: atlassian_rest.AtlassianRest
    # Where the credential came from, for the page to show. Never the credential itself.
    source: str

    @property
    def host(self) -> str:
        return urlparse(self.client.site).netloc.lower()


@dataclass
class GitHub:
    api: str
    web_host: str
    token: str | None
    source: str


async def _instance(session: AsyncSession, key: str) -> ConnectorInstance | None:
    row = (
        (
            await session.execute(
                select(ConnectorInstance)
                .where(ConnectorInstance.connector_key == key)
                .order_by(ConnectorInstance.id)
            )
        )
        .scalars()
        .first()
    )
    return None if row is None or row.state == "disabled" else row


async def _secret(row: ConnectorInstance, field: str) -> str:
    ref = (row.secret_refs or {}).get(field)
    return (await vault.read(ref) or "") if ref else ""


async def atlassian(session: AsyncSession, prefer: tuple[str, ...]) -> Atlassian | None:
    """The first usable Atlassian credential: each connector in `prefer`, then the environment."""
    for key in prefer:
        row = await _instance(session, key)
        if row is None:
            continue
        site = str((row.config or {}).get("site_url") or "").strip()
        email = str((row.config or {}).get("account_email") or "").strip()
        token = await _secret(row, "api_token")
        if site and email and token:
            client = atlassian_rest.AtlassianRest(site=site, email=email, token=token)
            return Atlassian(client, f"Settings → Connectors → {key.title()}, as {email}")
    env = atlassian_rest.AtlassianRest()
    if env.available:
        return Atlassian(env, f"the service's Atlassian credentials, as {env.account}")
    return None


def rovo() -> atlassian_mcp.RovoMcpSource | None:
    source = atlassian_mcp.RovoMcpSource()
    return source if source.available else None


async def github(session: AsyncSession) -> GitHub:
    settings = get_settings()
    api = settings.github_api_url.rstrip("/")
    web_host = "github.com" if api == "https://api.github.com" else urlparse(api).netloc.lower()
    row = await _instance(session, "github")
    if row is not None:
        token = await _secret(row, "personal_access_token")
        if token:
            return GitHub(api, web_host, token, "Settings → Connectors → GitHub")
    if settings.github_token:
        return GitHub(api, web_host, settings.github_token.get_secret_value(), "the service's GitHub token")
    return GitHub(api, web_host, None, "no token: public repos only, at GitHub's anonymous rate limit")


# --- The PRD ------------------------------------------------------------------------------------

PAGE_IN_PATH = re.compile(r"/pages/(?:edit-v2/|edit/)?(\d+)")
TINY = re.compile(r"/wiki/x/([A-Za-z0-9_\-]+)")


def page_ref(url: str) -> tuple[str, str, str]:
    """(host, page id, tiny-link code) from a Confluence page link. A bare page id is accepted."""
    text = url.strip()
    if text.isdigit():
        return "", text, ""
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise NotReadable("That isn't a Confluence page link. Paste the page's address from the browser.")
    host = parsed.netloc.lower()
    if found := PAGE_IN_PATH.search(parsed.path):
        return host, found.group(1), ""
    page_id = (parse_qs(parsed.query).get("pageId") or [""])[0]
    if page_id.isdigit():
        return host, page_id, ""
    if found := TINY.search(parsed.path):
        return host, "", found.group(1)
    raise NotReadable(
        "No page id in that link. Open the page in Confluence and copy the address from the browser; "
        "it contains /pages/<number>/."
    )


async def _resolve_tiny(access: Atlassian, code: str) -> str:
    """A /wiki/x/ short link redirects to the page; its page id is in the redirect."""
    try:
        location = await access.client.short_link_target(code)
    except atlassian_rest.AtlassianError as exc:
        raise NotReadable(str(exc)) from exc
    found = PAGE_IN_PATH.search(location) or re.search(r"pageId=(\d+)", location)
    if not found:
        raise NotReadable("That short link didn't lead to a page. Paste the page's full address instead.")
    return found.group(1)


def markdown_lines(text: str) -> list[str]:
    """Markdown (as MCP returns a page) in the same line shape the storage reader produces."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or set(line) <= {"-", "|", ":", " "}:
            continue
        if heading := re.match(r"^#{1,6}\s+(.*)", line):
            out.append(f"## {heading.group(1).strip()}")
        elif bullet := re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)", line):
            out.append(f"- {bullet.group(1).strip()}")
        else:
            out.append(line)
    return out


def _prd(page: dict[str, Any], lines: list[str], url: str, via: str, via_label: str) -> dict[str, Any]:
    if not any(not ln.startswith("## ") for ln in lines):
        raise NotReadable(
            "The page was read, but it has no text. Is the PRD written on this page, or linked from it?"
        )
    return {
        "url": url or page.get("url", ""),
        "page_id": page["page_id"],
        "title": page["title"] or "Untitled page",
        "space": page.get("space", ""),
        "version": int(page.get("version") or 0),
        "updated": page.get("updated", ""),
        "via": via,
        "via_label": via_label,
        "lines": lines,
        "word_count": sum(len(ln.split()) for ln in lines),
        "sections": [ln[3:] for ln in lines if ln.startswith("## ")][:40],
        "read_at": now(),
    }


async def read_page(session: AsyncSession, url: str) -> tuple[dict[str, Any], list[str], str, str]:
    """(page, lines, via, via_label) for any Confluence page: REST when there is a credential for
    its site, the Rovo MCP server otherwise. The callers decide what the page has to contain."""
    host, page_id, tiny = page_ref(url)
    access = await atlassian(session, ("confluence", "jira"))
    if access is not None and (not host or host == access.host):
        if tiny:
            page_id = await _resolve_tiny(access, tiny)
        try:
            page = await access.client.page(page_id)
        except atlassian_rest.AtlassianError as exc:
            if exc.status == 404:
                raise NotReadable(
                    f"Page {page_id} wasn't found on {access.host}, or {access.client.account} can't see it."
                ) from exc
            raise NotReadable(str(exc)) from exc
        return (
            {
                "page_id": page.page_id,
                "title": page.title,
                "space": page.space_key,
                "version": page.version,
                "updated": page.updated,
                "url": page.url or url,
            },
            storage.body_lines(page.storage),
            "rest",
            f"Confluence REST · {access.source}",
        )

    mcp = rovo()
    mcp_host = urlparse(mcp.site_url).netloc.lower() if mcp else ""
    if mcp is not None and (not host or host == mcp_host) and page_id:
        try:
            page = await mcp.read_page(page_id)
        except atlassian_mcp.RovoUnavailable as exc:
            raise NotReadable(f"The Rovo MCP server couldn't read the page: {exc}") from exc
        page = {**page, "url": page.get("url") or url}
        return page, markdown_lines(page["body"]), "mcp", "Atlassian Rovo MCP"

    if access is not None or mcp is not None:
        connected = access.host if access else mcp_host
        raise NotReadable(
            f"This page is on {host}, but Feature Kickoff is connected to {connected}. "
            "Paste a page from that site, or connect this one in Settings → Connectors."
        )
    raise NotReadable(
        "Confluence isn't connected. Add the Confluence connector in Settings → Connectors (site URL, "
        "account email and API token), or configure the Rovo MCP server, then fetch the page again."
    )


async def read_prd(session: AsyncSession, url: str) -> dict[str, Any]:
    page, lines, via, via_label = await read_page(session, url)
    return _prd(page, lines, page.get("url") or url, via, via_label)


async def read_confluence_doc(session: AsyncSession, url: str) -> dict[str, Any]:
    """A Confluence page read as reference material. Unlike the PRD it may be mostly headings, so
    an empty page is a read that says so rather than a refusal."""
    page, lines, _via, via_label = await read_page(session, url)
    text = "\n".join(lines)
    return {
        "url": url.strip(),
        "final_url": page.get("url") or url.strip(),
        "ok": True,
        "error": "",
        "kind": "confluence",
        "title": page.get("title") or "Untitled page",
        "version": f"v{page.get('version') or 0}",
        "page_id": page.get("page_id", ""),
        "space": page.get("space", ""),
        "summary": " ".join(text.split())[:400] or "The page has no text; only its link is used.",
        "operations": [],
        "deprecated": [],
        "security": [],
        "servers": [],
        "text": text[:DOC_TEXT_CHARS],
        "read_with": f"{via_label}",
        "read_at": now(),
    }


# --- GitHub repos -------------------------------------------------------------------------------

REPO_URL = re.compile(
    r"^(?:(?:https?://)?(?P<host>[^/\s]+)/)?(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)"
    r"(?:\.git)?(?:/(?:tree|blob)/(?P<ref>[^/\s?#]+))?(?:/[^\s]*)?/?$"
)
SPEC_FILE = re.compile(r"(^|/)(openapi|swagger|api-spec|api)[^/]*\.(ya?ml|json)$", re.I)
SKIP_DIRS = re.compile(
    r"(^|/)(node_modules|\.git|dist|build|target|vendor|__pycache__|\.venv|coverage|\.idea)/"
)
MANIFESTS = re.compile(
    r"(^|/)(package\.json|pom\.xml|build\.gradle(\.kts)?|settings\.gradle(\.kts)?|go\.mod|pyproject\.toml|"
    r"requirements\.txt|Cargo\.toml|[^/]+\.csproj|angular\.json|Dockerfile|Chart\.yaml|docker-compose\.ya?ml)$"
)
MAX_PATHS = 600
MAX_SPECS = 3
README_CHARS = 8000


def repo_ref(url: str, web_host: str) -> tuple[str, str, str]:
    """(owner, name, ref) from a GitHub link, `owner/name`, or a git@ remote."""
    text = url.strip()
    if text.startswith("git@"):
        text = text.split("@", 1)[1].replace(":", "/", 1)
    found = REPO_URL.match(text)
    if not found:
        raise NotReadable("That isn't a GitHub repository link. Use https://github.com/<owner>/<repo>.")
    host = (found.group("host") or web_host).lower().removeprefix("www.")
    if host != web_host:
        raise NotReadable(f"That repo is on {host}; Feature Kickoff reads repos on {web_host}.")
    return found.group("owner"), found.group("name"), found.group("ref") or ""


def _why(response: httpx.Response, what: str, anonymous: bool) -> str:
    if response.status_code == 404:
        hint = (
            " Private repos need a GitHub token with access: add one in Settings → Connectors → GitHub."
            if anonymous
            else " Check the token in Settings → Connectors → GitHub can see it."
        )
        return f"{what} wasn't found, or isn't visible.{hint}"
    if response.status_code in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0":
        return "GitHub's rate limit is used up for now." + (
            " Add a token in Settings → Connectors → GitHub for a much higher limit." if anonymous else ""
        )
    if response.status_code == 401:
        return "GitHub rejected the token. Rotate it in Settings → Connectors → GitHub."
    return f"GitHub couldn't return {what} (HTTP {response.status_code})."


async def read_repo(access: GitHub, url: str) -> dict[str, Any]:
    owner, name, ref = repo_ref(url, access.web_host)
    base = f"{access.api}/repos/{owner}/{name}"
    headers = {"X-GitHub-Api-Version": "2022-11-28", "Accept": "application/vnd.github+json"}
    if access.token:
        headers["Authorization"] = f"Bearer {access.token}"
    anonymous = access.token is None

    try:
        async with outbound.client(timeout=20.0, headers=headers) as c:
            meta = await c.get(base)
            if meta.status_code >= 400:
                raise NotReadable(_why(meta, f"{owner}/{name}", anonymous))
            info = meta.json()
            ref = ref or info.get("default_branch") or "HEAD"
            sha = await c.get(
                f"{base}/commits/{quote(ref, safe='')}", headers={"Accept": "application/vnd.github.sha"}
            )
            if sha.status_code >= 400:
                raise NotReadable(_why(sha, f"{owner}/{name} at {ref}", anonymous))
            commit = sha.text.strip()
            tree_r, langs_r, readme_r = await asyncio.gather(
                c.get(f"{base}/git/trees/{commit}", params={"recursive": "1"}),
                c.get(f"{base}/languages"),
                c.get(
                    f"{base}/readme",
                    params={"ref": commit},
                    headers={"Accept": "application/vnd.github.raw+json"},
                ),
            )
            tree = tree_r.json() if tree_r.status_code < 400 else {}
            blobs = [e["path"] for e in tree.get("tree", []) if e.get("type") == "blob" and e.get("path")]
            dirs = [e["path"] for e in tree.get("tree", []) if e.get("type") == "tree" and e.get("path")]
            kept = sorted(p for p in blobs if not SKIP_DIRS.search(p))
            spec_paths = [p for p in kept if SPEC_FILE.search(p)][:MAX_SPECS]
            web = f"https://{access.web_host}/{info.get('full_name') or f'{owner}/{name}'}"
            specs = await asyncio.gather(*(_spec(c, base, web, commit, p) for p in spec_paths))
    except httpx.HTTPError as exc:
        raise NotReadable(f"Couldn't reach GitHub ({type(exc).__name__}).") from exc

    languages = langs_r.json() if langs_r.status_code < 400 else {}
    total = sum(v for v in languages.values() if isinstance(v, int)) or 1
    return {
        "url": web,
        "full_name": info.get("full_name") or f"{owner}/{name}",
        "ok": True,
        "error": "",
        "description": info.get("description") or "",
        "default_branch": info.get("default_branch") or "",
        "ref": ref,
        "commit": commit[:12],
        "commit_url": f"{web}/tree/{commit}",
        "language": info.get("language") or "",
        "languages": [
            {"name": k, "share": round(v / total, 3)}
            for k, v in sorted(languages.items(), key=lambda kv: -kv[1])
            if isinstance(v, int)
        ][:6],
        "topics": info.get("topics") or [],
        "visibility": info.get("visibility") or "",
        "archived": bool(info.get("archived")),
        "readme": readme_r.text[:README_CHARS] if readme_r.status_code < 400 else "",
        "file_count": len(kept),
        "tree_truncated": bool(tree.get("truncated")) or len(kept) > MAX_PATHS,
        "top_level": sorted(
            {p.split("/")[0] + ("/" if "/" in p else "") for p in kept}
            | {d + "/" for d in dirs if "/" not in d}
        )[:60],
        "manifests": [p for p in kept if MANIFESTS.search(p)][:40],
        "paths": kept[:MAX_PATHS],
        "specs": list(specs),
        "read_with": access.source,
        "read_at": now(),
    }


async def _spec(c: httpx.AsyncClient, base: str, web: str, commit: str, path: str) -> dict:
    url = f"{web}/blob/{commit}/{path}"
    raw = await c.get(
        f"{base}/contents/{quote(path)}",
        params={"ref": commit},
        headers={"Accept": "application/vnd.github.raw+json"},
    )
    if raw.status_code >= 400:
        return {
            "path": path,
            "url": url,
            "ok": False,
            "error": f"HTTP {raw.status_code}",
            "title": "",
            "version": "",
            "operations": [],
            "deprecated": [],
        }
    try:
        spec = openapi.parse(raw.text)
    except openapi.SpecUnreadable as exc:
        return {
            "path": path,
            "url": url,
            "ok": False,
            "error": str(exc)[:200],
            "title": "",
            "version": "",
            "operations": [],
            "deprecated": [],
        }
    return {
        "path": path,
        "url": url,
        "ok": True,
        "error": "",
        "title": spec.title,
        "version": spec.version,
        "operations": spec.operations[:300],
        "deprecated": spec.deprecated[:100],
    }


def repo_failure(url: str, reason: str) -> dict[str, Any]:
    return {"url": url.strip(), "full_name": url.strip(), "ok": False, "error": reason, "read_at": now()}


# --- Docs (our API docs, third-party docs) --------------------------------------------------------

MAX_DOC_BYTES = 3_000_000
DOC_TEXT_CHARS = 14000
MAX_REDIRECTS = 5


async def resolve_host(host: str) -> list[str]:
    """The addresses a host resolves to. Tests replace this; nothing else should."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def _guard(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise NotReadable("Only http and https links can be read.")
    try:
        addresses = await resolve_host(parsed.hostname)
    except OSError as exc:
        raise NotReadable(f"{parsed.hostname} couldn't be resolved. Is the address right?") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
            raise NotReadable(f"{parsed.hostname} points at a local or reserved address, which isn't read.")


class _Text(HTMLParser):
    SKIP: ClassVar[set[str]] = {"script", "style", "noscript", "svg", "nav", "footer", "header", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "li", "h1", "h2", "h3", "h4", "tr", "br", "div", "section", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def page_text(markup: str) -> tuple[str, str]:
    parser = _Text()
    parser.feed(markup)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return " ".join(parser.title.split()), "\n".join(ln for ln in lines if ln)


async def fetch(url: str) -> tuple[str, str, str]:
    """(final url, content type, body text), following redirects only to hosts the guard allows."""
    current = url.strip()
    for _ in range(MAX_REDIRECTS + 1):
        await _guard(current)
        try:
            async with (
                outbound.client(timeout=20.0) as c,
                c.stream(
                    "GET",
                    current,
                    headers={
                        "User-Agent": "ShiftLeft-FeatureKickoff/1.0",
                        "Accept": "text/html,application/json,application/yaml,*/*;q=0.5",
                    },
                ) as response,
            ):
                if response.is_redirect and response.headers.get("location"):
                    current = urljoin(current, response.headers["location"])
                    continue
                if response.status_code >= 400:
                    raise NotReadable(
                        f"{urlparse(current).hostname} answered HTTP {response.status_code}"
                        + (
                            ": it needs a login, so only the link is used."
                            if response.status_code in (401, 403)
                            else "."
                        )
                    )
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_DOC_BYTES:
                        break
                return (
                    current,
                    response.headers.get("content-type", ""),
                    body.decode(response.encoding or "utf-8", errors="replace"),
                )
        except httpx.HTTPError as exc:
            raise NotReadable(f"Couldn't reach {urlparse(current).hostname} ({type(exc).__name__}).") from exc
    raise NotReadable("Too many redirects.")


async def read_doc(url: str) -> dict[str, Any]:
    final, content_type, body = await fetch(url)
    base = {"url": url.strip(), "final_url": final, "ok": True, "error": "", "read_at": now()}
    looks_like_spec = any(t in content_type for t in ("json", "yaml", "yml")) or re.search(
        r"\.(ya?ml|json)$", urlparse(final).path, re.I
    )
    if looks_like_spec or body.lstrip().startswith(("{", "openapi:", "swagger:")):
        try:
            spec = openapi.parse(body)
        except openapi.SpecUnreadable:
            spec = None
        if spec is not None:
            return {
                **base,
                "kind": "openapi",
                "title": spec.title or "OpenAPI document",
                "version": spec.version,
                "summary": f"{len(spec.operations)} operation(s)"
                + (f", {len(spec.deprecated)} deprecated" if spec.deprecated else ""),
                "operations": spec.operations[:400],
                "deprecated": spec.deprecated[:100],
                "security": spec.security,
                "servers": spec.servers,
                "text": "",
            }
    if "html" in content_type or "<html" in body[:2000].lower():
        title, text = page_text(body)
    else:
        title, text = "", html.unescape(body)
    if not text.strip():
        raise NotReadable("The page loaded but has no readable text (it may be rendered by JavaScript).")
    return {
        **base,
        "kind": "page",
        "title": title or urlparse(final).hostname or final,
        "version": "",
        "summary": " ".join(text.split())[:400],
        "operations": [],
        "deprecated": [],
        "security": [],
        "servers": [],
        "text": text[:DOC_TEXT_CHARS],
    }


def doc_failure(url: str, reason: str) -> dict[str, Any]:
    return {
        "url": url.strip(),
        "final_url": "",
        "ok": False,
        "error": reason,
        "kind": "",
        "title": "",
        "version": "",
        "summary": "",
        "operations": [],
        "deprecated": [],
        "security": [],
        "servers": [],
        "text": "",
        "read_at": now(),
    }


# --- Routing a pasted link ------------------------------------------------------------------------

# A Confluence link, whatever the site is called: the wiki prefix, a page path, or a pageId query.
CONFLUENCE_LINK = re.compile(r"(^|/)wiki(/|$)|/pages/\d+|[?&]pageId=\d+")

Kind = str  # "repo" | "confluence" | "doc"


def classify(url: str, github_host: str, atlassian_host: str = "") -> Kind:
    """Which reader a pasted link belongs to. Material we rely on can be code, a Confluence page,
    or any other document, and the person shouldn't have to say which."""
    text = url.strip()
    if text.startswith("git@"):
        return "repo"
    if "://" not in text and "." not in text.split("/", 1)[0]:
        # `owner/name`, the shorthand GitHub itself uses.
        return "repo" if REPO_URL.match(text) else "doc"
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host == github_host:
        return "repo"
    if (atlassian_host and host == atlassian_host) or CONFLUENCE_LINK.search(
        f"{parsed.path}?{parsed.query}"
    ):
        return "confluence"
    return "doc"
