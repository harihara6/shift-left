"""Reading a service's API spec from GitHub, pinned to the commit it was read at.

The ref (default branch unless the catalog names one) is resolved to a commit SHA first, and the
file is read at that SHA. Every finding links to the file at that commit, so it stays true to what
was read even after the branch moves on. The token is read at call time and never logged.
"""

from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from app.connectors import http, openapi
from app.core.config import get_settings


class SpecNotRead(RuntimeError):
    """Why a spec couldn't be read. Its check reads as not checked, never as passed."""


@dataclass
class SpecRead:
    repo: str
    path: str
    commit: str
    url: str
    operations: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)


class GitHubSpecs:
    def __init__(self, *, token: str | None = None, api_url: str | None = None) -> None:
        """Defaults to the service-wide settings (Feature Kickoff's path); pass `token` to act
        with one connector instance's own PAT instead (Settings -> Connectors)."""
        settings = get_settings()
        self.api = (api_url if api_url is not None else settings.github_api_url).rstrip("/")
        if token is not None:
            self._token = token
        else:
            self._token = settings.github_token.get_secret_value() if settings.github_token else None

    @property
    def available(self) -> bool:
        return bool(self._token)

    @property
    def unavailable_reason(self) -> str:
        return "" if self._token else "No GitHub token is configured (SHIFTLEFT_GITHUB_TOKEN)."

    def _web(self) -> str:
        """github.com for the public API; the Enterprise host's own web root otherwise."""
        if self.api == "https://api.github.com":
            return "https://github.com"
        return self.api.removesuffix("/api/v3")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def whoami(self) -> dict:
        """Settings -> Connectors' "Test connection" for GitHub: confirms the PAT itself works,
        independent of any particular repo."""
        if not self._token:
            raise SpecNotRead(self.unavailable_reason)
        try:
            async with http.client() as c:
                response = await c.get(f"{self.api}/user", headers={
                    **self._headers(), "Accept": "application/vnd.github+json",
                })
        except httpx.HTTPError as exc:
            raise SpecNotRead(f"Couldn't reach GitHub ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise SpecNotRead(_why(response, "the authenticated account"))
        return response.json()

    async def org_reachable(self, org: str) -> bool:
        """Whether `org` exists and is visible at all - a public read, so a real "no such org"
        is distinguishable from a token that merely lacks membership."""
        async with http.client() as c:
            response = await c.get(f"{self.api}/orgs/{quote(org)}", headers=self._headers())
        return response.status_code < 400

    async def read(self, repo: str, path: str, ref: str = "HEAD") -> SpecRead:
        if not self._token:
            raise SpecNotRead(self.unavailable_reason)
        headers = self._headers()
        try:
            async with http.client() as c:
                sha = await c.get(f"{self.api}/repos/{repo}/commits/{quote(ref)}",
                                  headers={**headers, "Accept": "application/vnd.github.sha"})
                if sha.status_code >= 400:
                    raise SpecNotRead(_why(sha, f"{repo} at {ref}"))
                commit = sha.text.strip()
                raw = await c.get(f"{self.api}/repos/{repo}/contents/{quote(path)}",
                                  params={"ref": commit},
                                  headers={**headers, "Accept": "application/vnd.github.raw+json"})
                if raw.status_code >= 400:
                    raise SpecNotRead(_why(raw, f"{path} in {repo}"))
        except httpx.HTTPError as exc:
            raise SpecNotRead(f"Couldn't reach GitHub ({type(exc).__name__})") from exc
        try:
            spec = openapi.parse(raw.text)
        except openapi.SpecUnreadable as exc:
            raise SpecNotRead(f"{path} in {repo} isn't a readable OpenAPI document: {exc}") from exc
        return SpecRead(repo, path, commit[:12], f"{self._web()}/{repo}/blob/{commit}/{path}",
                        spec.operations, spec.deprecated)


def _why(response: httpx.Response, what: str) -> str:
    if response.status_code == 404:
        return f"{what} wasn't found, or the token can't see it"
    if response.status_code in (401, 403):
        return f"GitHub refused access to {what} (HTTP {response.status_code})"
    return f"GitHub couldn't return {what} (HTTP {response.status_code})"
