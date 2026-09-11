"""Discovery through the Atlassian Rovo MCP Server.

One central endpoint (`https://mcp.atlassian.com/v2/mcp`) speaking JSON-RPC over Streamable
HTTP, not something hosted on our own Confluence site — the site URL is an *input*, resolved
to a `cloudId` that every tool call carries.

Two deliberate boundaries:

* **Discovery and single-page reads only.** MCP is interactive, per-user and rate-limited;
  ingestion stays on the REST connectors, which authenticate as the service and can be paced.
  Nothing here is on the `sync()` path, and nothing here writes. Feature Kickoff reads a PRD
  through `read_page` when there is no REST credential for the site.
* **The caller's own permissions.** Rovo MCP authenticates the person, not the org, so a
  discovery result never shows a Jira project the person running onboarding cannot already
  open. That matches how every other read in this service is scoped.

If it is not configured — Data Center rather than Cloud, MCP not enabled by the org admin, no
token — `available()` is False and onboarding falls back to the connectors, and then to setting
the project up by hand. Being unavailable is an expected state, not an error.
"""

import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx

from app.connectors.discovery import Candidate, terms
from app.core.config import get_settings

logger = logging.getLogger("shiftleft.rovo")

# Verified tool names on the Rovo MCP server. Do not guess at others — an unknown tool name is
# a runtime error against a remote we do not control.
TOOL_ACCESSIBLE_RESOURCES = "getAccessibleAtlassianResources"
TOOL_JIRA_PROJECTS = "getVisibleJiraProjects"
TOOL_CONFLUENCE_SEARCH = "searchConfluenceUsingCql"
TOOL_CONFLUENCE_PAGE = "getConfluencePage"

PROTOCOL_VERSION = "2025-06-18"


class RovoUnavailable(RuntimeError):
    """Raised internally when the server cannot be reached. Never surfaced as a 500."""


class RovoMcpSource:
    """A discovery source backed by Rovo MCP. Read-only, and optional by design."""

    def __init__(self, token: str | None = None) -> None:
        settings = get_settings()
        self.url = settings.atlassian_mcp_url
        self.site_url = settings.atlassian_site_url
        # In production this is a per-user OAuth 2.1 access token obtained through the
        # authorization-code flow and held in the vault; the env var is the local-dev path.
        # Whatever its origin, the value is never logged, returned or persisted.
        self._token = token or settings.atlassian_mcp_token
        self._cloud_id: str | None = None

    @property
    def available(self) -> bool:
        return bool(self._token and self.site_url)

    @property
    def unavailable_reason(self) -> str:
        if not self.site_url:
            return (
                "No Atlassian site is configured. Rovo MCP is Cloud-only — on Data Center there "
                "is no MCP path at all."
            )
        if not self._token:
            return (
                "No Rovo MCP authorization. An org admin enables the Rovo MCP Server and the "
                "person running onboarding authorizes it; until then, discovery is unavailable."
            )
        return ""

    # -- transport ---------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            # Streamable HTTP may answer either way; both have to be acceptable.
            "Accept": "application/json, text/event-stream",
        }

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        """A Streamable HTTP reply is either a JSON body or an SSE stream carrying one."""
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:].strip())
            raise RovoUnavailable("Empty event stream from the MCP server")
        return response.json()

    async def _call_tool(self, client: httpx.AsyncClient, name: str, arguments: dict) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = await client.post(self.url, json=payload, headers=self._headers())
        if response.status_code == 401:
            raise RovoUnavailable("Rovo MCP rejected the authorization — the token needs renewing")
        if response.status_code == 403:
            raise RovoUnavailable("This Atlassian account is not permitted to use the Rovo MCP Server")
        response.raise_for_status()
        body = self._parse(response)
        if "error" in body:
            raise RovoUnavailable(str(body["error"].get("message", "MCP call failed")))
        content = body.get("result", {}).get("content", [])
        for block in content:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except json.JSONDecodeError:
                    return block["text"]
        return None

    async def _resolve_cloud_id(self, client: httpx.AsyncClient) -> str:
        """The site hostname is accepted directly; the resource list is the fallback."""
        if self._cloud_id:
            return self._cloud_id
        host = urlparse(self.site_url).netloc or self.site_url
        try:
            resources = await self._call_tool(client, TOOL_ACCESSIBLE_RESOURCES, {})
            for resource in resources or []:
                if host in (resource.get("url", ""), resource.get("name", "")):
                    self._cloud_id = resource["id"]
                    return self._cloud_id
        except (RovoUnavailable, httpx.HTTPError, KeyError, TypeError):
            pass
        # Tools resolve a bare hostname themselves, so this is a working last resort.
        self._cloud_id = host
        return self._cloud_id

    # -- discovery ---------------------------------------------------------------------

    async def search_entities(self, hint: str, limit: int = 10) -> list[Candidate]:
        """Jira projects and Confluence roots matching `hint`, as the caller can see them."""
        if not self.available:
            return []
        matched = tuple(terms(hint))
        found: list[Candidate] = []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                cloud_id = await self._resolve_cloud_id(client)
                found += await self._jira_projects(client, cloud_id, hint, matched, limit)
                found += await self._confluence_roots(client, cloud_id, hint, matched, limit)
        except (RovoUnavailable, httpx.HTTPError) as exc:
            # A source that cannot answer contributes nothing. It must never turn into a
            # half-filled proposal that looks discovered.
            logger.warning("Rovo MCP discovery unavailable: %s", exc)
            return []
        return found

    async def _jira_projects(
        self, client: httpx.AsyncClient, cloud_id: str, hint: str, matched: tuple[str, ...], limit: int
    ) -> list[Candidate]:
        result = await self._call_tool(
            client, TOOL_JIRA_PROJECTS, {"cloudId": cloud_id, "searchString": hint, "limit": limit}
        )
        base = self.site_url.rstrip("/")
        out = []
        for project in _rows(result):
            key = project.get("key")
            if not key:
                continue
            out.append(
                Candidate(
                    connector_key="jira", slot="jira_project", ref=key,
                    title=project.get("name", key), url=f"{base}/browse/{key}",
                    detail={"lead": _lead(project), "id": project.get("id", "")},
                    matched_on=matched,
                )
            )
        return out

    async def _confluence_roots(
        self, client: httpx.AsyncClient, cloud_id: str, hint: str, matched: tuple[str, ...], limit: int
    ) -> list[Candidate]:
        # Only pages already tagged with the sl-* convention are candidates for the artifact
        # root — an untagged page tree is not evidence of anything.
        cql = f'label in (sl-requirements, sl-hld, sl-lld, sl-testplan) and text ~ "{_escape(hint)}"'
        result = await self._call_tool(
            client, TOOL_CONFLUENCE_SEARCH, {"cloudId": cloud_id, "cql": cql, "limit": limit}
        )
        base = self.site_url.rstrip("/")
        out = []
        for page in _rows(result):
            page_id = str(page.get("id", ""))
            if not page_id:
                continue
            out.append(
                Candidate(
                    connector_key="confluence", slot="confluence_root", ref=page_id,
                    title=page.get("title", page_id),
                    url=f"{base}/wiki/pages/viewpage.action?pageId={page_id}",
                    # Presence and title only. Page bodies stay in Confluence — a threat model
                    # or security page must never have its content copied into this service.
                    detail={"space": _space(page)},
                    matched_on=matched,
                )
            )
        return out


    # -- reading one page (Feature Kickoff's fallback when there is no REST credential) -------

    async def read_page(self, page_id: str) -> dict[str, Any]:
        """A page's title and body, as the caller can see it. Raises RovoUnavailable.

        Reading is safe over MCP; it is edits that round-trip through Markdown and lose tables
        and macros, which is why nothing here writes.
        """
        if not self.available:
            raise RovoUnavailable(self.unavailable_reason)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                cloud_id = await self._resolve_cloud_id(client)
                result = await self._call_tool(
                    client, TOOL_CONFLUENCE_PAGE, {"cloudId": cloud_id, "pageId": page_id}
                )
        except httpx.HTTPError as exc:
            raise RovoUnavailable(f"couldn't reach the MCP server ({type(exc).__name__})") from exc
        if isinstance(result, str):
            return {"page_id": page_id, "title": "", "space": "", "version": 0, "body": result}
        if not isinstance(result, dict):
            raise RovoUnavailable("the MCP server returned no page")
        body = result.get("body")
        if isinstance(body, dict):
            body = (body.get("storage") or {}).get("value") or body.get("value") or ""
        version = result.get("version")
        number = version.get("number") if isinstance(version, dict) else version
        return {
            "page_id": str(result.get("id") or page_id), "title": str(result.get("title") or ""),
            "space": _space(result) or str(result.get("spaceKey") or ""),
            "version": int(number or 0),
            "body": str(body or result.get("content") or result.get("markdown") or ""),
        }


def _rows(result: Any) -> list[dict]:
    """MCP tools answer with a list, or an envelope around one. Anything else is no rows."""
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        for key in ("values", "results", "projects", "data"):
            if isinstance(result.get(key), list):
                return [r for r in result[key] if isinstance(r, dict)]
    return []


def _lead(project: dict) -> str:
    lead = project.get("lead")
    return lead.get("displayName", "") if isinstance(lead, dict) else str(lead or "")


def _space(page: dict) -> str:
    space = page.get("space")
    return space.get("key", "") if isinstance(space, dict) else str(space or "")


def _escape(hint: str) -> str:
    return hint.replace('"', "").replace("\\", "")
