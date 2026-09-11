"""Feature Kickoff against live systems, stood in by a fake Confluence, Jira, GitHub and Xray.

The fake answers the documented REST and GraphQL shapes, so these tests pin down what the live
readers and writers send and what they do with the answers: a page read from storage format, a
catalog table edited without touching the rest of the page, a preflight that stops before the
first write, a retry that doesn't duplicate, and work for another team handed off, not written.
"""

import json
import re
from html import escape
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

ENT = "/api/projects/entitlements"
SITE = "https://example.atlassian.net"
PRD_ID = "9100001"
CATALOG_ID = "5100200"
TOKEN = "atl-token-never-shown"
FEATURE = "Account information API for regulated third parties (UK)"

LIVE = {
    "SHIFTLEFT_KICKOFF_SOURCES": "live",
    "SHIFTLEFT_KICKOFF_WRITE_MODE": "live",
    "SHIFTLEFT_ATLASSIAN_SITE_URL": SITE,
    "SHIFTLEFT_ATLASSIAN_EMAIL": "kickoff-bot@backbase.com",
    "SHIFTLEFT_ATLASSIAN_API_TOKEN": TOKEN,
    "SHIFTLEFT_SOFTWARE_CATALOG_PAGE_ID": CATALOG_ID,
    "SHIFTLEFT_GITHUB_TOKEN": "gh-token",
    "SHIFTLEFT_XRAY_CLIENT_ID": "xray-id",
    "SHIFTLEFT_XRAY_CLIENT_SECRET": "xray-secret",
    "SHIFTLEFT_PRODUCT_INDEX_URL": "",
}

PRD_LINES = [
    "## Summary",
    "Regulated third-party providers (TPPs) can read UK customers' account and transaction data "
    "through a new Account Information API.",
    "## Context",
    "This is a new external API and a new trust boundary.",
    "Customers authorise access during the TPP's redirect flow; the authorisation screens are out of "
    "scope for this PRD and the API has no UI of its own.",
    "## Features",
    "- List the accounts a customer has consented to share",
    "- Read balances and transactions for a consented account",
    "## Acceptance criteria",
    "- A TPP with a valid consent can list the customer's accounts.",
    "- A revoked consent stops all access within 1 minute.",
    "## Dependencies",
    "- Uses the consent-service to validate consents (GET /consents/{id}).",
    "- Uses the account-service to read balances (GET /accounts/{id}/balances).",
    "- Uses the transaction-service to read transactions (GET /accounts/{id}/transactions).",
    "## Third parties",
    "- Ledgerly (launch partner, account aggregator)",
    "## Data",
    "Responses carry account data and personal data (PII).",
]


def storage_of(lines: list[str]) -> str:
    """The PRD as Confluence stores it, with a macro whose parameter must not be read as prose."""
    out = ['<ac:structured-macro ac:name="toc"><ac:parameter ac:name="maxLevel">2</ac:parameter>'
           "</ac:structured-macro>"]
    in_list = False
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


CATALOG_BEFORE = "<h2>Services</h2><p>Owned by Architecture &amp; kept by hand.</p>" \
    '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>One row per deployable.</p>' \
    "</ac:rich-text-body></ac:structured-macro>"
CATALOG_TABLE = (
    '<table data-layout="default"><tbody>'
    "<tr><th><p>Component</p></th><th><p>Owner</p></th><th><p>Jira project</p></th>"
    "<th><p>Repository</p></th><th><p>Spec path</p></th><th><p>Status</p></th>"
    "<th><p>Planned operations</p></th></tr>"
    "<tr><td><p>consent-service</p></td><td><p>Entitlements</p></td><td><p>ENT</p></td>"
    '<td><p><a href="https://github.com/backbase/consent-service">backbase/consent-service</a></p></td>'
    "<td><p>spec/consent-api.yaml</p></td><td><p>Live</p></td><td><p /></td></tr>"
    '<tr><td colspan="1"><p>account-service</p></td><td><p>Nucleus</p></td><td><p>NUC</p></td>'
    "<td><p>backbase/account-service</p></td><td><p>api/openapi.yaml</p></td><td><p>Live</p></td>"
    "<td><p /></td></tr>"
    "</tbody></table>"
)
CATALOG_AFTER = "<p>Last reviewed in August.</p>"

SPECS = {
    "backbase/consent-service": ("spec/consent-api.yaml", """
openapi: 3.0.3
info: {title: Consent service, version: 1.4.0}
paths:
  /consents: {post: {summary: Create}}
  /consents/{id}: {get: {summary: Read}, delete: {summary: Revoke}}
"""),
    "backbase/account-service": ("api/openapi.yaml", """
openapi: 3.0.3
info: {title: Account service, version: 4.2.0}
paths:
  /accounts: {get: {summary: List}}
  /accounts/{id}: {get: {summary: Read}}
  /accounts/{id}/balances: {get: {summary: Balances, deprecated: true}}
"""),
}


class World:
    """A fake Atlassian site, GitHub, Xray and Cursor, answering the documented shapes."""

    def __init__(self) -> None:
        self.spaces = {"10": "ENT", "20": "ARCH", "30": "NUC"}
        self.pages = {
            PRD_ID: {"title": "PRD — Account information API for regulated third parties (UK)",
                     "spaceId": "10", "version": 9, "storage": storage_of(PRD_LINES), "parentId": ""},
            CATALOG_ID: {"title": "Software catalog", "spaceId": "20", "version": 31,
                         "storage": CATALOG_BEFORE + CATALOG_TABLE + CATALOG_AFTER, "parentId": ""},
        }
        self.labels: dict[str, list[str]] = {}
        self.issues: list[dict] = []
        self.links: list[dict] = []
        self.required: list[dict] = []
        self.fail_once: set[str] = set()
        self.reversed_links = False
        self.graphql: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.index_html = "<html><body><table><tr><td>Account overview</td></tr></table></body></html>"
        self._ids = 100

    def _id(self) -> str:
        self._ids += 1
        return str(self._ids)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        self.calls.append((request.method, f"{url.netloc}{url.path}"))
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.netloc == "example.atlassian.net":
            assert request.headers["authorization"].startswith("Basic ")
            return self._atlassian(request, url.path, query)
        if url.netloc == "api.github.com":
            return self._github(url.path, query)
        if url.netloc == "xray.cloud.getxray.app":
            return self._xray(request, url.path)
        if url.netloc == "api.cursor.com":
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"items": [
                {"id": "gpt-5", "displayName": "GPT-5"},
                {"id": "claude-opus-5", "displayName": "Claude Opus 5"}]})
        if url.netloc == "software.backbase.eu":
            return httpx.Response(200, text=self.index_html)
        return httpx.Response(404)

    # -- Confluence and Jira ----------------------------------------------------------------

    def _page_json(self, pid: str, body: bool) -> dict:
        page = self.pages[pid]
        out = {"id": pid, "title": page["title"], "spaceId": page["spaceId"], "parentId": page["parentId"],
               "version": {"number": page["version"], "createdAt": "2026-09-01T10:00:00Z"},
               "_links": {"webui": f"/spaces/{self.spaces[page['spaceId']]}/pages/{pid}"}}
        if body:
            out["body"] = {"storage": {"representation": "storage", "value": page["storage"]}}
        return out

    def _atlassian(self, request: httpx.Request, path: str, query: dict) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        method = request.method
        if path == "/wiki/rest/api/search":
            assert 'label = "sl-requirements"' in query["cql"]
            page = self.pages[PRD_ID]
            return httpx.Response(200, json={"results": [{
                "content": {"id": PRD_ID, "type": "page", "title": page["title"], "space": {"key": "ENT"},
                            "version": {"number": page["version"], "by": {"displayName": "M. Okonjo"}},
                            "_links": {"webui": f"/spaces/ENT/pages/{PRD_ID}"}},
                "lastModified": "2026-08-22T09:00:00Z"}]})
        if m := re.fullmatch(r"/wiki/api/v2/pages/(\d+)", path):
            pid = m.group(1)
            if pid not in self.pages:
                return httpx.Response(404, json={"errors": [{"title": "Not found"}]})
            if method == "GET":
                return httpx.Response(200, json=self._page_json(pid, query.get("body-format") == "storage"))
            if body["version"]["number"] != self.pages[pid]["version"] + 1:
                return httpx.Response(409, json={"errors": [{"title": "Version conflict"}]})
            self.pages[pid].update(version=body["version"]["number"], storage=body["body"]["value"])
            return httpx.Response(200, json=self._page_json(pid, False))
        if m := re.fullmatch(r"/wiki/api/v2/spaces/(\d+)", path):
            return httpx.Response(200, json={"id": m.group(1), "key": self.spaces[m.group(1)]})
        if path == "/wiki/api/v2/spaces":
            found = [{"id": i, "key": k} for i, k in self.spaces.items() if k == query["keys"]]
            return httpx.Response(200, json={"results": found})
        if path == "/wiki/api/v2/pages" and method == "GET":
            found = [self._page_json(i, False) for i, p in self.pages.items()
                     if p["spaceId"] == query["space-id"] and p["title"] == query["title"]]
            return httpx.Response(200, json={"results": found})
        if path == "/wiki/api/v2/pages" and method == "POST":
            pid = self._id()
            self.pages[pid] = {"title": body["title"], "spaceId": body["spaceId"], "version": 1,
                               "storage": body["body"]["value"], "parentId": body.get("parentId", "")}
            return httpx.Response(200, json=self._page_json(pid, False))
        if m := re.fullmatch(r"/wiki/rest/api/content/(\d+)/label", path):
            self.labels.setdefault(m.group(1), []).extend(label["name"] for label in body)
            return httpx.Response(200, json={"results": body})
        if path == "/rest/api/3/issue/createmeta/ENT/issuetypes":
            names = ["Epic", "Story", "Task", "Test", "Test Plan"]
            types = [{"id": str(i), "name": n} for i, n in enumerate(names)]
            return httpx.Response(200, json={"issueTypes": types})
        if re.fullmatch(r"/rest/api/3/issue/createmeta/ENT/issuetypes/\d+", path):
            base = [{"fieldId": f, "name": f, "required": True, "hasDefaultValue": False}
                    for f in ("summary", "issuetype", "project")]
            return httpx.Response(200, json={"fields": base + self.required})
        if path == "/rest/api/3/search/jql":
            label = re.search(r'labels = "([^"]+)"', query["jql"]).group(1)
            hits = [i for i in self.issues if label in i["labels"]]
            return httpx.Response(200, json={"issues": [
                {"id": i["id"], "key": i["key"],
                 "fields": {"summary": i["summary"], "project": {"key": i["project"]},
                            "issuetype": {"name": i["issuetype"]}}} for i in hits]})
        if path == "/rest/api/3/issue" and method == "POST":
            fields = body["fields"]
            if fields["summary"] in self.fail_once:
                self.fail_once.discard(fields["summary"])
                return httpx.Response(400, json={"errorMessages": [], "errors": {"summary": "Jira was busy"}})
            return httpx.Response(201, json=self._new_issue(
                fields["project"]["key"], fields["summary"], fields["issuetype"]["name"],
                fields.get("labels", []), (fields.get("parent") or {}).get("key", ""),
                fields.get("description")))
        if path == "/rest/api/3/issueLinkType":
            return httpx.Response(200, json={"issueLinkTypes": [
                {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                {"name": "Test", "inward": "is tested by", "outward": "tests"}]})
        if path == "/rest/api/3/issueLink" and method == "POST":
            self.links.append({"id": self._id(), "type": body["type"]["name"],
                               "inward": body["inwardIssue"]["key"], "outward": body["outwardIssue"]["key"]})
            return httpx.Response(201)
        if m := re.fullmatch(r"/rest/api/3/issueLink/(\d+)", path):
            self.links = [link for link in self.links if link["id"] != m.group(1)]
            return httpx.Response(204)
        if m := re.fullmatch(r"/rest/api/3/issue/([A-Z]+-\d+)", path):
            links = self._links_on(m.group(1))
            return httpx.Response(200, json={"key": m.group(1), "fields": {"issuelinks": links}})
        return httpx.Response(404, json={"errorMessages": [f"No fake for {method} {path}"]})

    def _new_issue(self, project, summary, issuetype, labels, parent="", description=None) -> dict:
        number = sum(1 for i in self.issues if i["project"] == project) + 1
        issue = {"id": self._id(), "key": f"{project}-{number}", "project": project, "summary": summary,
                 "issuetype": issuetype, "labels": labels, "parent": parent, "description": description}
        self.issues.append(issue)
        return {"id": issue["id"], "key": issue["key"], "self": f"{SITE}/rest/api/3/issue/{issue['id']}"}

    def _links_on(self, key: str) -> list[dict]:
        """One Jira presents a link from each end. `reversed_links` flips which end is which."""
        entries = []
        for link in self.links:
            if key not in (link["inward"], link["outward"]):
                continue
            other = link["outward"] if key == link["inward"] else link["inward"]
            sees_outward = (key == link["inward"]) != self.reversed_links
            side = "outwardIssue" if sees_outward else "inwardIssue"
            entries.append({"id": link["id"], "type": {"name": link["type"]}, side: {"key": other}})
        return entries

    def outward_from(self, source: str, type_name: str) -> list[str]:
        return [e["outwardIssue"]["key"] for e in self._links_on(source)
                if e["type"]["name"] == type_name and "outwardIssue" in e]

    # -- GitHub and Xray --------------------------------------------------------------------

    def _github(self, path: str, query: dict) -> httpx.Response:
        if m := re.fullmatch(r"/repos/([^/]+/[^/]+)/commits/HEAD", path):
            return httpx.Response(200, text="9f8e7d6c5b4a39281706f5e4d3c2b1a098765432") \
                if m.group(1) in SPECS else httpx.Response(404)
        if m := re.fullmatch(r"/repos/([^/]+/[^/]+)/contents/(.+)", path):
            repo, file = m.group(1), m.group(2)
            if repo in SPECS and SPECS[repo][0] == file and query.get("ref", "").startswith("9f8e"):
                return httpx.Response(200, text=SPECS[repo][1])
        return httpx.Response(404)

    def _xray(self, request: httpx.Request, path: str) -> httpx.Response:
        if path == "/api/v2/authenticate":
            assert json.loads(request.content) == {"client_id": "xray-id", "client_secret": "xray-secret"}
            return httpx.Response(200, text='"xray-jwt"')
        assert request.headers["authorization"] == "Bearer xray-jwt"
        body = json.loads(request.content)
        self.graphql.append(body)
        fields = body["variables"]["jira"]["fields"]
        kind = "Test Plan" if "createTestPlan" in body["query"] else "Test"
        made = self._new_issue(fields["project"]["key"], fields["summary"], kind, fields["labels"])
        node = {"issueId": made["id"], "jira": {"key": made["key"]}}
        name, key = ("createTestPlan", "testPlan") if kind == "Test Plan" else ("createTest", "test")
        if kind == "Test Plan":
            self.issues[-1]["tests"] = body["variables"]["tests"]
        return httpx.Response(200, json={"data": {name: {key: node, "warnings": []}}})


@pytest.fixture
def world():
    return World()


async def _live(boot, world, **env):
    """Boot with live settings, and route every outbound call to the fake."""
    context = boot(**{**LIVE, **env})
    client = await context.__aenter__()
    from app.connectors import http as outbound

    outbound.transport = httpx.MockTransport(world.handle)
    return context, client


async def _planned(client, headers, accept: tuple[str, ...] = ()) -> dict:
    started = await client.post(f"{ENT}/kickoff", headers=headers,
                                json={"page_id": PRD_ID, "provider": "rules", "model": "rules"})
    assert started.status_code == 201, started.text
    session = started.json()
    choices = [{"key": a["key"], "selected": a["selected"], "skip_reason": ""} for a in session["actions"]]
    planned = await client.put(f"{ENT}/kickoff/{session['id']}/actions", headers=headers,
                               json={"choices": choices})
    assert planned.status_code == 200, planned.text
    if accept:
        planned = await client.put(f"{ENT}/kickoff/{session['id']}/plan", headers=headers,
                                   json={"decisions": dict.fromkeys(accept, "accepted")})
    return planned.json()


def _result(session: dict, item_id: str) -> dict:
    return next(r for r in session["results"] if r["item_id"] == item_id)


# --- Reading live -------------------------------------------------------------------------------


async def test_prds_are_listed_from_confluence_by_label_and_read_from_storage_format(boot, world, admin):
    context, client = await _live(boot, world)
    try:
        listed = (await client.get(f"{ENT}/kickoff/prds", headers=admin)).json()
        assert listed["available"] and listed["pages"][0]["page_id"] == PRD_ID
        assert listed["pages"][0]["own_project"] and listed["pages"][0]["author"] == "M. Okonjo"

        session = (await client.post(f"{ENT}/kickoff", headers=admin,
                                     json={"page_id": PRD_ID, "provider": "rules", "model": "rules"})).json()
        assert session["source_mode"] == "live" and session["page"]["version"] == 9
        stated = [f for f in session["facts"] if f["status"] == "stated"]
        assert stated
        for fact in stated:  # every quote is a sentence of the page as stored, never the macro's "2"
            for quote in fact["quotes"]:
                assert escape(quote["text"]) in world.pages[PRD_ID]["storage"]
        assert all(q["text"] != "2" for f in session["facts"] for q in f["quotes"])
    finally:
        await context.__aexit__(None, None, None)


async def test_live_checks_read_the_catalog_table_and_each_spec_at_a_pinned_commit(boot, world, admin):
    context, client = await _live(boot, world)
    try:
        planned = await _planned(client, admin)
        findings = {f["id"]: f for c in planned["checks"] for f in c["findings"]}
        consent = findings["dependency:consent-service:GET /consents/{id}"]
        assert consent["status"] == "ok"
        assert consent["link"]["url"] == ("https://github.com/backbase/consent-service/blob/"
                                          "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432/spec/consent-api.yaml")
        assert findings["dependency:account-service:GET /accounts/{id}/balances"]["status"] == "gap"
        # Not in the catalog: not checked, with the catalog page as the place to fix it.
        missing = findings["dependency:transaction-service:GET /accounts/{id}/transactions"]
        assert missing["status"] == "not_checked" and "v31" in missing["link"]["label"]
        # No vendor is registered in the live registry, so nothing about Ledgerly is assumed.
        assert findings["third_party:Ledgerly:docs"]["status"] == "not_checked"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_spec_that_cannot_be_read_is_not_checked_rather_than_passed(boot, world, admin):
    context, client = await _live(boot, world)
    SPECS_BACKUP = dict(SPECS)
    SPECS.pop("backbase/consent-service")
    try:
        planned = await _planned(client, admin)
        finding = next(f for c in planned["checks"] for f in c["findings"]
                       if f["id"] == "dependency:consent-service:GET /consents/{id}")
        assert finding["status"] == "not_checked"
        assert "couldn't be read" in finding["title"] and "wasn't found" in finding["detail"]
    finally:
        SPECS.update(SPECS_BACKUP)
        await context.__aexit__(None, None, None)


# --- Writing live -------------------------------------------------------------------------------


async def test_confirming_creates_the_backlog_tests_and_pages_and_edits_only_the_catalog_table(
    boot, world, admin
):
    context, client = await _live(boot, world)
    try:
        planned = await _planned(client, admin, accept=("hld_page",))
        sid = planned["id"]
        applied = await client.post(f"{ENT}/kickoff/{sid}/apply", headers=admin)
        assert applied.status_code == 200, applied.text
        session = applied.json()
        assert session["status"] == "applied" and session["write_mode"] == "live"
        assert session["approved_by"] == admin["X-ShiftLeft-User"]

        label = f"sl-kickoff-{sid}"
        epic = next(i for i in world.issues if i["issuetype"] == "Epic")
        assert _result(session, "epic")["link"] == {"label": epic["key"],
                                                    "url": f"{SITE}/browse/{epic['key']}"}
        children = [i for i in world.issues if i["issuetype"] in ("Story", "Task")]
        assert children and all(i["parent"] == epic["key"] for i in children)
        assert all(label in i["labels"] and i["project"] == "ENT" for i in world.issues)
        # Who confirmed it travels with every issue.
        assert admin["X-ShiftLeft-User"] in json.dumps(epic["description"])

        tests = [i for i in world.issues if i["issuetype"] == "Test"]
        plan = next(i for i in world.issues if i["issuetype"] == "Test Plan")
        assert len(tests) == 2 and plan["tests"] == [t["id"] for t in tests]
        # PRD text reaches Xray as a variable, never spliced into the mutation.
        for call in world.graphql:
            assert "consent" not in call["query"].lower()
        assert all(world.outward_from(t["key"], "Test") == [epic["key"]] for t in tests)

        created = {p["title"]: (pid, p) for pid, p in world.pages.items() if pid not in (PRD_ID, CATALOG_ID)}
        feasibility_id, feasibility = created[f"Feasibility — {FEATURE}"]
        assert feasibility["parentId"] == PRD_ID and world.labels[feasibility_id] == ["sl-feasibility"]
        assert "Berlin Group" in feasibility["storage"] and "Not applicable" in feasibility["storage"]
        assert epic["key"] in feasibility["storage"]
        assert f"HLD — {FEATURE}" in created

        catalog = world.pages[CATALOG_ID]
        assert catalog["version"] == 32
        assert catalog["storage"].startswith(CATALOG_BEFORE) and catalog["storage"].endswith(CATALOG_AFTER)
        assert CATALOG_TABLE[:-len("</tbody></table>")] in catalog["storage"]  # existing rows untouched
        assert "<td><p>Account Information API</p></td>" in catalog["storage"]
        assert _result(session, "catalog:account-information-api")["status"] == "updated"

        # No writer for the index yet, and waivers need a person: handed off, never dropped.
        assert _result(session, "index:feature")["status"] == "handoff"
        assert all(r["status"] != "failed" for r in session["results"])
    finally:
        await context.__aexit__(None, None, None)


async def test_preflight_refuses_before_anything_is_written(boot, world, admin):
    context, client = await _live(boot, world)
    world.required = [{"fieldId": "customfield_10020", "name": "Team", "required": True,
                       "hasDefaultValue": False}]
    try:
        planned = await _planned(client, admin)
        refused = await client.post(f"{ENT}/kickoff/{planned['id']}/apply", headers=admin)
        assert refused.status_code == 409
        assert any("Team" in b for b in refused.json()["detail"]["blockers"])
        assert world.issues == [] and world.pages[CATALOG_ID]["version"] == 31
        again = (await client.get(f"{ENT}/kickoff/{planned['id']}", headers=admin)).json()
        assert again["status"] == "planned" and again["approved_by"] is None
    finally:
        await context.__aexit__(None, None, None)


async def test_a_partial_failure_is_retried_without_duplicating_what_was_created(boot, world, admin):
    context, client = await _live(boot, world)
    try:
        planned = await _planned(client, admin)
        story = next(i for i in planned["plan"]["items"] if i["id"] == "story:1")
        world.fail_once = {story["title"]}

        first = (await client.post(f"{ENT}/kickoff/{planned['id']}/apply", headers=admin)).json()
        assert first["status"] == "partial"
        failed = _result(first, "story:1")
        assert failed["status"] == "failed" and "Jira was busy" in failed["message"]
        created_before = len(world.issues)

        retried = (await client.post(f"{ENT}/kickoff/{planned['id']}/apply", headers=admin)).json()
        assert retried["status"] == "applied"
        assert _result(retried, "story:1")["status"] == "created"
        assert len(world.issues) == created_before + 1
        assert sum(1 for i in world.issues if i["issuetype"] == "Epic") == 1
        # The retry applied the frozen plan, confirmed once, by the same person.
        assert retried["approved_by"] == first["approved_by"]
    finally:
        await context.__aexit__(None, None, None)


async def test_an_issue_created_before_a_crash_is_found_not_duplicated(boot, world, admin):
    context, client = await _live(boot, world)
    try:
        planned = await _planned(client, admin)
        sid = planned["id"]
        epic_title = next(i["title"] for i in planned["plan"]["items"] if i["id"] == "epic")
        # As if a previous attempt created the epic and died before recording it.
        world._new_issue("ENT", epic_title, "Epic", [f"sl-kickoff-{sid}"])
        session = (await client.post(f"{ENT}/kickoff/{sid}/apply", headers=admin)).json()
        assert _result(session, "epic")["status"] == "exists"
        assert sum(1 for i in world.issues if i["issuetype"] == "Epic") == 1
    finally:
        await context.__aexit__(None, None, None)


async def test_the_catalog_is_left_alone_if_it_changed_since_the_plan_was_drafted(boot, world, admin):
    context, client = await _live(boot, world)
    try:
        planned = await _planned(client, admin)
        world.pages[CATALOG_ID]["version"] = 32  # someone edited it by hand in between
        before = world.pages[CATALOG_ID]["storage"]
        session = (await client.post(f"{ENT}/kickoff/{planned['id']}/apply", headers=admin)).json()
        result = _result(session, "catalog:account-information-api")
        assert result["status"] == "failed" and "v31 → v32" in result["message"]
        assert world.pages[CATALOG_ID]["storage"] == before
        assert session["status"] == "partial"
    finally:
        await context.__aexit__(None, None, None)


async def test_work_for_another_team_is_drafted_as_a_request_not_written(boot, world, admin):
    context, client = await _live(boot, world)
    try:
        deprecation = "deprecation:account-service:GET /accounts/{id}/balances"
        planned = await _planned(client, admin, accept=(deprecation,))
        session = (await client.post(f"{ENT}/kickoff/{planned['id']}/apply", headers=admin)).json()
        result = _result(session, f"suggestion:{deprecation}")
        assert result["status"] == "handoff" and "NUC" in result["message"]
        assert not any(i["project"] == "NUC" for i in world.issues)
    finally:
        await context.__aexit__(None, None, None)


async def test_a_link_jira_records_backwards_is_made_again_the_right_way(boot, world, admin):
    context, client = await _live(boot, world)
    world.reversed_links = True
    try:
        planned = await _planned(client, admin)
        await client.post(f"{ENT}/kickoff/{planned['id']}/apply", headers=admin)
        epic = next(i for i in world.issues if i["issuetype"] == "Epic")
        tests = [i for i in world.issues if i["issuetype"] == "Test"]
        assert all(world.outward_from(t["key"], "Test") == [epic["key"]] for t in tests)
        assert any(m == "DELETE" for m, _ in world.calls)
        assert len(world.links) == len(tests)
    finally:
        await context.__aexit__(None, None, None)


# --- The product index, until its parser is written ----------------------------------------------


async def test_the_product_index_reads_as_unavailable_until_its_parser_is_written(boot, world, admin):
    context, client = await _live(boot, world, SHIFTLEFT_PRODUCT_INDEX_URL="https://software.backbase.eu/product/index")
    try:
        connections = (await client.get(f"{ENT}/kickoff/connections", headers=admin)).json()
        index = next(c for c in connections["connections"] if c["key"] == "product_index")
        assert index["state"] == "not_built" and "product_index_parser.py" in index["note"]

        planned = await _planned(client, admin)
        item = next(i for i in planned["plan"]["items"] if i["id"] == "index:feature")
        assert "couldn't be read" in item["detail"] and "isn't written yet" in item["detail"]
        session = (await client.post(f"{ENT}/kickoff/{planned['id']}/apply", headers=admin)).json()
        assert _result(session, "index:feature")["status"] == "handoff"
    finally:
        await context.__aexit__(None, None, None)


async def test_once_the_parser_is_written_a_listed_feature_is_not_added_again(
    boot, world, admin, monkeypatch
):
    context, client = await _live(boot, world, SHIFTLEFT_PRODUCT_INDEX_URL="https://software.backbase.eu/product/index")
    from app.connectors import product_index_parser as parser

    monkeypatch.setattr(parser, "WRITTEN", True)
    monkeypatch.setattr(parser, "parse", lambda document, url: parser.ParsedIndex(
        [parser.IndexFeature(FEATURE, "Open Banking", "Beta")],
        "2026.3"))
    try:
        planned = await _planned(client, admin)
        assert not any(i["id"] == "index:feature" for i in planned["plan"]["items"])
        assert any("already lists" in n for n in planned["plan"]["notes"])
        assert planned["plan"]["index_version"] == "2026.3"
    finally:
        await context.__aexit__(None, None, None)


# --- Configuration --------------------------------------------------------------------------------


async def test_connections_say_where_reads_and_writes_go_and_never_show_a_credential(boot, world, admin):
    context, client = await _live(boot, world)
    try:
        response = await client.get(f"{ENT}/kickoff/connections", headers=admin)
        body = response.json()
        assert body["sources"] == "live" and body["write_mode"] == "live"
        states = {c["key"]: c["state"] for c in body["connections"]}
        assert states["confluence"] == "configured" and states["index_write"] == "not_built"
        for secret in (TOKEN, "gh-token", "xray-secret"):
            assert secret not in response.text
    finally:
        await context.__aexit__(None, None, None)


async def test_example_pages_are_labelled_and_create_is_a_dry_run_by_default(client, admin):
    body = (await client.get(f"{ENT}/kickoff/connections", headers=admin)).json()
    assert body["sources"] == "fixtures" and body["write_mode"] == "dry-run"
    assert {c["state"] for c in body["connections"]} >= {"example", "dry_run"}


async def test_cursor_models_are_listed_from_the_teams_account_but_not_run_here(boot, world, admin):
    context, client = await _live(boot, world, SHIFTLEFT_CURSOR_API_KEY="cursor-key")
    try:
        response = await client.get(f"{ENT}/kickoff/models", headers=admin)
        cursor = next(p for p in response.json()["providers"] if p["key"] == "cursor")
        assert [m["id"] for m in cursor["models"]] == ["gpt-5", "claude-opus-5"]
        assert cursor["available"] is False and "run in the editor" in cursor["note"]
        assert "cursor-key" not in response.text
        refused = await client.post(f"{ENT}/kickoff", headers=admin,
                                    json={"page_id": PRD_ID, "provider": "cursor", "model": "gpt-5"})
        assert refused.status_code == 422
    finally:
        await context.__aexit__(None, None, None)


def test_a_session_that_read_example_pages_cannot_write_live(monkeypatch):
    from app.models.kickoff import KickoffSession
    from app.services import kickoff

    monkeypatch.setattr(kickoff, "write_mode", lambda: "live")
    row = KickoffSession(id=1, status="planned", data={"source_mode": "fixtures"})
    with pytest.raises(kickoff.Refused, match="example pages"):
        kickoff.prepare_apply(row, None, [])


# --- The pieces -----------------------------------------------------------------------------------


def test_storage_format_is_read_into_sections_bullets_and_table_rows():
    from app.services.confluence_storage import body_lines

    lines = body_lines(
        '<ac:structured-macro ac:name="toc"><ac:parameter ac:name="x">3</ac:parameter></ac:structured-macro>'
        "<h2>Features</h2><ul><li><p>Send &amp; receive</p></li><li>Revoke<ul><li>nested</li></ul></li></ul>"
        "<table><tr><th><p>A</p></th><th><p>B</p></th></tr><tr><td><p>1</p></td><td><p>2</p></td></tr></table>"
    )
    assert lines == ["## Features", "- Send & receive", "- Revoke", "- nested", "A | B", "1 | 2"]


def test_a_catalog_edit_changes_one_cell_and_leaves_every_other_byte():
    from app.services import confluence_storage as storage

    page = CATALOG_BEFORE + CATALOG_TABLE + CATALOG_AFTER
    table = storage.catalog_table(page)
    assert [r["name"] for r in table.rows] == ["consent-service", "account-service"]
    assert table.rows[0]["repo"] == "backbase/consent-service"
    edited = storage.set_cell(page, "account-service", "planned", "GET /accounts/{id}/statements")
    assert edited.replace("<td><p>GET /accounts/{id}/statements</p></td>", "<td><p /></td>") == page
    with pytest.raises(storage.TableUnreadable):
        storage.set_cell(page, "no-such-service", "planned", "x")


def test_a_page_without_a_readable_catalog_table_is_refused_not_guessed():
    from app.services import confluence_storage as storage

    with pytest.raises(storage.TableUnreadable):
        storage.catalog_table("<table><tr><th>Name</th><th>Owner</th></tr></table>")


def test_openapi_operations_and_deprecations_come_from_the_spec_alone():
    from app.connectors import openapi

    spec = openapi.parse(SPECS["backbase/account-service"][1])
    assert "GET /accounts/{id}/balances" in spec.operations
    assert spec.deprecated == ["GET /accounts/{id}/balances"]
    with pytest.raises(openapi.SpecUnreadable):
        openapi.parse("title: not an api")
