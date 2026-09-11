"""Applying a confirmed plan: a dry run, or live writes to Jira, Xray and Confluence.

What holds for both writers:

* **Only the frozen plan is applied.** The plan a person confirmed is stored before anything is
  written; a retry applies that plan, never a recomputed one.
* **Every item ends with a result a person can act on:** created, updated, already there, handed
  off (with what to do), left out, or failed (with why). Nothing is dropped silently.

What holds for live writes:

* **Preflight before the first write.** Missing issue types or required fields the plan can't fill
  refuse the whole apply up front, rather than leaving half a backlog.
* **Idempotent.** Every issue carries the session's `sl-kickoff-<id>` label and is looked up by it
  before being created; every page is looked up by title. A retry after a failure, or after a
  crash between creating and recording, finds what exists instead of duplicating it.
* **Inside the project's boundary.** An API token acts as one account, so a kickoff writes only to
  its own project's Jira project and space, plus the configured software catalog page. Work for
  another team is drafted as a request and handed off: whether kickoff may write into other
  teams' projects is an open decision (proposal s11).
* **The catalog is edited, never rewritten,** and only if its version is still the one the plan
  was drafted against.
"""

import logging
from dataclasses import asdict, dataclass

from app.connectors.atlassian_rest import AtlassianError, AtlassianRest, adf
from app.connectors.xray_cloud import XrayCloud, XrayError
from app.services import confluence_storage as storage
from app.services import kickoff_pages as pages
from app.services.kickoff_plan import PlanItem, result_line

logger = logging.getLogger("shiftleft.kickoff")

# A result in one of these states is final: a retry leaves it alone.
NO_LOOKUP = ("Not attempted: couldn't check Jira for what this kickoff already created, so creating "
             "could duplicate it.")
DONE = {"created", "updated", "exists", "handoff", "skipped", "dry_run"}
# Fields the plan fills on every issue. A required field outside this set stops the apply.
FILLED_FIELDS = {"summary", "issuetype", "project", "reporter", "description", "labels", "parent"}
LEFT_OUT = "Left out of the plan by the person confirming it."
PAGE_KIND = {"suggestion:hld_page": ("hld", "HLD"), "suggestion:lld_page": ("lld", "LLD"),
             "suggestion:test_plan_page": ("test_plan", "Test plan")}


@dataclass
class Result:
    item_id: str
    group: str
    title: str
    status: str
    message: str
    link: dict | None = None
    issue_id: str = ""


@dataclass
class Context:
    session_id: int
    project_key: str
    actor: str
    feature: str
    prd: dict
    own_space: bool
    snapshot: dict
    # Everything the feasibility and starting pages show (built by the kickoff service).
    record: dict

    @property
    def label(self) -> str:
        return f"sl-kickoff-{self.session_id}"


def issue_type(item: dict) -> str:
    return {"Epic": "Epic", "Story": "Story"}.get(item["kind"], "Task")


def _result(item: dict, status: str, message: str, **kw) -> Result:
    return Result(item["id"], item["group"], item["title"], status, message, **kw)


class DryRun:
    mode = "dry-run"

    async def preflight(self, items: list[dict], ctx: Context) -> list[str]:
        return []

    async def apply(self, items: list[dict], previous: list[dict], ctx: Context) -> list[Result]:
        catalog, index = ctx.snapshot["catalog"]["version"], ctx.snapshot["index"]["version"]
        return [
            _result(i, "dry_run", result_line(PlanItem(**i), catalog, index)) if i["included"]
            else _result(i, "skipped", LEFT_OUT)
            for i in items
        ]


class Live:
    mode = "live"

    def __init__(self) -> None:
        self.atl = AtlassianRest()
        self.xray = XrayCloud()
        self._link_types: list[str] | None = None

    # -- before anything is written ----------------------------------------------------------

    def _own(self, item: dict, ctx: Context) -> bool:
        return item["project"] == ctx.project_key

    async def preflight(self, items: list[dict], ctx: Context) -> list[str]:
        todo = [i for i in items if i["included"]]
        jira = [i for i in todo if i["group"] == "jira" and self._own(i, ctx)]
        xray = [i for i in todo if i["group"] == "xray"]
        pages = [i for i in todo if i["group"] in ("confluence", "software_catalog")]
        touches_atlassian = jira or xray or pages
        if touches_atlassian and not self.atl.available:
            return [f"Jira and Confluence: {self.atl.unavailable_reason}"]
        problems = []
        if xray and not self.xray.available:
            problems.append(f"Xray: {self.xray.unavailable_reason}")
        needed = {issue_type(i) for i in jira} | ({"Test", "Test Plan"} if xray else set())
        if not needed:
            return problems
        try:
            types = await self.atl.issue_types(ctx.project_key)
            for name in sorted(needed):
                if name not in types:
                    hint = " Is Xray enabled on the project?" if name.startswith("Test") else ""
                    problems.append(
                        f"{ctx.project_key} has no “{name}” issue type this account can create.{hint}")
                elif not name.startswith("Test"):  # Xray fills its own issue types
                    for field in await self.atl.required_fields(ctx.project_key, types[name]):
                        fid = field.get("fieldId") or field.get("key")
                        if fid not in FILLED_FIELDS:
                            problems.append(
                                f"{ctx.project_key} {name} issues require “{field.get('name', fid)}”, which "
                                "the plan doesn't fill. Give it a default in Jira, or leave those items out."
                            )
        except AtlassianError as exc:
            problems.append(str(exc))
        return problems

    # -- the writes --------------------------------------------------------------------------

    async def apply(self, items: list[dict], previous: list[dict], ctx: Context) -> list[Result]:
        prior = {r["item_id"]: r for r in previous if r["status"] in DONE}
        out: dict[str, Result] = {}
        for item in items:
            if item["id"] in prior:
                out[item["id"]] = Result(**{k: prior[item["id"]].get(k) for k in Result.__dataclass_fields__
                                            if k in prior[item["id"]]})
            elif not item["included"]:
                out[item["id"]] = _result(item, "skipped", LEFT_OUT)
        todo = [i for i in items if i["id"] not in out]
        by_group: dict[str, list[dict]] = {}
        for item in todo:
            by_group.setdefault(item["group"], []).append(item)

        needs_lookup = bool(by_group.get("jira") or by_group.get("xray"))
        existing = await self._lookup(ctx) if needs_lookup else {}
        epic = await self._issues(by_group.get("jira", []), ctx, existing, out)
        test_plan_key = await self._xray(by_group.get("xray", []), ctx, existing, epic, out)
        await self._pages(by_group.get("confluence", []), ctx, epic, test_plan_key, out)
        await self._catalog(by_group.get("software_catalog", []), ctx, out)
        index_url = ctx.snapshot["index"].get("url")
        where = f"at {index_url}" if index_url else "to the product index by hand"
        for item in by_group.get("product_index", []):
            out[item["id"]] = _result(item, "handoff", f"Add this row {where}: the index has no writer yet.")
        for item in by_group.get("waivers", []):
            where = epic[0] if epic else "the epic"
            out[item["id"]] = _result(item, "handoff",
                                      f"Kept as a draft. Record its owner and rationale on Feature Readiness "
                                      f"against {where}. Scoped out is not passed.")
        return [out[i["id"]] for i in items]

    async def _lookup(self, ctx: Context) -> dict | None:
        """What this kickoff already created, by (project, summary). None if Jira can't say."""
        try:
            found = await self.atl.search_issues(f'labels = "{ctx.label}"')
        except AtlassianError as exc:
            logger.warning("Couldn't look up issues this kickoff created: %s", exc)
            return None
        return {(i["project"], i["summary"]): i for i in found}

    def _description(self, item: dict, ctx: Context) -> dict:
        drawn = [
            f"From the PRD: “{d['text']}”" if d["kind"] == "quote" else (d["text"], d["url"]) if d.get("url")
            else d["text"] for d in item.get("drawn_from", [])
        ]
        return adf(item.get("detail", ""), *drawn, (f"PRD: {ctx.prd['title']} (v{ctx.prd['version']})",
                                                     ctx.prd["url"]),
                   f"Created by ShiftLeft Feature Kickoff #{ctx.session_id}, confirmed by {ctx.actor}.")

    def _found(self, item: dict, found: dict) -> Result:
        return _result(item, "exists", f"Already created by this kickoff: {found['key']}.",
                       link={"label": found["key"], "url": self.atl.issue_url(found["key"])},
                       issue_id=found["id"])

    async def _create(self, item: dict, ctx: Context, existing: dict, parent: str = "") -> Result:
        summary = item["title"][:255]
        found = existing.get((ctx.project_key, summary))
        if found:
            return self._found(item, found)
        fields = {
            "project": {"key": ctx.project_key}, "issuetype": {"name": issue_type(item)}, "summary": summary,
            "labels": sorted(set(item["labels"]) | {ctx.label}), "description": self._description(item, ctx),
        }
        if parent:
            fields["parent"] = {"key": parent}
        created = await self.atl.create_issue(fields)
        message = f"Created {item['kind'].lower()} {created['key']} in {ctx.project_key}."
        return _result(item, "created", message, link={"label": created["key"], "url": created["url"]},
                       issue_id=created["id"])

    async def _link(self, type_name: str, source: str, target: str) -> str:
        """A note for the result: linked, or why not. A link that can't be made never fails the item."""
        try:
            if self._link_types is None:
                self._link_types = await self.atl.link_types()
            if type_name not in self._link_types:
                return f" Not linked: this Jira has no “{type_name}” link type."
            await self.atl.link_outward(type_name, source, target)
            return f" Linked to {target}."
        except AtlassianError as exc:
            return f" Not linked to {target}: {exc}"

    async def _issues(self, todo: list[dict], ctx: Context, existing: dict | None,
                      out: dict[str, Result]) -> tuple[str, str] | None:
        """Create the epic, then its children. Returns (epic key, epic id) if there is an epic."""
        epic_result = out.get("epic")
        epic_item = next((i for i in todo if i["id"] == "epic"), None)
        if todo and existing is None:
            for item in todo:
                out[item["id"]] = _result(item, "failed", NO_LOOKUP)
            return None
        if epic_item:
            try:
                epic_result = await self._create(epic_item, ctx, existing)
            except AtlassianError as exc:
                epic_result = _result(epic_item, "failed", str(exc))
            out["epic"] = epic_result
        epic = ((epic_result.link or {}).get("label", ""), epic_result.issue_id) \
            if epic_result and epic_result.status in ("created", "exists") else None
        # A person may leave the epic out; then children are created without a parent.
        epic_planned = epic_result is not None and epic_result.status != "skipped"
        for item in todo:
            if item["id"] == "epic":
                continue
            if not self._own(item, ctx):
                out[item["id"]] = _result(
                    item, "handoff",
                    f"Drafted as a request for {item['project']}: this kickoff writes only to "
                    f"{ctx.project_key}. Send it to the owning team.")
                continue
            if epic_planned and not epic:
                reason = "Not attempted: the epic wasn't created, so this would be orphaned."
                out[item["id"]] = _result(item, "failed", reason)
                continue
            try:
                result = await self._create(item, ctx, existing, parent=epic[0] if epic else "")
                if item["kind"] == "Dependency" and epic and result.status == "created":
                    result.message += await self._link("Blocks", result.link["label"], epic[0])
                out[item["id"]] = result
            except AtlassianError as exc:
                out[item["id"]] = _result(item, "failed", str(exc))
        return epic

    async def _xray(self, todo: list[dict], ctx: Context, existing: dict | None,
                    epic: tuple[str, str] | None, out: dict[str, Result]) -> str:
        if not todo:
            plan = out.get("xray:plan")
            return (plan.link or {}).get("label", "") if plan else ""
        if existing is None:
            for item in todo:
                out[item["id"]] = _result(item, "failed", NO_LOOKUP)
            return ""
        labels = sorted({*todo[0]["labels"], ctx.label})
        for item in [i for i in todo if i["id"].startswith("xray:test:")]:
            found = existing.get((ctx.project_key, item["title"][:255]))
            try:
                if found:
                    out[item["id"]] = self._found(item, found)
                    continue
                test = await self.xray.create_test(ctx.project_key, item["title"][:255], labels)
                message = f"Created test {test.key}."
                if epic:
                    message += await self._link("Test", test.key, epic[0])
                out[item["id"]] = _result(item, "created", message,
                                          link={"label": test.key, "url": self.atl.issue_url(test.key)},
                                          issue_id=test.issue_id)
            except XrayError as exc:
                out[item["id"]] = _result(item, "failed", str(exc))
        plan_item = next((i for i in todo if i["id"] == "xray:plan"), None)
        if not plan_item:
            return ""
        tests = [r.issue_id for k, r in out.items()
                 if k.startswith("xray:test:") and r.status in ("created", "exists") and r.issue_id]
        found = existing.get((ctx.project_key, plan_item["title"][:255]))
        try:
            if found:
                result = self._found(plan_item, found)
            else:
                title = plan_item["title"][:255]
                made = await self.xray.create_test_plan(ctx.project_key, title, labels, tests)
                message = f"Created test plan {made.key} with {len(tests)} test(s)."
                result = _result(plan_item, "created", message,
                                 link={"label": made.key, "url": self.atl.issue_url(made.key)},
                                 issue_id=made.issue_id)
        except XrayError as exc:
            result = _result(plan_item, "failed", str(exc))
        out[plan_item["id"]] = result
        return (result.link or {}).get("label", "")

    async def _pages(self, todo: list[dict], ctx: Context, epic: tuple[str, str] | None, test_plan_key: str,
                     out: dict[str, Result]) -> None:
        for item in todo:
            if not ctx.own_space:
                out[item["id"]] = _result(
                    item, "handoff",
                    f"Drafted for the {ctx.prd['space']} space: this kickoff writes only to "
                    f"{ctx.project_key}'s own space.")
                continue
            kind, prefix = PAGE_KIND.get(item["id"], ("feasibility", ""))
            title = f"{prefix} — {ctx.feature}" if prefix else item["title"]
            record = {**ctx.record, "test_plan_key": test_plan_key}
            body = (pages.feasibility(record, epic[0] if epic else "") if kind == "feasibility"
                    else pages.starting_page(kind, record, epic[0] if epic else ""))
            try:
                found = await self.atl.find_page(ctx.prd["space"], title)
                if found:
                    message = f"A page called “{title}” already exists; left as it is."
                    link = {"label": "Open page", "url": found["url"]}
                    out[item["id"]] = _result(item, "exists", message, link=link)
                    continue
                made = await self.atl.create_page(ctx.prd["space"], title, body, parent_id=ctx.prd["page_id"])
                message = f"Created “{title}” under the PRD."
                try:
                    await self.atl.add_labels(made["id"], item["labels"])
                except AtlassianError as exc:
                    message += f" Labels not added: {exc}"
                link = {"label": "Open page", "url": made["url"]}
                out[item["id"]] = _result(item, "created", message, link=link)
            except AtlassianError as exc:
                out[item["id"]] = _result(item, "failed", str(exc))

    async def _catalog(self, todo: list[dict], ctx: Context, out: dict[str, Result]) -> None:
        if not todo:
            return
        drafted = ctx.snapshot["catalog"]
        if not drafted["available"]:
            reason = (f"The catalog couldn't be read when the plan was drafted ({drafted['note']}), so "
                      "there's nothing to apply it to.")
            for item in todo:
                out[item["id"]] = _result(item, "failed", reason)
            return
        try:
            page = await self.atl.page(drafted["page_id"])
        except AtlassianError as exc:
            for item in todo:
                out[item["id"]] = _result(item, "failed", str(exc))
            return
        if page.version != drafted["version"]:
            reason = (f"The catalog page changed since the plan was drafted (v{drafted['version']} → "
                      f"v{page.version}). Nothing was written to it. Start a new kickoff to draft against "
                      "the current page.")
            for item in todo:
                out[item["id"]] = _result(item, "failed", reason)
            return
        body, applied = page.storage, []
        for item in todo:
            diff = item.get("diff") or {}
            try:
                if diff.get("op") == "add":
                    name = str(diff["fields"].get("name", ""))
                    if any(r["name"].lower() == name.lower() for r in storage.catalog_table(body).rows):
                        out[item["id"]] = _result(item, "exists", f"{name} is already a row on the catalog.")
                        continue
                    body = storage.add_row(body, {k: str(v) for k, v in diff["fields"].items()})
                else:
                    body = storage.set_cell(body, diff["row"], diff["field"], ", ".join(diff["after"]))
                applied.append(item)
            except (storage.TableUnreadable, KeyError) as exc:
                reason = f"Not applied: {exc} Recorded here for the catalog owner."
                out[item["id"]] = _result(item, "handoff", reason)
        if not applied:
            return
        try:
            version = await self.atl.update_page(
                page, body, f"Feature Kickoff #{ctx.session_id}, confirmed by {ctx.actor}")
        except AtlassianError as exc:
            for item in applied:
                out[item["id"]] = _result(item, "failed", f"Nothing was written to the catalog: {exc}")
            return
        for item in applied:
            verb = "Added to" if item["diff"]["op"] == "add" else "Changed on"
            out[item["id"]] = _result(item, "updated", f"{verb} the software catalog (now v{version}).",
                                      link={"label": f"{page.title} v{version}", "url": page.url})


def writer(mode: str) -> DryRun | Live:
    return Live() if mode == "live" else DryRun()


def dump(results: list[Result]) -> list[dict]:
    return [asdict(r) for r in results]
