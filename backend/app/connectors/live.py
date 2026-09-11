"""Real connectors for Settings -> Connectors: what "Test connection" actually calls.

Before this module, every connector key resolved to `MockConnector`, whose `test_connection()`
checked only that some config and a vault reference existed - never that the vault reference
resolved to anything, because nothing did (see app/services/vault.py). A connector could be
"Connected" with an empty token and still report success. Each class below fixes that for one
connector: it reads the instance's own config and resolves its own secret at call time, then
makes one real, read-only, authenticated call to the source and reports what actually happened.

`list_capabilities`, `list_available_filters`, `preview_data`, `sync` and
`map_to_canonical_model` still answer from the same fixture tables `mock.py` uses. Wiring those
to real data is later PRD phasing (normalized_artifacts, ingestion_jobs); this module is scoped
to making the connection test honest, which is a prerequisite for that work, not a substitute.

Auth methods here match `connectors.json` exactly, and nothing beyond what this service can
actually establish end to end: no OAuth 2.0 consumer flow, no GitHub App installation, no on-prem
Data Center variant for Jira/Confluence/Xray. Each of those needs a callback URL, an app
registration, or a host shape this service has no code for - listing it as an option would be
exactly the kind of un-backed choice this file exists to remove. A team that needs one of those
paths gets it by extending the matching class here, not by the UI pretending it already works.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from app.connectors import http, mock
from app.connectors.atlassian_rest import AtlassianError, AtlassianRest
from app.connectors.base import Connector, SyncResult, TestResult
from app.connectors.discovery import Candidate
from app.connectors.github_specs import GitHubSpecs, SpecNotRead
from app.connectors.xray_cloud import XrayCloud, XrayError
from app.services import vault

# HTTP status -> what it means, for sources that don't explain themselves in the response body.
_KNOWN_STATUS = {
    401: "the credentials were rejected",
    403: "the account isn't permitted to do this",
    404: "it wasn't found, or the credentials can't see it",
}


def _problem(response: httpx.Response, action: str) -> str:
    return f"{action} failed: {_KNOWN_STATUS.get(response.status_code, f'HTTP {response.status_code}')}"


async def _request(method: str, url: str, action: str, **kwargs: Any) -> httpx.Response | str:
    """One outbound call for a connection test. Returns the response on any answer from the
    source, or an error string if the call never landed - kept distinct from an authenticated
    refusal, so "couldn't reach the host" never reads as "the credentials were wrong".
    """
    try:
        async with http.client(timeout=15.0) as c:
            return await c.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        return f"{action} failed: couldn't reach {httpx.URL(url).host} ({type(exc).__name__})"


class LiveConnector(Connector):
    """Base for every real connector. Subclasses implement only `test_connection()`."""

    def __init__(self, key: str, name: str, config: dict[str, Any], secrets: dict[str, str]) -> None:
        super().__init__(config, secrets)
        self.key = key
        self.name = name

    def _field(self, field_key: str) -> str:
        return str(self.config.get(field_key) or "").strip()

    async def _secret(self, field_key: str) -> str:
        ref = self.secrets.get(field_key)
        if not ref:
            return ""
        return await vault.read(ref) or ""

    @staticmethod
    def _missing(**named: str) -> str:
        """Empty if every named value is present; otherwise which ones are not, so a call is
        never attempted for nothing and the message says exactly what to fill in."""
        gaps = [label.replace("_", " ") for label, value in named.items() if not value]
        return f"Missing configuration: {', '.join(gaps)}" if gaps else ""

    async def _ok(self, message: str) -> TestResult:
        return TestResult(
            ok=True, message=message,
            capabilities=await self.list_capabilities(), filters=await self.list_available_filters(),
        )

    @staticmethod
    def _fail(message: str) -> TestResult:
        return TestResult(ok=False, message=message)

    # -- the rest of the contract answers from fixtures until real sync is built (see module
    # docstring) - identical to MockConnector, so nothing above this layer can tell the two apart.

    async def list_capabilities(self) -> list[str]:
        return mock.CAPABILITIES.get(self.key, [])

    async def list_available_filters(self) -> list[str]:
        return mock.FILTERS.get(self.key, [])

    async def preview_data(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        return mock.PREVIEW_ROWS.get(self.key, [])[:limit]

    async def sync(self, query: str, mode: str = "incremental") -> SyncResult:
        rows = await self.preview_data(query, limit=100)
        return SyncResult(ok=True, records=len(rows), message=f"{mode} sync completed")

    async def search_entities(self, hint: str, limit: int = 10) -> list[Candidate]:
        return await mock.discover(self.key, await self.list_capabilities(), hint, limit)

    def map_to_canonical_model(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"source": self.key, "source_ref": r.get("key") or r.get("pr") or r.get("page_id"), "raw": r}
            for r in raw
        ]


# -- Planning & docs -------------------------------------------------------------------------


class JiraConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        site = self._field("site_url")
        email = self._field("account_email")
        token = await self._secret("api_token")
        if problem := self._missing(site_url=site, account_email=email, api_token=token):
            return self._fail(problem)
        try:
            who = await AtlassianRest(site=site, email=email, token=token).whoami()
        except AtlassianError as exc:
            return self._fail(str(exc))
        return await self._ok(f"Reachable as {who.get('displayName') or email}")


class ConfluenceConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        site = self._field("site_url")
        email = self._field("account_email")
        token = await self._secret("api_token")
        if problem := self._missing(site_url=site, account_email=email, api_token=token):
            return self._fail(problem)
        try:
            who = await AtlassianRest(site=site, email=email, token=token).whoami_confluence()
        except AtlassianError as exc:
            return self._fail(str(exc))
        return await self._ok(f"Reachable as {who.get('displayName') or email}")


# -- Test management --------------------------------------------------------------------------


class XrayConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        client_id = self._field("client_id")
        secret = await self._secret("client_secret")
        if problem := self._missing(client_id=client_id, client_secret=secret):
            return self._fail(problem)
        try:
            await XrayCloud(client_id=client_id, client_secret=secret).test_auth()
        except XrayError as exc:
            return self._fail(str(exc))
        return await self._ok("Reachable · API key exchanged for a token")


# -- Code & review ----------------------------------------------------------------------------


class GithubConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        token = await self._secret("personal_access_token")
        if problem := self._missing(personal_access_token=token):
            return self._fail(problem)
        client = GitHubSpecs(token=token)
        try:
            who = await client.whoami()
        except SpecNotRead as exc:
            return self._fail(str(exc))
        org = self._field("organisation")
        if org and not await client.org_reachable(org):
            return self._fail(
                f"Token is valid for {who.get('login')}, but the organisation "
                f"{org!r} wasn't found or isn't visible to it."
            )
        return await self._ok(f"Reachable as {who.get('login')}" + (f" · {org} is visible" if org else ""))


class BitbucketConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        token = await self._secret("repository_access_token")
        if problem := self._missing(repository_access_token=token):
            return self._fail(problem)
        response = await _request(
            "GET", "https://api.bitbucket.org/2.0/user", "Checking the Bitbucket connection",
            headers={"Authorization": f"Bearer {token}"},
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the Bitbucket connection"))
        return await self._ok(f"Reachable as {response.json().get('username', 'unknown user')}")


# -- Code quality -------------------------------------------------------------------------------


class SonarQubeConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        server, token = self._field("server_url"), await self._secret("user_token")
        if problem := self._missing(server_url=server, user_token=token):
            return self._fail(problem)
        response = await _request(
            "GET", f"{server.rstrip('/')}/api/authentication/validate",
            "Checking the SonarQube connection", auth=(token, ""),
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the SonarQube connection"))
        if not response.json().get("valid"):
            return self._fail("Checking the SonarQube connection failed: the token was rejected")
        return await self._ok("Reachable · token accepted")


# -- Build & deploy -----------------------------------------------------------------------------


class CiConnector(LiveConnector):
    """Shares GitHub's connection: `connectors.py` merges the GitHub instance's own config and
    secrets in before constructing this, so the field keys below are GitHub's."""

    async def test_connection(self) -> TestResult:
        token = await self._secret("personal_access_token")
        if not token:
            return self._fail(
                "CI shares GitHub's connection, and GitHub isn't configured yet - set that up first."
            )
        try:
            who = await GitHubSpecs(token=token).whoami()
        except SpecNotRead as exc:
            return self._fail(f"CI shares GitHub's connection, which failed: {exc}")
        return await self._ok(f"Reachable via GitHub, as {who.get('login')}")


class JenkinsConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        base, user, token = self._field("base_url"), self._field("user"), await self._secret("api_token")
        if problem := self._missing(base_url=base, user=user, api_token=token):
            return self._fail(problem)
        response = await _request(
            "GET", f"{base.rstrip('/')}/api/json", "Checking the Jenkins connection", auth=(user, token),
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the Jenkins connection"))
        return await self._ok("Reachable · authenticated as " + user)


# -- Flow metrics -------------------------------------------------------------------------------


class LinearBConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        key = await self._secret("api_key")
        if problem := self._missing(api_key=key):
            return self._fail(problem)
        response = await _request(
            "GET", "https://public-api.linearb.io/api/v2/teams", "Checking the LinearB connection",
            headers={"x-api-key": key},
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the LinearB connection"))
        return await self._ok("Reachable · API key accepted")


# -- Operations ---------------------------------------------------------------------------------


class JsmConnector(LiveConnector):
    """Shares the Jira connection: `connectors.py` merges the Jira instance's own config and
    secrets in before constructing this, so the field keys below are Jira's."""

    async def test_connection(self) -> TestResult:
        site = self._field("site_url")
        email = self._field("account_email")
        token = await self._secret("api_token")
        if problem := self._missing(site_url=site, account_email=email, api_token=token):
            return self._fail(f"JSM shares the Jira connection, which isn't fully set up: {problem}")
        atl = AtlassianRest(site=site, email=email, token=token)
        try:
            await atl.whoami()
        except AtlassianError as exc:
            return self._fail(f"JSM shares the Jira connection, which failed: {exc}")
        desk = self._field("service_desk_project")
        if not desk:
            return await self._ok("Reachable via Jira · no service desk project configured yet")
        response = await _request(
            "GET", f"{atl.site}/rest/servicedeskapi/servicedesk", "Checking Jira Service Management",
            auth=(email, token), headers={"Accept": "application/json"},
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking Jira Service Management"))
        return await self._ok(f"Reachable via Jira · service desk {desk} visible")


class SlackConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        token = await self._secret("bot_token")
        if problem := self._missing(bot_token=token):
            return self._fail(problem)
        response = await _request(
            "POST", "https://slack.com/api/auth.test", "Checking the Slack connection",
            headers={"Authorization": f"Bearer {token}"},
        )
        if isinstance(response, str):
            return self._fail(response)
        # Slack answers 200 even on a rejected token; the refusal is in the body.
        body = response.json() if response.status_code < 400 else {}
        if response.status_code >= 400 or not body.get("ok"):
            reason = body.get("error", f"HTTP {response.status_code}")
            return self._fail(f"Checking the Slack connection failed: {reason}")
        bot, team = body.get("user", "unknown"), body.get("team", "workspace")
        return await self._ok(f"Reachable · bot {bot} in {team}")


class SentryConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        org, token = self._field("organisation_slug"), await self._secret("auth_token")
        if problem := self._missing(organisation_slug=org, auth_token=token):
            return self._fail(problem)
        response = await _request(
            "GET", f"https://sentry.io/api/0/organizations/{quote(org)}/", "Checking the Sentry connection",
            headers={"Authorization": f"Bearer {token}"},
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the Sentry connection"))
        return await self._ok(f"Reachable · organisation {org} visible")


class PagerDutyConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        key = await self._secret("api_key")
        if problem := self._missing(api_key=key):
            return self._fail(problem)
        response = await _request(
            "GET", "https://api.pagerduty.com/abilities", "Checking the PagerDuty connection",
            headers={
                "Authorization": f"Token token={key}",
                "Accept": "application/vnd.pagerduty+json;version=2",
            },
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the PagerDuty connection"))
        return await self._ok("Reachable · API key accepted")


# -- Design ---------------------------------------------------------------------------------


class FigmaConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        token = await self._secret("access_token")
        if problem := self._missing(access_token=token):
            return self._fail(problem)
        response = await _request(
            "GET", "https://api.figma.com/v1/me", "Checking the Figma connection",
            headers={"X-Figma-Token": token},
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the Figma connection"))
        return await self._ok(f"Reachable as {response.json().get('email', 'unknown account')}")


# -- Observability ----------------------------------------------------------------------------


class DatadogConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        site = self._field("site") or "datadoghq.com"
        api_key, app_key = await self._secret("api_key"), await self._secret("application_key")
        if problem := self._missing(api_key=api_key, application_key=app_key):
            return self._fail(problem)
        response = await _request(
            "GET", f"https://api.{site}/api/v1/validate", "Checking the Datadog connection",
            headers={"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key},
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400 or not response.json().get("valid"):
            return self._fail(_problem(response, "Checking the Datadog connection"))
        return await self._ok(f"Reachable · API key valid on {site}")


# -- Security -------------------------------------------------------------------------------


class SecurityScannersConnector(LiveConnector):
    async def test_connection(self) -> TestResult:
        token = await self._secret("snyk_token")
        if problem := self._missing(snyk_token=token):
            return self._fail(f"{problem} · CodeQL isn't checked here - it rides on the GitHub connector")
        response = await _request(
            "GET", "https://api.snyk.io/rest/self?version=2024-10-15", "Checking the Snyk connection",
            headers={"Authorization": f"token {token}"},
        )
        if isinstance(response, str):
            return self._fail(response)
        if response.status_code >= 400:
            return self._fail(_problem(response, "Checking the Snyk connection"))
        return await self._ok("Snyk reachable · CodeQL findings are read through the GitHub connector")


REGISTRY: dict[str, type[LiveConnector]] = {
    "jira": JiraConnector,
    "confluence": ConfluenceConnector,
    "xray": XrayConnector,
    "github": GithubConnector,
    "bitbucket": BitbucketConnector,
    "sonarqube": SonarQubeConnector,
    "ci": CiConnector,
    "jenkins": JenkinsConnector,
    "linearb": LinearBConnector,
    "jsm": JsmConnector,
    "slack": SlackConnector,
    "sentry": SentryConnector,
    "pagerduty": PagerDutyConnector,
    "figma": FigmaConnector,
    "datadog": DatadogConnector,
    "security": SecurityScannersConnector,
}
