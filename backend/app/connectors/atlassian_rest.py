"""Jira and Confluence Cloud over REST: Feature Kickoff's live reads and writes.

Why REST and not the Rovo MCP server that onboarding discovers with:

* **Rovo edits are lossy.** It hands page bodies to the model as Markdown and converts them back,
  which drops tables, macros, panels and mentions (atlassian/atlassian-mcp-server#60). The
  software catalog is a table on a shared page, so one kickoff could strip it. Here a catalog edit
  changes one table's rows in the page's own storage format and leaves every other byte alone.
* **Versions are enforced.** A Confluence update carries the next version number and is refused
  if someone else saved in between, which is exactly the "changed since the plan was drafted" stop.
* **The contract is documented.** Every call below is a published endpoint with a stable shape;
  guessing at an MCP tool's arguments against a remote we don't control is not.

An API token acts as the account that owns it. Whoever that is, the write is recorded in ShiftLeft
against the person who confirmed it, and every created issue and page says who that was.
Credentials are read at call time and never logged, returned or stored.
"""

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.connectors import http
from app.core.config import get_settings

logger = logging.getLogger("shiftleft.atlassian")


class AtlassianError(RuntimeError):
    """A call Jira or Confluence refused. The message is safe to show; it never holds a secret."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class PageRead:
    page_id: str
    title: str
    space_key: str
    space_id: str
    version: int
    storage: str
    url: str
    updated: str = ""
    author: str = ""


def _message(response: httpx.Response, action: str) -> str:
    """Jira and Confluence explain a refusal in the body. Keep their words, drop everything else."""
    reasons: list[str] = []
    try:
        body = response.json()
    except ValueError:
        body = {}
    if isinstance(body, dict):
        reasons += [str(m) for m in body.get("errorMessages") or []]
        errors = body.get("errors")
        if isinstance(errors, dict):
            reasons += [f"{k}: {v}" for k, v in errors.items()]
        elif isinstance(errors, list):
            reasons += [str(e.get("title") or e.get("detail") or e) for e in errors if e]
        if body.get("message"):
            reasons.append(str(body["message"]))
    known = {401: "the credentials were rejected", 403: "the account isn't permitted to do this",
             404: "it wasn't found, or the account can't see it", 409: "someone else changed it first"}
    text = "; ".join(reasons) or known.get(response.status_code, f"HTTP {response.status_code}")
    return f"{action} failed: {text}"


class AtlassianRest:
    def __init__(
        self, *, site: str | None = None, email: str | None = None, token: str | None = None,
    ) -> None:
        """Defaults to the service-wide settings (Feature Kickoff's path); pass `site`/`email`/
        `token` to act as one connector instance's own configuration instead (Settings ->
        Connectors' "Test connection" path) - the HTTP calls below are the same either way.
        """
        settings = get_settings()
        self.site = (site if site is not None else settings.atlassian_site_url).rstrip("/")
        self._email = email if email is not None else settings.atlassian_email
        if token is not None:
            self._token = token
        elif settings.atlassian_api_token:
            self._token = settings.atlassian_api_token.get_secret_value()
        else:
            self._token = None
        self._spaces: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return bool(self.site and self._email and self._token)

    @property
    def unavailable_reason(self) -> str:
        if not self.site:
            return "No Atlassian site is configured (SHIFTLEFT_ATLASSIAN_SITE_URL)."
        if not (self._email and self._token):
            return "No Atlassian API credentials (SHIFTLEFT_ATLASSIAN_EMAIL, SHIFTLEFT_ATLASSIAN_API_TOKEN)."
        return ""

    @property
    def account(self) -> str:
        """Who the writes act as. An email, not a secret; shown so nobody is surprised."""
        return self._email

    # -- transport -------------------------------------------------------------------------

    async def _call(self, method: str, path: str, action: str, **kwargs) -> Any:
        if not self.available:
            raise AtlassianError(self.unavailable_reason)
        auth = (self._email, self._token or "")
        try:
            async with http.client(timeout=30.0) as c:
                response = await c.request(
                    method, f"{self.site}{path}", auth=auth, headers={"Accept": "application/json"}, **kwargs
                )
        except httpx.HTTPError as exc:
            reason = f"{action} failed: couldn't reach {self.site} ({type(exc).__name__})"
            raise AtlassianError(reason) from exc
        if response.status_code >= 400:
            raise AtlassianError(_message(response, action), response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # -- Connection tests --------------------------------------------------------------------

    async def whoami(self) -> dict:
        """Settings -> Connectors' "Test connection" for Jira: one authenticated read, so a
        wrong token or email reads as a real refusal rather than an assumed success."""
        return await self._call("GET", "/rest/api/3/myself", "Checking the Jira connection")

    async def whoami_confluence(self) -> dict:
        return await self._call(
            "GET", "/wiki/rest/api/user/current", "Checking the Confluence connection"
        )

    # -- Confluence ------------------------------------------------------------------------

    def page_url(self, webui: str) -> str:
        return f"{self.site}/wiki{webui}" if webui else ""

    async def short_link_target(self, code: str) -> str:
        """Where a /wiki/x/<code> short link redirects: the page's full address."""
        if not self.available:
            raise AtlassianError(self.unavailable_reason)
        try:
            async with http.client(timeout=15.0) as c:
                response = await c.get(
                    f"{self.site}/wiki/x/{quote(code)}", auth=(self._email, self._token or ""),
                    follow_redirects=False,
                )
        except httpx.HTTPError as exc:
            raise AtlassianError(f"Opening the short link failed: couldn't reach {self.site}") from exc
        if response.status_code >= 400:
            raise AtlassianError(_message(response, "Opening the short link"), response.status_code)
        return response.headers.get("location", "")

    async def search_pages(self, cql: str, limit: int = 25) -> list[dict]:
        body = await self._call(
            "GET", "/wiki/rest/api/search", "Searching Confluence",
            params={"cql": cql, "limit": limit, "expand": "content.version,content.space"},
        )
        pages = []
        for row in (body or {}).get("results", []):
            content = row.get("content") or {}
            if content.get("type") != "page" or not content.get("id"):
                continue
            version = content.get("version") or {}
            pages.append({
                "page_id": str(content["id"]), "title": content.get("title", ""),
                "space": (content.get("space") or {}).get("key", ""),
                "url": self.page_url((content.get("_links") or {}).get("webui", "")),
                "version": int(version.get("number") or 0),
                "updated": str(row.get("lastModified") or version.get("when") or "")[:10],
                "author": (version.get("by") or {}).get("displayName", ""),
            })
        return pages

    async def space_key(self, space_id: str) -> str:
        body = await self._call("GET", f"/wiki/api/v2/spaces/{quote(space_id)}", "Reading the space")
        return (body or {}).get("key", "")

    async def space_id(self, key: str) -> str:
        if key in self._spaces:
            return self._spaces[key]
        body = await self._call("GET", "/wiki/api/v2/spaces", "Finding the space", params={"keys": key})
        results = (body or {}).get("results") or []
        if not results:
            raise AtlassianError(
                f"Finding the space failed: no space {key!r} is visible to this account", 404)
        self._spaces[key] = str(results[0]["id"])
        return self._spaces[key]

    async def page(self, page_id: str) -> PageRead:
        body = await self._call(
            "GET", f"/wiki/api/v2/pages/{quote(page_id)}", "Reading the page",
            params={"body-format": "storage"},
        )
        space_id = str(body.get("spaceId", ""))
        version = body.get("version") or {}
        return PageRead(
            page_id=str(body["id"]), title=body.get("title", ""),
            space_key=await self.space_key(space_id) if space_id else "", space_id=space_id,
            version=int(version.get("number") or 0),
            storage=((body.get("body") or {}).get("storage") or {}).get("value", ""),
            url=self.page_url((body.get("_links") or {}).get("webui", "")),
            updated=str(version.get("createdAt", ""))[:10],
        )

    async def find_page(self, space_key: str, title: str) -> dict | None:
        space_id = await self.space_id(space_key)
        body = await self._call(
            "GET", "/wiki/api/v2/pages", "Looking for an existing page",
            params={"space-id": space_id, "title": title, "limit": 1},
        )
        results = (body or {}).get("results") or []
        if not results:
            return None
        row = results[0]
        return {"id": str(row["id"]), "url": self.page_url((row.get("_links") or {}).get("webui", ""))}

    async def create_page(self, space_key: str, title: str, storage: str, parent_id: str = "") -> dict:
        payload: dict[str, Any] = {
            "spaceId": await self.space_id(space_key), "status": "current", "title": title,
            "body": {"representation": "storage", "value": storage},
        }
        if parent_id:
            payload["parentId"] = parent_id
        body = await self._call("POST", "/wiki/api/v2/pages", "Creating the page", json=payload)
        return {"id": str(body["id"]), "url": self.page_url((body.get("_links") or {}).get("webui", ""))}

    async def update_page(self, page: PageRead, storage: str, message: str) -> int:
        """Save a new version. Refused (409) if anyone saved since `page` was read."""
        version = page.version + 1
        await self._call(
            "PUT", f"/wiki/api/v2/pages/{quote(page.page_id)}", "Updating the page",
            json={
                "id": page.page_id, "status": "current", "title": page.title,
                "body": {"representation": "storage", "value": storage},
                "version": {"number": version, "message": message},
            },
        )
        return version

    async def add_labels(self, page_id: str, labels: list[str]) -> None:
        if labels:
            await self._call(
                "POST", f"/wiki/rest/api/content/{quote(page_id)}/label", "Labelling the page",
                json=[{"prefix": "global", "name": label} for label in labels],
            )

    # -- Jira ------------------------------------------------------------------------------

    def issue_url(self, key: str) -> str:
        return f"{self.site}/browse/{key}"

    async def issue_types(self, project: str) -> dict[str, str]:
        """Issue type name → id, for the types this account can create in `project`."""
        body = await self._call(
            "GET", f"/rest/api/3/issue/createmeta/{quote(project)}/issuetypes", "Reading issue types"
        )
        rows = (body or {}).get("issueTypes") or (body or {}).get("values") or []
        return {row["name"]: str(row["id"]) for row in rows if row.get("name")}

    async def required_fields(self, project: str, type_id: str) -> list[dict]:
        body = await self._call(
            "GET", f"/rest/api/3/issue/createmeta/{quote(project)}/issuetypes/{quote(type_id)}",
            "Reading required fields", params={"maxResults": 200},
        )
        rows = (body or {}).get("fields") or (body or {}).get("values") or []
        return [r for r in rows if r.get("required") and not r.get("hasDefaultValue")]

    async def search_issues(self, jql: str) -> list[dict]:
        body = await self._call(
            "GET", "/rest/api/3/search/jql", "Searching Jira",
            params={"jql": jql, "fields": "summary,issuetype,project", "maxResults": 100},
        )
        return [
            {"id": str(i["id"]), "key": i["key"], "summary": (i.get("fields") or {}).get("summary", ""),
             "project": ((i.get("fields") or {}).get("project") or {}).get("key", "")}
            for i in (body or {}).get("issues", [])
        ]

    async def create_issue(self, fields: dict) -> dict:
        body = await self._call("POST", "/rest/api/3/issue", "Creating the issue", json={"fields": fields})
        return {"id": str(body["id"]), "key": body["key"], "url": self.issue_url(body["key"])}

    async def link_types(self) -> list[str]:
        body = await self._call("GET", "/rest/api/3/issueLinkType", "Reading link types")
        return [t["name"] for t in (body or {}).get("issueLinkTypes", []) if t.get("name")]

    async def link(self, type_name: str, inward: str, outward: str) -> None:
        await self._call(
            "POST", "/rest/api/3/issueLink", "Linking issues",
            json={"type": {"name": type_name}, "inwardIssue": {"key": inward},
                  "outwardIssue": {"key": outward}},
        )

    async def _link_on(self, source: str, target: str, type_name: str) -> dict | None:
        body = await self._call("GET", f"/rest/api/3/issue/{quote(source)}", "Reading links",
                                params={"fields": "issuelinks"})
        for link in ((body or {}).get("fields") or {}).get("issuelinks") or []:
            ends = {(link.get("inwardIssue") or {}).get("key"), (link.get("outwardIssue") or {}).get("key")}
            if (link.get("type") or {}).get("name") == type_name and target in ends:
                return link
        return None

    async def link_outward(self, type_name: str, source: str, target: str) -> None:
        """Make `source` show the type's outward label towards `target` ("ENT-9 tests ENT-1").

        Atlassian's docs say the inward/outward field names carry no reliable direction at the API
        level, so the link is read back from `source`: an entry naming `target` as its
        outwardIssue is displayed with the outward label. A reversed link is removed and made again
        the other way round, rather than left pointing backwards.
        """
        for inward, outward in ((source, target), (target, source)):
            await self.link(type_name, inward, outward)
            made = await self._link_on(source, target, type_name)
            if made and (made.get("outwardIssue") or {}).get("key") == target:
                return
            if made and made.get("id"):
                await self._call("DELETE", f"/rest/api/3/issueLink/{quote(str(made['id']))}",
                                 "Removing a reversed link")
        raise AtlassianError(
            f"Linking failed: Jira didn't record {source} → {target} in the expected direction")


def adf(*paragraphs: str | tuple[str, str]) -> dict:
    """A Jira description. Each paragraph is text, or (text, url) for a link."""
    content = []
    for p in paragraphs:
        if isinstance(p, tuple):
            text, url = p
            node = {"type": "text", "text": text, "marks": [{"type": "link", "attrs": {"href": url}}]}
        else:
            node = {"type": "text", "text": p}
        if node["text"]:
            content.append({"type": "paragraph", "content": [node]})
    return {"type": "doc", "version": 1, "content": content}
