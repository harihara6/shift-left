"""Feature Kickoff: seven steps from a PRD to an ordered Jira backlog, against fake live systems.

A fake Confluence, GitHub, Jira and docs host answer the documented REST shapes, so these tests pin
down what the readers send and what they do with the answers. No example data is involved anywhere:
without a connection, a step says how to connect.
"""

import json
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

ENT = "/api/projects/entitlements"
PAY = "/api/projects/db-payments"
SITE = "https://example.atlassian.net"
PAGE_ID = "9100001"
PAGE_URL = f"{SITE}/wiki/spaces/ENT/pages/{PAGE_ID}/Instant+account+aggregation"
DEP_PAGE_ID = "9100777"
DEP_PAGE_URL = f"{SITE}/wiki/spaces/PLT/pages/{DEP_PAGE_ID}/Accounts+service+contract"
TOKEN = "atl-token-never-shown"
GH_TOKEN = "gh-token-never-shown"

ENV = {
    "SHIFTLEFT_ATLASSIAN_SITE_URL": SITE,
    "SHIFTLEFT_ATLASSIAN_EMAIL": "kickoff-bot@backbase.com",
    "SHIFTLEFT_ATLASSIAN_API_TOKEN": TOKEN,
    "SHIFTLEFT_GITHUB_TOKEN": GH_TOKEN,
}

PRD_LINES = [
    "## Summary",
    "Customers in Germany and the Netherlands see their accounts at other banks next to their own, "
    "through open banking account information.",
    "## Requirements",
    "- Link an account at another bank through Salt Edge",
    "- Show balances and transactions for linked accounts",
    "- Let the customer remove a linked account at any time",
    "## Data",
    "The feature stores personal data: account holder name and IBAN.",
]

TDD_PAGE_ID = "9100888"
TDD_PAGE_URL = f"{SITE}/wiki/spaces/ENT/pages/{TDD_PAGE_ID}/Accounts+TDD"
# A design a team already owns: two sections this analysis touches, and one it must not.
TDD_STORAGE = (
    "<h1>Accounts TDD</h1><p>Owned by the accounts team.</p>"
    "<h2>High-level design</h2><p>The old high-level design.</p>"
    "<h2>Risks</h2><p>A risk nobody asked us to rewrite.</p>"
    "<h2>Monitoring and alerting</h2><p>Old monitoring.</p>"
)

DEP_PAGE_LINES = [
    "## What the accounts service guarantees",
    "- Balances are refreshed every four hours, not on demand",
    "- Removing a link is asynchronous and completes within a day",
]

SPEC = """
openapi: 3.0.3
info: {title: Accounts API, version: 2.1.0}
paths:
  /accounts: {get: {summary: List}}
  /accounts/{id}/balances: {get: {summary: Balances}}
  /accounts/{id}/legacy: {get: {summary: Old, deprecated: true}}
"""

DOC_SPEC = """
openapi: 3.0.3
info: {title: Digital Banking API, version: 5.0.0}
paths:
  /linked-accounts: {get: {summary: List}, post: {summary: Link}}
components:
  securitySchemes:
    oauth: {type: oauth2, flows: {authorizationCode: {}}}
"""


def storage_of(lines: list[str]) -> str:
    out, in_list = [], False
    for line in lines:
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li><p>{escape(line[2:])}</p></li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<h2>{escape(line[3:])}</h2>" if line.startswith("## ") else f"<p>{escape(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


class World:
    """One fake for every host Feature Kickoff calls."""

    def __init__(self) -> None:
        self.repos = {
            "acme/accounts-web": {
                "description": "The web app",
                "language": "TypeScript",
                "files": [
                    "package.json",
                    "src/app/accounts/accounts.component.ts",
                    "src/app/accounts/accounts.service.ts",
                    "node_modules/left-pad/index.js",
                ],
            },
            "acme/accounts-api": {
                "description": "The accounts service",
                "language": "Java",
                "files": [
                    "pom.xml",
                    "api/openapi.yaml",
                    "src/main/java/com/acme/accounts/AccountsController.java",
                ],
            },
        }
        self.required: list[dict] = []
        self.issues: list[dict] = []
        self.links: list[tuple[str, str]] = []
        self.created: list[dict] = []
        self.auth_seen: set[str] = set()
        self.pages = {TDD_PAGE_ID: TDD_STORAGE}
        self.page_version = 4
        self.version_messages: list[str] = []
        self.created_pages: list[dict] = []
        self.page_labels: list[dict] = []

    # -- the transport -----------------------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.auth_seen.add(request.headers.get("authorization", ""))
        host = request.url.host
        if host == "example.atlassian.net":
            return self.atlassian(request)
        if host == "api.github.com":
            return self.github(request)
        if host == "docs.example.com":
            return self.docs(request)
        return httpx.Response(404)

    def atlassian(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/wiki/api/v2/pages/{PAGE_ID}":
            return httpx.Response(
                200,
                json={
                    "id": PAGE_ID,
                    "title": "Instant account aggregation",
                    "spaceId": "77",
                    "version": {"number": 7, "createdAt": "2026-09-01T10:00:00Z"},
                    "body": {"storage": {"value": storage_of(PRD_LINES)}},
                    "_links": {"webui": f"/spaces/ENT/pages/{PAGE_ID}/Instant+account+aggregation"},
                },
            )
        if path.startswith("/wiki/api/v2/pages/") and path.rsplit("/", 1)[1] in self.pages:
            page_id = path.rsplit("/", 1)[1]
            if request.method == "PUT":
                body = json.loads(request.content)
                self.pages[page_id] = body["body"]["value"]
                self.page_version += 1
                self.version_messages.append(body["version"]["message"])
                return httpx.Response(200, json={"id": page_id})
            return httpx.Response(
                200,
                json={
                    "id": page_id,
                    "title": "Accounts TDD",
                    "spaceId": "77",
                    "version": {"number": self.page_version, "createdAt": "2026-09-02T10:00:00Z"},
                    "body": {"storage": {"value": self.pages[page_id]}},
                    "_links": {"webui": f"/spaces/ENT/pages/{page_id}/Accounts+TDD"},
                },
            )
        if path == "/wiki/api/v2/pages" and request.method == "POST":
            body = json.loads(request.content)
            self.created_pages.append(body)
            return httpx.Response(
                200, json={"id": "9200000", "_links": {"webui": "/spaces/ENT/pages/9200000/New"}}
            )
        if path == "/wiki/api/v2/pages":
            return httpx.Response(200, json={"results": []})
        if path.startswith("/wiki/rest/api/content/") and path.endswith("/label"):
            self.page_labels += json.loads(request.content)
            return httpx.Response(200, json={})
        if path == f"/wiki/api/v2/pages/{DEP_PAGE_ID}":
            return httpx.Response(
                200,
                json={
                    "id": DEP_PAGE_ID,
                    "title": "Accounts service contract",
                    "spaceId": "77",
                    "version": {"number": 3, "createdAt": "2026-08-20T10:00:00Z"},
                    "body": {"storage": {"value": storage_of(DEP_PAGE_LINES)}},
                    "_links": {"webui": f"/spaces/PLT/pages/{DEP_PAGE_ID}/Accounts+service+contract"},
                },
            )
        if path.startswith("/wiki/api/v2/pages/"):
            return httpx.Response(404, json={"message": "Not found"})
        if path == "/wiki/api/v2/spaces/77":
            return httpx.Response(200, json={"key": "ENT"})
        if path == "/wiki/api/v2/spaces":
            return httpx.Response(200, json={"results": [{"id": "77", "key": "ENT"}]})
        if path == "/rest/api/3/issue/createmeta/ENT/issuetypes":
            return httpx.Response(
                200,
                json={
                    "issueTypes": [
                        {"id": "10", "name": "Epic"},
                        {"id": "11", "name": "Story"},
                        {"id": "12", "name": "Task"},
                    ]
                },
            )
        if path.startswith("/rest/api/3/issue/createmeta/ENT/issuetypes/"):
            return httpx.Response(200, json={"fields": self.required})
        if path.startswith("/rest/api/3/issue/createmeta/"):
            return httpx.Response(404, json={"errorMessages": ["No project"]})
        if path == "/rest/api/3/project/ENT/components":
            return httpx.Response(200, json=[{"id": "1", "name": "Accounts"}, {"id": "2", "name": "Web"}])
        if path == "/rest/api/3/project/ENT/versions":
            return httpx.Response(
                200,
                json=[
                    {"id": "9", "name": "2026.2", "released": True, "archived": False},
                    {"id": "10", "name": "2026.4", "released": False, "archived": False},
                    {"id": "11", "name": "old", "released": True, "archived": True},
                ],
            )
        if path == "/rest/api/3/priority":
            return httpx.Response(200, json=[{"id": "1", "name": "High"}, {"id": "3", "name": "Medium"}])
        if path == "/rest/api/3/search/jql":
            jql = parse_qs(urlparse(str(request.url)).query)["jql"][0]
            label = jql.split('labels = "')[1].rstrip('"')
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "id": i["id"],
                            "key": i["key"],
                            "fields": {"summary": i["fields"]["summary"], "project": {"key": "ENT"}},
                        }
                        for i in self.issues
                        if label in i["fields"].get("labels", [])
                    ]
                },
            )
        if path == "/rest/api/3/issue" and request.method == "POST":
            fields = json.loads(request.content)["fields"]
            key = f"ENT-{len(self.issues) + 1}"
            issue = {"id": str(100 + len(self.issues)), "key": key, "fields": fields}
            self.issues.append(issue)
            self.created.append(issue)
            return httpx.Response(201, json={"id": issue["id"], "key": key})
        if path == "/rest/api/3/issueLinkType":
            return httpx.Response(200, json={"issueLinkTypes": [{"name": "Blocks"}, {"name": "Relates"}]})
        if path == "/rest/api/3/issueLink":
            body = json.loads(request.content)
            self.links.append((body["inwardIssue"]["key"], body["outwardIssue"]["key"]))
            return httpx.Response(201)
        if path.startswith("/rest/api/3/issue/"):
            key = path.rsplit("/", 1)[1]
            links = [
                {"id": str(n), "type": {"name": "Blocks"}, "outwardIssue": {"key": b}}
                for n, (a, b) in enumerate(self.links)
                if a == key
            ]
            return httpx.Response(200, json={"fields": {"issuelinks": links}})
        return httpx.Response(404)

    def github(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.strip("/").split("/")
        name = "/".join(parts[1:3])
        repo = self.repos.get(name)
        if repo is None:
            return httpx.Response(404, json={"message": "Not Found"})
        rest = parts[3:]
        if not rest:
            return httpx.Response(
                200,
                json={
                    "full_name": name,
                    "description": repo["description"],
                    "default_branch": "main",
                    "language": repo["language"],
                    "topics": ["banking"],
                    "visibility": "private",
                    "archived": False,
                },
            )
        if rest[0] == "commits":
            return httpx.Response(200, text="abc123def4567890")
        if rest[:2] == ["git", "trees"]:
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [{"path": p, "type": "blob"} for p in repo["files"]]
                    + [{"path": "src", "type": "tree"}],
                },
            )
        if rest[0] == "languages":
            return httpx.Response(200, json={repo["language"]: 9000, "Shell": 1000})
        if rest[0] == "readme":
            return httpx.Response(200, text=f"# {name}\nHow to build and run {name}.")
        if rest[0] == "contents" and "/".join(rest[1:]) == "api/openapi.yaml":
            return httpx.Response(200, text=SPEC)
        return httpx.Response(404)

    def docs(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/openapi.yaml":
            return httpx.Response(200, text=DOC_SPEC, headers={"content-type": "application/yaml"})
        if request.url.path == "/guide":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=(
                    "<html><head><title>Salt Edge guide</title><script>var x=1</script></head>"
                    "<body><h1>Connect</h1><p>Create a customer, then a connection.</p></body></html>"
                ),
            )
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"location": "http://metadata.internal/latest"})
        if request.url.path == "/private":
            return httpx.Response(401)
        return httpx.Response(404)


@pytest.fixture
def world(monkeypatch) -> World:
    return World()


def _wire(world: World, monkeypatch, local: set[str] | None = None) -> None:
    """Point every outbound call at the fake. Called inside `boot`, after the app is imported."""
    from app.connectors import http
    from app.services import kickoff_sources

    http.transport = httpx.MockTransport(world)

    async def resolve(host: str) -> list[str]:
        return ["127.0.0.1"] if host in (local or {"metadata.internal"}) else ["93.184.216.34"]

    monkeypatch.setattr(kickoff_sources, "resolve_host", resolve)


async def _ready(c: httpx.AsyncClient, h: dict, *, deps: bool = True) -> dict:
    """An analysis with every step through compliance done."""
    a = (await c.post(f"{ENT}/kickoff/analyses", headers=h, json={"prd_url": PAGE_URL})).json()
    base = f"{ENT}/kickoff/analyses/{a['id']}"
    await c.put(f"{base}/repos", headers=h, json={"urls": ["https://github.com/acme/accounts-web"]})
    await c.put(
        f"{base}/dependencies",
        headers=h,
        json={"urls": ["https://github.com/acme/accounts-api"] if deps else []},
    )
    await c.post(f"{base}/compliance/suggest", headers=h)
    r = await c.put(f"{base}/compliance", headers=h, json={"selected": ["psd2", "gdpr"], "custom": []})
    assert r.status_code == 200, r.text
    await c.put(f"{base}/api-docs", headers=h, json={"urls": ["https://docs.example.com/openapi.yaml"]})
    r = await c.put(
        f"{base}/third-parties",
        headers=h,
        json={"providers": [{"key": "saltedge", "name": "", "docs_url": "https://docs.example.com/guide"}]},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _run(c: httpx.AsyncClient, h: dict, analysis: dict, provider: str = "rules") -> dict:
    r = await c.post(
        f"{ENT}/kickoff/analyses/{analysis['id']}/run",
        headers=h,
        json={"provider": provider, "model": "rules" if provider == "rules" else "claude-opus-5"},
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- Step 1: the PRD ------------------------------------------------------------------------------------


async def test_the_prd_is_read_from_confluence_and_saved_as_an_analysis(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        r = await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})
        assert r.status_code == 201, r.text
        a = r.json()
        assert a["title"] == "Instant account aggregation"
        assert a["prd"]["version"] == 7 and a["prd"]["via"] == "rest" and a["prd"]["space"] == "ENT"
        assert a["prd"]["lines"] == PRD_LINES
        assert a["prd"]["read_by"] == "dev@backbase.com"
        assert [s["done"] for s in a["steps"]] == [True, False, False, False, False, False, False, False]

        listed = (await c.get(f"{ENT}/kickoff/analyses", headers=contributor)).json()
        assert [x["id"] for x in listed] == [a["id"]]
        assert listed[0]["steps_done"] == 1 and listed[0]["steps_total"] == 8


async def test_a_page_on_another_site_or_a_missing_page_is_refused_with_the_reason(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        other = await c.post(
            f"{ENT}/kickoff/analyses",
            headers=contributor,
            json={"prd_url": "https://elsewhere.atlassian.net/wiki/spaces/X/pages/1/Y"},
        )
        assert other.status_code == 409
        assert "elsewhere.atlassian.net" in other.json()["detail"]["message"]
        assert "example.atlassian.net" in other.json()["detail"]["message"]
        missing = await c.post(
            f"{ENT}/kickoff/analyses",
            headers=contributor,
            json={"prd_url": f"{SITE}/wiki/spaces/ENT/pages/404/Gone"},
        )
        assert missing.status_code == 409 and "wasn't found" in missing.json()["detail"]["message"]
        no_id = await c.post(
            f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": f"{SITE}/wiki/home"}
        )
        assert "page id" in no_id.json()["detail"]["message"]
        assert (await c.get(f"{ENT}/kickoff/analyses", headers=contributor)).json() == []


async def test_without_a_connection_the_prd_step_says_how_to_connect_instead_of_showing_examples(
    client, contributor
):
    r = await client.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})
    assert r.status_code == 409
    assert "Settings → Connectors" in r.json()["detail"]["message"]
    status = (await client.get(f"{ENT}/kickoff/status", headers=contributor)).json()
    confluence = next(x for x in status["connections"] if x["key"] == "confluence")
    assert confluence["state"] == "not_configured"


async def test_status_names_where_credentials_come_from_and_never_returns_one(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        r = await c.get(f"{ENT}/kickoff/status", headers=contributor)
        assert r.status_code == 200
        assert TOKEN not in r.text and GH_TOKEN not in r.text
        states = {x["key"]: x["state"] for x in r.json()["connections"]}
        assert states == {"confluence": "ready", "github": "ready", "jira": "ready", "ai": "fallback"}


# --- Steps 2 and 3: repos -----------------------------------------------------------------------------


async def test_repos_are_read_at_a_pinned_commit_with_their_specs(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        r = await c.put(
            f"{base}/dependencies",
            headers=contributor,
            json={"urls": ["https://github.com/acme/accounts-api/tree/main/api", "acme/missing-repo"]},
        )
        assert r.status_code == 200, r.text
        repos = r.json()["dependencies"]["repos"]
        api, missing = repos
        assert api["ok"] and api["full_name"] == "acme/accounts-api" and api["commit"] == "abc123def456"
        assert api["html_url"] == "https://github.com/acme/accounts-api"
        assert api["specs"][0]["path"] == "api/openapi.yaml"
        assert api["specs"][0]["operation_count"] == 3
        assert api["specs"][0]["deprecated"] == ["GET /accounts/{id}/legacy"]
        assert api["read_with"] == "the service's GitHub token"
        assert not missing["ok"] and "wasn't found" in missing["error"]
        assert f"Bearer {GH_TOKEN}" in world.auth_seen
        # An unreadable repo blocks the run: it is never silently left out of the analysis.
        assert any("couldn't be read: acme/missing-repo" in b for b in r.json()["run_blockers"])


async def test_a_token_in_settings_connectors_is_used_before_the_environment(
    boot, contributor, admin, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        r = await c.post(
            "/api/connectors/github/secrets",
            headers=admin,
            json={"field_key": "personal_access_token", "value": "gh-from-settings"},
        )
        assert r.status_code == 204, r.text
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        r = await c.put(
            f"{ENT}/kickoff/analyses/{a['id']}/repos",
            headers=contributor,
            json={"urls": ["https://github.com/acme/accounts-web"]},
        )
        assert r.json()["repos"]["repos"][0]["read_with"] == "Settings → Connectors → GitHub"
        assert "Bearer gh-from-settings" in world.auth_seen
        assert "gh-from-settings" not in r.text


async def test_vendored_paths_are_left_out_of_the_tree(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        r = await c.put(
            f"{ENT}/kickoff/analyses/{a['id']}/repos",
            headers=contributor,
            json={"urls": ["https://github.com/acme/accounts-web"]},
        )
        repo = r.json()["repos"]["repos"][0]
        assert repo["file_count"] == 3
        assert "package.json" in repo["manifests"]


def test_a_pasted_link_goes_to_the_reader_it_belongs_to():
    """Step 3 takes whatever a team relies on, so the link decides the reader, not the person."""
    from app.services.kickoff_sources import classify

    gh, atl = "github.com", "example.atlassian.net"
    assert classify("https://github.com/acme/accounts-api", gh, atl) == "repo"
    assert classify("acme/accounts-api", gh, atl) == "repo"
    assert classify("git@github.com:acme/accounts-api.git", gh, atl) == "repo"
    assert classify(DEP_PAGE_URL, gh, atl) == "confluence"
    # A Confluence page on a site we aren't connected to is still a page, and says so when read.
    assert classify("https://other.atlassian.net/wiki/spaces/X/pages/12/Y", gh, "") == "confluence"
    assert classify("https://wiki.corp.example/x?pageId=44", gh, atl) == "confluence"
    assert classify("https://docs.example.com/openapi.yaml", gh, atl) == "doc"
    assert classify("https://docs.example.com/guide", gh, atl) == "doc"


async def test_what_we_rely_on_takes_repos_pages_and_documents_alike(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        r = await c.put(
            f"{ENT}/kickoff/analyses/{a['id']}/dependencies",
            headers=contributor,
            json={
                "urls": [
                    "https://github.com/acme/accounts-api",
                    DEP_PAGE_URL,
                    "https://docs.example.com/guide",
                ]
            },
        )
        assert r.status_code == 200, r.text
        deps = r.json()["dependencies"]
        assert [repo["full_name"] for repo in deps["repos"]] == ["acme/accounts-api"]
        kinds = {d["kind"]: d for d in deps["docs"]}
        assert set(kinds) == {"confluence", "page"}
        page = kinds["confluence"]
        assert page["ok"] and page["title"] == "Accounts service contract"
        assert page["version"] == "v3"
        assert "refreshed every four hours" in page["summary"]
        assert deps["saved"] is True
        # The step reports both kinds, so "3 repos" never stands in for a page nobody read.
        step = next(s for s in r.json()["steps"] if s["key"] == "dependencies")
        assert step["done"] and step["summary"] == "1 repo · 2 documents"


async def test_material_relied_on_is_part_of_what_makes_a_plan_stale(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = await _ready(c, contributor)
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        assert not (await _run(c, contributor, a))["plan"]["stale"]
        r = await c.put(
            f"{base}/dependencies",
            headers=contributor,
            json={"urls": ["https://github.com/acme/accounts-api", DEP_PAGE_URL]},
        )
        assert r.json()["plan"]["stale"] == ["what you rely on"]
        created = await c.post(
            f"{base}/backlog", headers=contributor, json={"backlog_url": f"{SITE}/browse/ENT-1"}
        )
        assert created.status_code == 409


async def test_a_repo_is_either_coded_in_or_relied_on(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        await c.put(
            f"{base}/repos", headers=contributor, json={"urls": ["https://github.com/acme/accounts-web"]}
        )
        r = await c.put(f"{base}/dependencies", headers=contributor, json={"urls": ["acme/accounts-web"]})
        assert r.status_code == 409 and "acme/accounts-web" in r.json()["detail"]["message"]


# --- Step 4: compliance --------------------------------------------------------------------------------


async def test_compliance_is_proposed_with_quotes_and_the_approval_is_named(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        r = await c.post(f"{base}/compliance/suggest", headers=contributor)
        comp = r.json()["compliance"]
        by_key = {s["key"]: s for s in comp["suggestions"]}
        # Germany + "open banking" puts PSD2 in scope; "personal data" in an EU PRD puts GDPR there.
        assert by_key["psd2"]["confidence"] == "strong" and by_key["gdpr"]["confidence"] == "strong"
        assert "rule-based" in comp["suggested_note"]
        for suggestion in comp["suggestions"]:
            assert suggestion["quotes"]
            for q in suggestion["quotes"]:
                assert PRD_LINES[q["line"] - 1].removeprefix("- ") == q["text"]
        # Nothing is chosen by proposing.
        assert comp["selected"] == [] and comp["approved_by"] is None

        bad = await c.put(f"{base}/compliance", headers=contributor, json={"selected": ["made_up"]})
        assert bad.status_code == 409
        ok = await c.put(
            f"{base}/compliance",
            headers=contributor,
            json={"selected": ["psd2"], "custom": [{"name": "Internal data residency", "note": "EU only"}]},
        )
        comp = ok.json()["compliance"]
        assert comp["approved_by"] == "dev@backbase.com" and comp["selected"] == ["psd2"]
        assert comp["custom"][0]["name"] == "Internal data residency"


async def test_approving_that_no_compliance_applies_is_an_answer(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        r = await c.put(
            f"{ENT}/kickoff/analyses/{a['id']}/compliance",
            headers=contributor,
            json={"selected": [], "custom": []},
        )
        step = next(s for s in r.json()["steps"] if s["key"] == "compliance")
        assert step["done"] and step["summary"] == "None apply"


# --- Steps 5 and 6: docs and providers -------------------------------------------------------------------


async def test_docs_are_read_as_operations_or_text_and_local_addresses_are_refused(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        r = await c.put(
            f"{ENT}/kickoff/analyses/{a['id']}/api-docs",
            headers=contributor,
            json={
                "urls": [
                    "https://docs.example.com/openapi.yaml",
                    "https://docs.example.com/guide",
                    "https://docs.example.com/moved",
                    "https://docs.example.com/private",
                    "http://localhost:8000/admin",
                ]
            },
        )
        spec, page, moved, private, local = r.json()["api_docs"]["docs"]
        assert (
            spec["kind"] == "openapi"
            and spec["operation_count"] == 2
            and spec["title"] == "Digital Banking API"
        )
        assert page["kind"] == "page" and page["title"] == "Salt Edge guide"
        assert "Create a customer" in page["summary"] and "var x" not in page["summary"]
        # A redirect to a local address is refused like the address itself.
        assert not moved["ok"] and "local or reserved" in moved["error"]
        assert not private["ok"] and "needs a login" in private["error"]
        assert not local["ok"]


async def test_providers_come_from_the_catalog_and_the_prd_names_them_first(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        assert a["third_parties"]["mentioned"]["saltedge"][0]["line"] == 4
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        unknown = await c.put(
            f"{base}/third-parties",
            headers=contributor,
            json={"providers": [{"key": "nope", "name": "Nope"}]},
        )
        assert unknown.status_code == 409
        r = await c.put(
            f"{base}/third-parties",
            headers=contributor,
            json={
                "providers": [
                    {"key": "saltedge", "name": "", "docs_url": "https://docs.example.com/guide"},
                    {"key": "", "name": "Ninth Wave", "docs_url": ""},
                ]
            },
        )
        salt, ninth = r.json()["third_parties"]["providers"]
        assert salt["name"] == "Salt Edge" and salt["doc"]["ok"] and salt["mentioned"]
        assert ninth["name"] == "Ninth Wave" and ninth["doc"] is None

        catalog = (await c.get(f"{ENT}/kickoff/catalog", headers=contributor)).json()
        assert {"saltedge", "ninthwave"} <= {p["key"] for p in catalog["providers"]}
        assert {"psd2", "gdpr", "pci_dss"} <= {f["key"] for f in catalog["frameworks"]}


# --- Step 7: the analysis --------------------------------------------------------------------------------


async def test_the_analysis_does_not_run_until_its_inputs_are_ready(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        r = await c.post(
            f"{ENT}/kickoff/analyses/{a['id']}/run",
            headers=contributor,
            json={"provider": "rules", "model": "rules"},
        )
        assert r.status_code == 409
        blockers = r.json()["detail"]["blockers"]
        assert any("repo to code in" in b for b in blockers)
        assert any("compliance" in b for b in blockers)


async def test_a_rule_based_draft_says_so_and_orders_every_task_after_what_it_depends_on(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = await _run(c, contributor, await _ready(c, contributor))
        plan = a["plan"]
        assert a["status"] == "analysed"
        assert plan["reader"] == "rules" and "no AI" in plan["drafted_by"]
        refs = [t["ref"] for t in plan["tasks"]]
        assert refs == [f"T{n}" for n in range(1, len(refs) + 1)]
        for i, task in enumerate(plan["tasks"]):
            assert all(refs.index(d) < i for d in task["depends_on"]), task
            assert task["origin"] == "rules"
        titles = [t["title"] for t in plan["tasks"]]
        assert titles[0] == "Get Salt Edge sandbox access and credentials"
        assert "Link an account at another bank through Salt Edge" in titles
        assert titles[-1].startswith("End-to-end tests")
        story = next(t for t in plan["tasks"] if t["title"].startswith("Show balances"))
        assert story["repo"] == "acme/accounts-web" and story["quotes"][0]["line"] == 5
        assert {k for t in plan["tasks"] for k in t["compliance"]} == {"psd2", "gdpr"}


async def test_a_claude_draft_is_held_to_its_inputs(boot, contributor, world, monkeypatch):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        from app.services import kickoff_ai, model_provider

        async def models(api_key: str, default: str):
            return [model_provider.ModelOption("claude-opus-5", "Claude Opus 5")], "1 model"

        seen: dict = {}

        async def fake_call(provider, model, system, content, output, max_tokens):
            if output is kickoff_ai.ComplianceSuggestions:
                return kickoff_ai.ComplianceSuggestions(
                    frameworks=[
                        kickoff_ai.SuggestedFramework(
                            key="psd2", confidence="strong", why="Open banking.", lines=[2]
                        ),
                        kickoff_ai.SuggestedFramework(key="made_up", confidence="strong", why="?", lines=[2]),
                        kickoff_ai.SuggestedFramework(
                            key="pci_dss", confidence="possible", why="?", lines=[]
                        ),
                    ],
                    other=[],
                )
            seen["content"] = content
            return kickoff_ai.DraftPlan(
                summary="Aggregation.",
                epic_title="Account aggregation",
                epic_description="Epic.",
                repo_work=[
                    kickoff_ai.RepoWork(
                        repo="ACME/accounts-web",
                        summary="UI",
                        changes=[
                            kickoff_ai.Change(
                                area="src/app/accounts", what="List linked accounts", why="Req 2"
                            )
                        ],
                    ),
                    kickoff_ai.RepoWork(repo="acme/invented", summary="?", changes=[]),
                ],
                dependency_needs=[
                    kickoff_ai.DependencyNeed(
                        repo="acme/accounts-api",
                        relies_on="Balances",
                        status="available",
                        evidence="GET /accounts/{id}/balances",
                        action="None",
                    )
                ],
                risks=["Consent expiry"],
                open_questions=["Which banks first?"],
                tasks=[
                    kickoff_ai.DraftTask(
                        title="Build the UI",
                        type="Story",
                        repo="acme/accounts-web",
                        description="d",
                        acceptance_criteria=["a"],
                        depends_on=[2],
                        estimate="M",
                        compliance=["psd2", "sox"],
                        prd_lines=[5, 99, 1],
                    ),
                    kickoff_ai.DraftTask(
                        title="Salt Edge client",
                        type="Story",
                        repo="acme/elsewhere",
                        description="d",
                        acceptance_criteria=[],
                        depends_on=[],
                        estimate="L",
                        compliance=[],
                        prd_lines=[],
                    ),
                ],
            )

        monkeypatch.setattr(model_provider, "_claude_models", models)
        monkeypatch.setattr(kickoff_ai, "_call", fake_call)
        ready = await _ready(c, contributor)
        proposed = {(s["key"], s["by"]) for s in ready["compliance"]["suggestions"]}
        # Claude's unknown key and its unquoted proposal are dropped; a strong keyword match it
        # didn't list is still shown.
        assert proposed == {("psd2", "claude"), ("gdpr", "rules")}
        a = await _run(c, contributor, ready, provider="claude")
        plan = a["plan"]
        assert plan["reader"] == "claude" and plan["drafted_by"] == "Claude (claude-opus-5)"
        # The dependency comes first, whatever order the model gave.
        assert [t["title"] for t in plan["tasks"]] == ["Salt Edge client", "Build the UI"]
        client_task, ui = plan["tasks"]
        assert ui["depends_on"] == [client_task["ref"]]
        assert client_task["repo"] == ""  # a repo that isn't in step 2 is left unassigned, and said so
        assert any("acme/elsewhere" in n for n in plan["notes"])
        assert ui["compliance"] == ["psd2"]  # not an approved framework: dropped
        assert [q["line"] for q in ui["quotes"]] == [5]  # headings and lines past the end: dropped
        assert [w["repo"] for w in plan["repo_work"]] == ["acme/accounts-web"]
        # What the model was given: numbered PRD lines, the repo tree and spec, the approvals.
        assert "5. - Show balances and transactions for linked accounts" in seen["content"]
        assert "src/app/accounts/accounts.service.ts" in seen["content"]
        assert "GET /accounts/{id}/balances" in seen["content"]
        assert "psd2: PSD2" in seen["content"]


FAKE_CURSOR = '''#!/usr/bin/env python3
"""A stand-in for the Cursor CLI: logs each call, lists models, answers from answers.json."""
import json, os, sys
from pathlib import Path

here = Path(__file__).parent
args = sys.argv[1:]
with open(here / "calls.jsonl", "a") as log:
    call = {{"args": args, "env": dict(os.environ), "cwd": os.getcwd(), "files": sorted(os.listdir("."))}}
    log.write(json.dumps(call) + "\\n")
if args[:1] == ["models"]:
    if (here / "signed-out").exists():
        print("Error: not logged in. Run 'agent login' first.", file=sys.stderr)
        sys.exit(1)
    print("Available models\\n\\nauto - Auto\\nsonnet-4.5 - Claude 4.5 Sonnet  (current)\\ngpt-5 - GPT-5\\n")
    print("Tip: use --model <id> to switch.")
    sys.exit(0)
prompt = args[-1]
for needle, answer in json.loads((here / "answers.json").read_text()):
    if needle in prompt:
        print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": answer}}))
        sys.exit(0)
print("no answer for this prompt", file=sys.stderr)
sys.exit(1)
'''


def _fake_cursor(tmp_path, answers: list[tuple[str, str]]):
    cli = tmp_path / "cursor-agent"
    cli.write_text(FAKE_CURSOR.format())
    cli.chmod(0o755)
    (tmp_path / "answers.json").write_text(json.dumps(answers))
    return cli


def _cursor_calls(tmp_path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


async def test_a_cursor_draft_runs_the_cli_read_only_and_is_held_to_its_inputs(
    boot, contributor, world, monkeypatch, tmp_path
):
    from app.services import kickoff_ai as k

    plan = k.DraftPlan(
        summary="Aggregation.",
        epic_title="Account aggregation",
        epic_description="Epic.",
        repo_work=[k.RepoWork(repo="acme/invented", summary="?", changes=[])],
        dependency_needs=[],
        risks=[],
        open_questions=[],
        tasks=[
            k.DraftTask(
                title="Build the UI", type="Story", repo="ACME/accounts-web", description="d",
                acceptance_criteria=["a"], depends_on=[2], estimate="M", compliance=["psd2", "sox"],
                prd_lines=[5],
            ),
            k.DraftTask(
                title="Salt Edge client", type="Story", repo="", description="d", acceptance_criteria=[],
                depends_on=[], estimate="L", compliance=[], prd_lines=[],
            ),
        ],
    )
    suggestions = k.ComplianceSuggestions(
        frameworks=[k.SuggestedFramework(key="psd2", confidence="strong", why="Open banking.", lines=[2])],
        other=[],
    )
    cli = _fake_cursor(
        tmp_path,
        [
            # The CLI can't enforce a schema: prose and a fence around the JSON are tolerated.
            ("compliance frameworks a bank's feature must meet", suggestions.model_dump_json()),
            ("You plan engineering work", f"Here it is:\n```json\n{plan.model_dump_json()}\n```"),
        ],
    )
    async with boot(**ENV, SHIFTLEFT_CURSOR_CLI=str(cli), SHIFTLEFT_CURSOR_API_KEY="crsr-key") as c:
        _wire(world, monkeypatch)
        status = (await c.get(f"{ENT}/kickoff/status", headers=contributor)).json()
        cursor = next(p for p in status["providers"] if p["key"] == "cursor")
        assert cursor["available"] and cursor["default_model"] == "sonnet-4.5"
        assert [m["id"] for m in cursor["models"]] == ["auto", "sonnet-4.5", "gpt-5"]
        assert status["default_provider"] == "cursor"

        ready = await _ready(c, contributor)
        assert {(s["key"], s["by"]) for s in ready["compliance"]["suggestions"]} == {
            ("psd2", "cursor"),
            ("gdpr", "rules"),
        }
        run = f"{ENT}/kickoff/analyses/{ready['id']}/run"
        r = await c.post(run, headers=contributor, json={"provider": "cursor", "model": "made-up"})
        assert r.status_code == 409  # only a model the CLI listed can run

        r = await c.post(run, headers=contributor, json={"provider": "cursor", "model": "sonnet-4.5"})
        assert r.status_code == 200, r.text
        drafted = r.json()["plan"]
        assert drafted["reader"] == "cursor" and drafted["drafted_by"] == "sonnet-4.5 through Cursor"
        assert [t["title"] for t in drafted["tasks"]] == ["Salt Edge client", "Build the UI"]
        assert {t["origin"] for t in drafted["tasks"]} == {"cursor"}
        assert drafted["tasks"][1]["compliance"] == ["psd2"]
        assert drafted["repo_work"] == []  # a repo that isn't an input is dropped

        # An answer that doesn't fit the shape falls back to the rule-based draft, and says why.
        (tmp_path / "answers.json").write_text(json.dumps([["You plan engineering work", "Sorry, no."]]))
        r = await c.post(run, headers=contributor, json={"provider": "cursor", "model": "sonnet-4.5"})
        fallback = r.json()["plan"]
        assert fallback["reader"] == "rules" and "Cursor couldn't draft this" in fallback["note"]

    asked = [call for call in _cursor_calls(tmp_path) if call["args"][:1] == ["-p"]]
    assert len(asked) == 3
    for call in asked:
        args = call["args"]
        assert args[args.index("--mode") + 1] == "ask" and "--trust" in args
        assert "--force" not in args and "-f" not in args and "--approve-mcps" not in args
        workspace = Path(args[args.index("--workspace") + 1])
        assert workspace.resolve() == Path(call["cwd"]).resolve()
        # Nothing of ours reaches the CLI but its own key; its empty workspace is gone afterwards.
        assert call["env"]["CURSOR_API_KEY"] == "crsr-key"
        assert not [k for k in call["env"] if k.startswith("SHIFTLEFT_")]
        assert TOKEN not in json.dumps(call["env"]) and GH_TOKEN not in json.dumps(call["env"])
        assert not workspace.exists()


async def test_inputs_too_long_for_one_argument_reach_the_cli_as_a_file(boot, tmp_path):
    from app.services import kickoff_ai as k

    answer = k.ComplianceSuggestions(frameworks=[], other=[])
    cli = _fake_cursor(tmp_path, [("compliance frameworks", answer.model_dump_json())])
    async with boot(SHIFTLEFT_CURSOR_CLI=str(cli)):
        from app.services import cursor_cli

        inputs = "a-line-of-the-inputs\n" * 20_000
        got = await cursor_cli.ask("gpt-5", k.SUGGEST_SYSTEM, inputs, k.ComplianceSuggestions, 30)
    assert got == answer
    (call,) = _cursor_calls(tmp_path)
    assert call["files"] == ["inputs.md"] and "a-line-of-the-inputs" not in call["args"][-1]
    assert len(call["args"][-1].encode()) < cursor_cli.ARGV_PROMPT_LIMIT


async def test_a_signed_out_or_missing_cursor_cli_says_how_to_fix_it(boot, contributor, tmp_path):
    cli = _fake_cursor(tmp_path, [])
    (tmp_path / "signed-out").touch()
    async with boot(SHIFTLEFT_CURSOR_CLI=str(cli)) as c:
        status = (await c.get(f"{ENT}/kickoff/status", headers=contributor)).json()
        cursor = next(p for p in status["providers"] if p["key"] == "cursor")
        assert not cursor["available"] and "agent login" in cursor["note"]
        assert status["default_provider"] == "rules"
    async with boot(SHIFTLEFT_CURSOR_CLI=str(tmp_path / "not-there")) as c:
        status = (await c.get(f"{ENT}/kickoff/status", headers=contributor)).json()
        cursor = next(p for p in status["providers"] if p["key"] == "cursor")
        assert not cursor["available"] and "isn't installed" in cursor["note"]


async def test_editing_tasks_is_recorded_and_the_order_is_enforced(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = await _run(c, contributor, await _ready(c, contributor))
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        tasks = a["plan"]["tasks"]
        dependent = next(t for t in tasks if t["depends_on"])
        # Moving a task above what it depends on is refused, with the reason.
        reordered = [dependent] + [t for t in tasks if t["ref"] != dependent["ref"]]
        r = await c.put(f"{base}/plan", headers=contributor, json={"epic_title": "E", "tasks": reordered})
        assert r.status_code == 409 and "isn't above it" in r.json()["detail"]["blockers"][0]

        edited = [
            {**tasks[0], "title": "Get Salt Edge sandbox access"},
            *tasks[1:],
            {"title": "Feature flag and rollout", "type": "Task", "depends_on": [tasks[-1]["ref"]]},
        ]
        r = await c.put(
            f"{base}/plan", headers=contributor, json={"epic_title": "Aggregation", "tasks": edited}
        )
        assert r.status_code == 200, r.text
        plan = r.json()["plan"]
        assert plan["epic_title"] == "Aggregation" and plan["edited_by"] == "dev@backbase.com"
        assert plan["tasks"][0]["edited_by"] == "dev@backbase.com" and plan["tasks"][0]["origin"] == "rules"
        assert plan["tasks"][1]["edited_by"] is None
        added = plan["tasks"][-1]
        assert added["origin"] == "person" and added["ref"] == f"T{len(tasks) + 1}"


async def test_a_plan_older_than_its_inputs_says_which_and_cannot_be_created(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = await _run(c, contributor, await _ready(c, contributor))
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        r = await c.put(f"{base}/api-docs", headers=contributor, json={"urls": []})
        assert r.json()["plan"]["stale"] == ["the API docs"]
        listed = (await c.get(f"{ENT}/kickoff/analyses", headers=contributor)).json()
        assert listed[0]["stale"] is True
        r = await c.post(f"{base}/backlog", headers=contributor, json={"backlog_url": "ENT"})
        assert r.status_code == 409 and "run the analysis again" in r.json()["detail"]["message"]
        assert world.created == []


# --- Step 7: the technical design ---------------------------------------------------------------------


def _tdd(ai, sections: list[tuple[str, str]]):
    return ai.TddDraft(
        sections=[
            ai.TddSectionDraft(
                key=key,
                title=title,
                body_markdown="- Reads balances from acme/accounts-api\n\n```mermaid\nsequenceDiagram\n```",
                diagrams=[
                    ai.Diagram(kind="sequence", title="Link flow", source="sequenceDiagram\n  A->>B: hi")
                ],
            )
            for key, title in sections
        ]
    )


async def _tdd_ready(c, headers, world, monkeypatch, mode: str, selected: list[str]):
    """An analysis with step 7 read and confirmed, ready to run."""
    a = await _ready(c, headers)
    base = f"{ENT}/kickoff/analyses/{a['id']}"
    r = await c.post(f"{base}/tdd/page", headers=headers, json={"mode": mode, "url": TDD_PAGE_URL})
    assert r.status_code == 200, r.text
    r = await c.put(
        f"{base}/tdd",
        headers=headers,
        json={"enabled": True, "selected": selected, "space_key": "ENT", "title": "Accounts TDD"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_sections_offered_are_the_ones_the_page_has(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        base = f"{ENT}/kickoff/analyses/{a['id']}"

        r = await c.post(
            f"{base}/tdd/page", headers=contributor, json={"mode": "existing", "url": TDD_PAGE_URL}
        )
        assert r.status_code == 200, r.text
        tdd = r.json()["tdd"]
        # An existing design offers only what it has: nothing is invented into a team's page.
        on_the_page = [s for s in tdd["sections"] if s["present"]]
        assert [s["key"] for s in on_the_page] == ["other-accounts-tdd", "hld", "risks", "monitoring"]
        # A section the page lacks can be added deliberately, but is never ticked for you.
        addable = {s["key"]: s for s in tdd["sections"] if not s["present"]}
        assert "traceability" in addable and addable["traceability"]["recommended"] is False
        assert tdd["source"]["version"] == 4

        # A sample also offers the standard sections it lacks, so a thin template still works.
        r = await c.post(
            f"{base}/tdd/page", headers=contributor, json={"mode": "sample", "url": TDD_PAGE_URL}
        )
        offered = {s["key"]: s for s in r.json()["tdd"]["sections"]}
        assert offered["hld"]["present"] is True
        assert offered["traceability"]["present"] is False
        assert offered["lld"]["present"] is False

        # Nothing may be ticked that the page didn't offer.
        r = await c.put(f"{base}/tdd", headers=contributor, json={"enabled": True, "selected": ["invented"]})
        assert r.status_code == 409 and "aren't on that page" in r.json()["detail"]["message"]


async def test_the_design_replaces_only_the_ticked_sections_and_leaves_the_rest_byte_for_byte(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        ai = _fake_model(monkeypatch, [])
        monkeypatch.setattr(
            ai,
            "_call",
            _queue(
                ai,
                [
                    _plan(ai, ["Build the UI"]),
                    _tdd(ai, [("hld", "High-level design"), ("lld", "Low-level design")]),
                ],
            ),
        )
        a = await _tdd_ready(c, contributor, world, monkeypatch, "existing", ["hld", "traceability"])
        assert a["tdd"]["approved_by"] == "dev@backbase.com"

        a = await _run(c, contributor, a, provider="claude")
        doc = a["tdd_document"]
        assert doc["drafted"] and doc["note"] == ""
        # A section nobody ticked is dropped, however good it looks.
        assert [s["key"] for s in doc["sections"]] == ["hld", "traceability"]
        assert any("wasn't ticked" in n for n in doc["notes"])
        # The traceability matrix is built from the analysis, not drafted.
        built = doc["sections"][1]
        assert built["built"] is True and built["body_markdown"] == ""
        assert built["rows"][0][0].startswith("T1 · Build the UI")
        assert built["rows"][0][6] == "—"

        published = doc["published"]
        assert published["written"] == ["hld"] and published["version"] == 5
        page = world.pages[TDD_PAGE_ID]
        # This is the guarantee: every section nobody ticked survives exactly as it was.
        assert "<p>A risk nobody asked us to rewrite.</p>" in page
        assert "<p>Old monitoring.</p>" in page
        assert "<p>Owned by the accounts team.</p>" in page
        assert "<p>The old high-level design.</p>" not in page
        assert "acme/accounts-api" in page
        # The version message says who and what, so it is traceable and revertible in Confluence.
        assert "dev@backbase.com" in world.version_messages[-1]
        assert "High-level design" in world.version_messages[-1]
        assert {"prefix": "global", "name": f"shiftleft-kickoff-{a['id']}"} in world.page_labels


async def test_a_sample_writes_a_new_page_and_running_again_writes_the_same_one(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        ai = _fake_model(monkeypatch, [])
        monkeypatch.setattr(
            ai,
            "_call",
            _queue(
                ai,
                [
                    _plan(ai, ["Build the UI"]),
                    _tdd(ai, [("hld", "High-level design")]),
                    _plan(ai, ["Build the UI"]),
                    _tdd(ai, [("hld", "High-level design")]),
                ],
            ),
        )
        a = await _tdd_ready(c, contributor, world, monkeypatch, "sample", ["hld"])
        a = await _run(c, contributor, a, provider="claude")
        assert len(world.created_pages) == 1
        assert world.created_pages[0]["title"] == "Accounts TDD"
        assert a["tdd_document"]["published"]["page_id"] == "9200000"

        # Running again writes the page it made, rather than leaving a trail of duplicates.
        world.pages["9200000"] = world.created_pages[0]["body"]["value"]
        await _run(c, contributor, a, provider="claude")
        assert len(world.created_pages) == 1


async def test_a_design_that_cannot_be_written_says_why_and_never_costs_the_plan(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        ai = _fake_model(monkeypatch, [])
        monkeypatch.setattr(
            ai, "_call", _queue(ai, [_plan(ai, ["Build the UI"]), _tdd(ai, [("hld", "High-level design")])])
        )
        a = await _tdd_ready(c, contributor, world, monkeypatch, "existing", ["hld"])

        from app.services import kickoff_tdd

        async def refuses(*args, **kwargs):
            from app.connectors.atlassian_rest import AtlassianError

            raise AtlassianError("Updating the page failed", 409)

        monkeypatch.setattr(kickoff_tdd, "publish", refuses)
        a = await _run(c, contributor, a, provider="claude")

        assert "Someone saved the page while this ran" in a["tdd_document"]["note"]
        assert a["tdd_document"]["published"] is None
        # The plan is what the backlog is made from, and it is unaffected.
        assert [t["title"] for t in a["plan"]["tasks"]] == ["Build the UI"]
        assert world.pages[TDD_PAGE_ID] == TDD_STORAGE


async def test_changing_the_ticked_sections_makes_the_plan_stale(boot, contributor, world, monkeypatch):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        ai = _fake_model(monkeypatch, [])
        monkeypatch.setattr(
            ai, "_call", _queue(ai, [_plan(ai, ["Build the UI"]), _tdd(ai, [("hld", "High-level design")])])
        )
        a = await _tdd_ready(c, contributor, world, monkeypatch, "existing", ["hld"])
        a = await _run(c, contributor, a, provider="claude")
        assert not a["plan"]["stale"]

        r = await c.put(
            f"{ENT}/kickoff/analyses/{a['id']}/tdd",
            headers=contributor,
            json={"enabled": True, "selected": ["hld", "risks"], "space_key": "ENT"},
        )
        assert r.json()["plan"]["stale"] == ["the technical design sections"]


# --- Creating the backlog ----------------------------------------------------------------------------------


async def test_the_backlog_gets_the_epic_then_every_task_in_order_linked_and_attributed(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = await _run(c, contributor, await _ready(c, contributor))
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        backlog_url = f"{SITE}/jira/software/c/projects/ENT/boards/12/backlog"
        r = await c.post(f"{base}/backlog", headers=contributor, json={"backlog_url": backlog_url})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["status"] == "created"
        backlog = out["backlog"]
        assert backlog["project_key"] == "ENT" and backlog["board_id"] == "12"
        assert backlog["created_by"] == "dev@backbase.com" and backlog["failed"] == 0
        assert backlog["epic"]["key"] == "ENT-1"

        epic, *tasks = world.created
        assert epic["fields"]["issuetype"] == {"id": "10"}
        assert [t["fields"]["summary"] for t in tasks] == [t["title"] for t in a["plan"]["tasks"]]
        assert all(t["fields"]["parent"] == {"key": "ENT-1"} for t in tasks)
        assert all(f"shiftleft-kickoff-{a['id']}" in t["fields"]["labels"] for t in world.created)
        spike = tasks[0]
        assert spike["fields"]["issuetype"] == {"id": "12"}  # no Spike type in ENT: created as a Task
        text = json.dumps(spike["fields"]["description"])
        assert "dev@backbase.com" in text and "rule-based" in text

        keys = {t["ref"]: t["key"] for t in backlog["tickets"]}
        expected = {(keys[d], keys[t["ref"]]) for t in a["plan"]["tasks"] for d in t["depends_on"]}
        assert set(world.links) == expected

        # A retry creates nothing twice: what exists is found by label and summary.
        again = await c.post(f"{base}/backlog", headers=contributor, json={"backlog_url": backlog_url})
        assert again.status_code == 200
        assert len(world.created) == 1 + len(a["plan"]["tasks"])
        assert {t["status"] for t in again.json()["backlog"]["tickets"]} == {"exists"}
        assert again.json()["backlog"]["attempts"] == 2


async def test_the_preflight_refuses_before_anything_is_written(boot, contributor, world, monkeypatch):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        world.required = [
            {"key": "customfield_100", "name": "Team", "required": True, "hasDefaultValue": False}
        ]
        a = await _run(c, contributor, await _ready(c, contributor))
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        r = await c.post(f"{base}/backlog", headers=contributor, json={"backlog_url": "ENT"})
        assert r.status_code == 409
        assert any("“Team”" in b for b in r.json()["detail"]["blockers"])
        other = await c.post(
            f"{base}/backlog",
            headers=contributor,
            json={"backlog_url": "https://elsewhere.atlassian.net/browse/ENT-1"},
        )
        assert other.status_code == 409 and "elsewhere.atlassian.net" in other.json()["detail"]["message"]
        assert world.created == []


async def test_ticket_options_are_offered_by_jira_and_applied_to_every_ticket(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = await _run(c, contributor, await _ready(c, contributor))
        base = f"{ENT}/kickoff/analyses/{a['id']}"

        # Nothing is typed blind: the choices come from the project itself.
        r = await c.get(f"{base}/backlog-fields", headers=contributor, params={"backlog_url": "ENT"})
        assert r.status_code == 200, r.text
        offered = r.json()
        assert offered["components"] == ["Accounts", "Web"]
        # Unreleased first, and an archived version is not offered at all.
        assert offered["fix_versions"] == ["2026.4", "2026.2"]
        assert offered["priorities"] == ["High", "Medium"]

        r = await c.put(
            f"{base}/backlog-options",
            headers=contributor,
            json={
                "labels": ["platform"],
                "components": ["Accounts", "Invented"],
                "priority": "High",
                "fix_version": "2026.4",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["backlog_options"]["priority"] == "High"

        r = await c.post(f"{base}/backlog", headers=contributor, json={"backlog_url": "ENT"})
        assert r.status_code == 200, r.text
        for issue in world.created:
            fields = issue["fields"]
            # A component the project doesn't have is dropped rather than failing every create.
            assert fields["components"] == [{"name": "Accounts"}]
            assert fields["priority"] == {"name": "High"}
            assert fields["fixVersions"] == [{"name": "2026.4"}]
            # The two identity labels always go on: finding these tickets again depends on them.
            assert fields["labels"] == [f"shiftleft-kickoff-{a['id']}", "shiftleft-tracked", "platform"]


async def test_a_required_field_the_options_can_fill_stops_blocking_the_create(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        world.required = [
            {"key": "components", "name": "Component/s", "required": True, "hasDefaultValue": False}
        ]
        a = await _run(c, contributor, await _ready(c, contributor))
        base = f"{ENT}/kickoff/analyses/{a['id']}"

        r = await c.post(f"{base}/backlog", headers=contributor, json={"backlog_url": "ENT"})
        assert r.status_code == 409
        assert any("Ticket options" in b for b in r.json()["detail"]["blockers"])
        assert world.created == []

        await c.put(f"{base}/backlog-options", headers=contributor, json={"components": ["Accounts"]})
        r = await c.post(f"{base}/backlog", headers=contributor, json={"backlog_url": "ENT"})
        assert r.status_code == 200, r.text
        assert world.created and world.created[0]["fields"]["components"] == [{"name": "Accounts"}]


# --- Access --------------------------------------------------------------------------------


async def test_a_viewer_reads_analyses_but_cannot_change_or_run_them(
    boot, contributor, viewer, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        assert (await c.get(base, headers=viewer)).status_code == 200
        assert (
            await c.post(f"{ENT}/kickoff/analyses", headers=viewer, json={"prd_url": PAGE_URL})
        ).status_code == 404
        for method, path, body in [
            ("put", "/repos", {"urls": []}),
            ("post", "/compliance/suggest", None),
            ("put", "/compliance", {"selected": []}),
            ("post", "/run", {"provider": "rules", "model": "rules"}),
            ("post", "/refine", {"provider": "claude", "model": "m", "instructions": "x"}),
            ("post", "/tdd/page", {"mode": "sample", "url": TDD_PAGE_URL}),
            ("put", "/tdd", {"enabled": False}),
            ("post", "/tdd/publish", None),
            ("put", "/backlog-options", {"labels": ["x"]}),
            ("post", "/backlog", {"backlog_url": "ENT"}),
            ("patch", "", {"title": "x"}),
            ("delete", "", None),
        ]:
            r = await c.request(method.upper(), base + path, headers=viewer, json=body)
            assert r.status_code == 404, (method, path, r.status_code)
        # Reading what an analysis has produced is a viewer's to do.
        for path in ("/runs", "/runs/1"):
            assert (await c.get(base + path, headers=viewer)).status_code in (200, 404)
        # The ticket-option choices come from Jira, so reading them is a write-shaped read.
        r = await c.get(f"{base}/backlog-fields", headers=viewer, params={"backlog_url": "ENT"})
        assert r.status_code == 404


async def test_analyses_do_not_leak_across_projects_or_to_strangers(
    boot, contributor, admin, stranger, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        assert (await c.get(f"{ENT}/kickoff/analyses/{a['id']}", headers=stranger)).status_code == 404
        assert (await c.get(f"{ENT}/kickoff/analyses", headers=stranger)).status_code == 404
        # The right id under another project is not found, even for someone who can see both.
        assert (await c.get(f"{PAY}/kickoff/analyses/{a['id']}", headers=admin)).status_code == 404
        assert (await c.get(f"{PAY}/kickoff/analyses", headers=admin)).json() == []


async def test_deleting_an_analysis_is_audited_and_leaves_jira_alone(
    boot, contributor, admin, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        r = await c.delete(f"{ENT}/kickoff/analyses/{a['id']}", headers=contributor)
        assert r.status_code == 204
        assert (await c.get(f"{ENT}/kickoff/analyses/{a['id']}", headers=contributor)).status_code == 404


# --- Service-wide defaults ---------------------------------------------------------------------------------


async def test_defaults_are_readable_by_anyone_and_changed_only_by_a_platform_admin(
    boot, admin, contributor, viewer
):
    async with boot(**ENV) as c:
        # No credential lives here, so reading it is not restricted: the wizard fills in from it.
        r = await c.get("/api/kickoff/settings", headers=viewer)
        assert r.status_code == 200
        assert r.json()["tdd_template_url"] == "" and r.json()["editable"] is False

        body = {
            "tdd_template_url": f"{SITE}/wiki/spaces/PLT/pages/{DEP_PAGE_ID}/Template",
            "tdd_space_key": "plt",
            "tdd_parent_url": "",
            "tdd_sections": ["hld", "lld", "hld"],
            "jira_project_url": f"{SITE}/browse/ENT-1",
            "jira_defaults": {"labels": ["platform"], "components": ["Accounts"], "priority": "High"},
            "analysis_prompt": "Call out anything that needs another team.",
            "tdd_prompt": "",
        }
        assert (await c.put("/api/kickoff/settings", headers=contributor, json=body)).status_code == 403
        r = await c.put("/api/kickoff/settings", headers=admin, json=body)
        assert r.status_code == 200, r.text
        saved = r.json()
        assert saved["editable"] is True
        assert saved["tdd_space_key"] == "PLT"
        assert saved["tdd_sections"] == ["hld", "lld"]
        assert saved["jira_defaults"]["labels"] == ["platform"]
        assert saved["updated_by"] == "h.nuti@backbase.com"


async def test_a_new_analysis_starts_from_the_defaults_and_can_still_change_them(
    boot, admin, contributor, world, monkeypatch
):
    async with boot(**ENV) as c:
        _wire(world, monkeypatch)
        await c.put(
            "/api/kickoff/settings",
            headers=admin,
            json={
                "jira_project_url": f"{SITE}/browse/ENT-1",
                "jira_defaults": {"labels": ["platform"]},
                "analysis_prompt": "Call out anything that needs another team.",
                "tdd_sections": ["hld"],
                "tdd_template_url": f"{SITE}/wiki/spaces/PLT/pages/{DEP_PAGE_ID}/Template",
            },
        )
        a = (await c.post(f"{ENT}/kickoff/analyses", headers=contributor, json={"prd_url": PAGE_URL})).json()
        assert a["backlog_target"]["url"] == f"{SITE}/browse/ENT-1"

        # A later change to the defaults never reaches an analysis already under way.
        await c.put(
            "/api/kickoff/settings",
            headers=admin,
            json={"jira_project_url": f"{SITE}/browse/OTHER-1"},
        )
        again = (await c.get(f"{ENT}/kickoff/analyses/{a['id']}", headers=contributor)).json()
        assert again["backlog_target"]["url"] == f"{SITE}/browse/ENT-1"


# --- Running again, and refining instead ---------------------------------------------------------------


def _plan(ai, titles: list[str], epic: str = "Account aggregation"):
    """A drafted plan of the given task titles, in order."""
    return ai.DraftPlan(
        summary="Aggregation.",
        epic_title=epic,
        epic_description="Epic.",
        repo_work=[],
        dependency_needs=[],
        risks=[],
        open_questions=[],
        tasks=[
            ai.DraftTask(
                title=title,
                type="Story",
                repo="acme/accounts-web",
                description="d",
                acceptance_criteria=["a"],
                depends_on=[],
                estimate="M",
                compliance=[],
                prd_lines=[],
            )
            for title in titles
        ],
    )


def _fake_model(monkeypatch, drafts: list, seen: dict | None = None):
    """Answers each model call with the next draft, and records what it was given."""
    from app.services import kickoff_ai, model_provider

    async def models(api_key: str, default: str):
        return [model_provider.ModelOption("claude-opus-5", "Claude Opus 5")], "1 model"

    queue = list(drafts)

    async def fake_call(provider, model, system, content, output, max_tokens):
        if output is kickoff_ai.ComplianceSuggestions:
            return kickoff_ai.ComplianceSuggestions(frameworks=[], other=[])
        if seen is not None:
            seen.setdefault("calls", []).append({"system": system, "content": content})
        return queue.pop(0)

    monkeypatch.setattr(kickoff_ai, "_call", fake_call)
    monkeypatch.setattr(model_provider, "_claude_models", models)
    return kickoff_ai


async def test_running_again_keeps_the_draft_it_replaced_and_says_what_changed(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        ai = _fake_model(monkeypatch, [])
        # The drafts name the module's own types, so they are built once it is imported.
        monkeypatch.setattr(
            ai,
            "_call",
            _queue(
                ai,
                [
                    _plan(ai, ["Build the UI", "Salt Edge client"]),
                    _plan(ai, ["Build the UI", "Consent screen"]),
                ],
            ),
        )
        a = await _ready(c, contributor)
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        first = await _run(c, contributor, a, provider="claude")
        assert [t["title"] for t in first["plan"]["tasks"]] == ["Build the UI", "Salt Edge client"]

        second = await _run(c, contributor, a, provider="claude")
        assert second["plan"]["run_number"] == 2

        runs = (await c.get(f"{base}/runs", headers=contributor)).json()
        assert [(r["run_number"], r["kind"], r["is_current"]) for r in runs] == [
            (2, "run", True),
            (1, "run", False),
        ]

        # The draft that was replaced is still readable, whole.
        one = (await c.get(f"{base}/runs/1", headers=contributor)).json()
        assert [t["title"] for t in one["plan"]["tasks"]] == ["Build the UI", "Salt Edge client"]
        assert one["diff"] is None

        two = (await c.get(f"{base}/runs/2", headers=contributor)).json()
        assert [t["title"] for t in two["diff"]["added"]] == ["Consent screen"]
        assert [t["title"] for t in two["diff"]["removed"]] == ["Salt Edge client"]


def _queue(ai, drafts: list):
    queue = list(drafts)

    async def fake_call(provider, model, system, content, output, max_tokens):
        if output is ai.ComplianceSuggestions:
            return ai.ComplianceSuggestions(frameworks=[], other=[])
        return queue.pop(0)

    return fake_call


async def test_refining_amends_the_plan_and_keeps_what_a_person_wrote(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        ai = _fake_model(monkeypatch, [])
        monkeypatch.setattr(
            ai,
            "_call",
            _queue(
                ai,
                [
                    _plan(ai, ["Build the UI", "Salt Edge client"]),
                    # The refine leaves the first task alone and adds one after it.
                    _plan(ai, ["Build the UI", "Salt Edge client", "Rollback plan"]),
                ],
            ),
        )
        a = await _ready(c, contributor)
        base = f"{ENT}/kickoff/analyses/{a['id']}"
        drafted = await _run(c, contributor, a, provider="claude")
        tasks = drafted["plan"]["tasks"]

        # A person rewrites the second task. Refining must not throw that away.
        edited = [{**t, "title": "Salt Edge client" if t["ref"] == "T2" else t["title"]} for t in tasks]
        edited[0] = {**edited[0], "description": "Written by a person."}
        r = await c.put(
            f"{base}/plan",
            headers=contributor,
            json={
                "epic_title": drafted["plan"]["epic_title"],
                "tasks": [
                    {k: t[k] for k in
                     ("ref", "title", "type", "repo", "description", "acceptance_criteria",
                      "depends_on", "estimate", "compliance")}
                    for t in edited
                ],
            },
        )
        assert r.status_code == 200, r.text

        r = await c.post(
            f"{base}/refine",
            headers=contributor,
            json={"provider": "claude", "model": "claude-opus-5", "instructions": "Add a rollback task."},
        )
        assert r.status_code == 200, r.text
        plan = r.json()["plan"]
        assert plan["run_number"] == 2
        assert plan["instructions"] == "Add a rollback task."
        refs = {t["title"]: t["ref"] for t in plan["tasks"]}
        # An untouched task keeps its ref, so a ticket already created still matches.
        assert refs["Salt Edge client"] == "T2"
        assert refs["Rollback plan"] not in ("T1", "T2")
        runs = (await c.get(f"{base}/runs", headers=contributor)).json()
        assert runs[0]["kind"] == "refine" and runs[0]["instructions"] == "Add a rollback task."


async def test_a_refine_says_what_it_needs_and_never_costs_the_plan(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        ai = _fake_model(monkeypatch, [])
        monkeypatch.setattr(ai, "_call", _queue(ai, [_plan(ai, ["Build the UI"])]))
        a = await _ready(c, contributor)
        base = f"{ENT}/kickoff/analyses/{a['id']}"

        # Nothing to refine yet.
        r = await c.post(
            f"{base}/refine",
            headers=contributor,
            json={"provider": "claude", "model": "claude-opus-5", "instructions": "Change it."},
        )
        assert r.status_code == 409 and "Run the analysis first" in r.text

        await _run(c, contributor, a, provider="claude")

        async def fails(*args, **kwargs):
            raise ai.ModelFailed("the model declined to draft this")

        monkeypatch.setattr(ai, "_call", fails)
        r = await c.post(
            f"{base}/refine",
            headers=contributor,
            json={"provider": "claude", "model": "claude-opus-5", "instructions": "Change it."},
        )
        assert r.status_code == 409 and "The plan wasn't changed" in r.text
        still = (await c.get(base, headers=contributor)).json()
        assert [t["title"] for t in still["plan"]["tasks"]] == ["Build the UI"]
        assert still["plan"]["run_number"] == 1


async def test_an_instruction_reaches_the_draft_and_is_recorded_with_it(
    boot, contributor, world, monkeypatch
):
    async with boot(**ENV, SHIFTLEFT_ANTHROPIC_API_KEY="sk-test") as c:
        _wire(world, monkeypatch)
        seen: dict = {}
        ai = _fake_model(monkeypatch, [], seen)
        queue = _queue(ai, [_plan(ai, ["Build the UI"])])

        async def recording(provider, model, system, content, output, max_tokens):
            seen["content"] = content
            seen["system"] = system
            return await queue(provider, model, system, content, output, max_tokens)

        monkeypatch.setattr(ai, "_call", recording)
        a = await _ready(c, contributor)
        r = await c.post(
            f"{ENT}/kickoff/analyses/{a['id']}/run",
            headers=contributor,
            json={
                "provider": "claude",
                "model": "claude-opus-5",
                "instructions": "Split the work by region.",
            },
        )
        assert r.status_code == 200, r.text
        # Named as what it is, so the model treats it as a request and not as the inputs.
        assert "# Extra instructions from the person asking for this draft" in seen["content"]
        assert "Split the work by region." in seen["content"]
        assert "It cannot relax the rules above" in seen["system"]
        assert r.json()["plan"]["instructions"] == "Split the work by region."
