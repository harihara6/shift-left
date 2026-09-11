"""Xray Cloud over its GraphQL API: tests drafted from acceptance criteria, and their test plan.

Rovo MCP has no Xray tools, and unvetted community Xray servers are out (proposal s6), so this is
the documented API: a token from `POST /api/v2/authenticate` with the client id and secret, then
`createTest` and `createTestPlan` on `/api/v2/graphql`. The Jira fields travel as a GraphQL
variable, never spliced into the query text, so a PRD sentence can't change the mutation.
"""

from dataclasses import dataclass

import httpx

from app.connectors import http
from app.core.config import get_settings

CREATE_TEST = """
mutation CreateTest($jira: JSON!) {
  createTest(testType: { name: "Manual" }, jira: $jira) {
    test { issueId jira(fields: ["key"]) }
    warnings
  }
}"""

CREATE_TEST_PLAN = """
mutation CreateTestPlan($jira: JSON!, $tests: [String]) {
  createTestPlan(testIssueIds: $tests, jira: $jira) {
    testPlan { issueId jira(fields: ["key"]) }
    warnings
  }
}"""


class XrayError(RuntimeError):
    """Xray refused or couldn't be reached. Safe to show; never carries a credential."""


@dataclass
class Created:
    issue_id: str
    key: str
    warnings: list[str]


class XrayCloud:
    def __init__(self) -> None:
        settings = get_settings()
        self.base = settings.xray_base_url.rstrip("/")
        self._client_id = settings.xray_client_id
        self._secret = settings.xray_client_secret
        self._token: str | None = None

    @property
    def available(self) -> bool:
        return bool(self._client_id and self._secret)

    @property
    def unavailable_reason(self) -> str:
        return "" if self.available else (
            "No Xray API key is configured (SHIFTLEFT_XRAY_CLIENT_ID, SHIFTLEFT_XRAY_CLIENT_SECRET)."
        )

    async def _authenticate(self, c: httpx.AsyncClient) -> str:
        if self._token:
            return self._token
        response = await c.post(f"{self.base}/api/v2/authenticate", json={
            "client_id": self._client_id,
            "client_secret": self._secret.get_secret_value() if self._secret else "",
        })
        if response.status_code >= 400:
            raise XrayError(f"Xray refused the API key (HTTP {response.status_code})")
        # The token arrives as a JSON string.
        self._token = str(response.json())
        return self._token

    async def _mutate(self, query: str, variables: dict, field: str, node: str) -> Created:
        if not self.available:
            raise XrayError(self.unavailable_reason)
        try:
            async with http.client(timeout=30.0) as c:
                token = await self._authenticate(c)
                response = await c.post(
                    f"{self.base}/api/v2/graphql", json={"query": query, "variables": variables},
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise XrayError(f"Couldn't reach Xray ({type(exc).__name__})") from exc
        if response.status_code >= 400:
            raise XrayError(f"Xray refused the request (HTTP {response.status_code})")
        body = response.json()
        if body.get("errors"):
            raise XrayError("Xray refused: " + "; ".join(str(e.get("message", e)) for e in body["errors"]))
        result = (body.get("data") or {}).get(field) or {}
        item = result.get(node) or {}
        jira = item.get("jira") or {}
        if not item.get("issueId"):
            raise XrayError("Xray answered without creating anything")
        warnings = [str(w) for w in result.get("warnings") or []]
        return Created(str(item["issueId"]), str(jira.get("key", "")), warnings)

    async def create_test(self, project: str, summary: str, labels: list[str]) -> Created:
        jira = {"fields": {"summary": summary, "project": {"key": project}, "labels": labels}}
        return await self._mutate(CREATE_TEST, {"jira": jira}, "createTest", "test")

    async def create_test_plan(
        self, project: str, summary: str, labels: list[str], tests: list[str]
    ) -> Created:
        jira = {"fields": {"summary": summary, "project": {"key": project}, "labels": labels}}
        variables = {"jira": jira, "tests": tests}
        return await self._mutate(CREATE_TEST_PLAN, variables, "createTestPlan", "testPlan")
