"""Creating an analysis's tasks in a Jira backlog: the only write, and a named person's acceptance.

* **Preflight first.** Issue types are mapped (a Spike becomes a Task where the project has no
  Spike type) and fields Jira requires but this can't fill are named. If anything is missing,
  nothing is written.
* **In order.** The epic, then each task in the plan's order, so the backlog ranks them as planned.
  "Depends on" becomes a Blocks link.
* **Idempotent.** Every issue carries the analysis's label. A retry, or a re-run after the plan
  changed, finds what's already there by that label and summary instead of creating it twice.
* **Attributed.** Every description says who created it and that it was drafted by AI or rules.
"""

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.connectors.atlassian_rest import AtlassianError, AtlassianRest
from app.services.kickoff_sources import NotReadable, now

KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,19}$")
PROJECT_IN_PATH = re.compile(r"/projects/([A-Za-z][A-Za-z0-9_]{1,19})(?:/|$)")
BROWSE = re.compile(r"/browse/([A-Za-z][A-Za-z0-9_]{1,19})(?:-\d+)?(?:/|$)")
BOARD = re.compile(r"/boards/(\d+)")
# A task's type, then what to use instead when the project doesn't have it.
TYPE_CHOICES = {
    "Epic": ("Epic",),
    "Story": ("Story", "Task"),
    "Task": ("Task", "Story"),
    "Spike": ("Spike", "Task", "Story"),
}
# Fields this writer always sets, or that Jira fills itself.
FILLED = {"summary", "issuetype", "project", "reporter", "description", "labels", "parent"}
TRACKING_LABEL = "shiftleft-tracked"


class Refused(Exception):
    def __init__(self, message: str, blockers: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.blockers = blockers or []


def label_for(analysis_id: int) -> str:
    return f"shiftleft-kickoff-{analysis_id}"


def backlog_ref(url: str) -> dict[str, Any]:
    """The Jira site and project (and board, if any) from a backlog, board, project or issue link."""
    text = url.strip()
    if KEY.match(text.upper()) and "/" not in text:
        return {"url": text, "host": "", "project_key": text.upper(), "board_id": ""}
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    if not parsed.netloc:
        raise NotReadable("That isn't a Jira link. Paste the backlog's address from the browser.")
    found = PROJECT_IN_PATH.search(parsed.path) or BROWSE.search(parsed.path)
    key = found.group(1) if found else (parse_qs(parsed.query).get("projectKey") or [""])[0]
    if not key:
        raise NotReadable(
            "No project in that link. Open the backlog in Jira and copy its address; it contains "
            "/projects/<KEY>/."
        )
    board = BOARD.search(parsed.path)
    return {
        "url": url.strip(),
        "host": parsed.netloc.lower(),
        "project_key": key.upper(),
        "board_id": board.group(1) if board else "",
    }


# --- Descriptions (Atlassian Document Format) ---------------------------------------------------------


def _text(text: str, url: str = "") -> dict:
    node: dict[str, Any] = {"type": "text", "text": text}
    if url:
        node["marks"] = [{"type": "link", "attrs": {"href": url}}]
    return node


def _p(*nodes: dict) -> dict:
    return {"type": "paragraph", "content": list(nodes)}


def _h(text: str) -> dict:
    return {"type": "heading", "attrs": {"level": 3}, "content": [_text(text)]}


def _ul(items: list[str]) -> dict:
    return {"type": "bulletList", "content": [{"type": "listItem", "content": [_p(_text(i))]} for i in items]}


def _doc(blocks: list[dict]) -> dict:
    return {"type": "doc", "version": 1, "content": [b for b in blocks if b.get("content")]}


def _footer(ctx: dict[str, Any]) -> list[dict]:
    return [
        _p(_text("PRD: "), _text(ctx["prd_title"], ctx["prd_url"])),
        _p(
            _text(
                f"Drafted by {ctx['drafted_by']} in ShiftLeft Feature Kickoff "
                f"(analysis #{ctx['analysis_id']}); "
                f"reviewed and created by {ctx['actor']}."
            )
        ),
    ]


def epic_description(plan: dict[str, Any], ctx: dict[str, Any]) -> dict:
    blocks = [_p(_text(plan.get("epic_description") or plan.get("summary") or ctx["prd_title"]))]
    if plan.get("open_questions"):
        blocks += [_h("Open questions"), _ul(plan["open_questions"])]
    if plan.get("risks"):
        blocks += [_h("Risks"), _ul(plan["risks"])]
    return _doc(blocks + _footer(ctx))


def task_description(task: dict[str, Any], keys: dict[str, str], ctx: dict[str, Any]) -> dict:
    blocks = [_p(_text(task.get("description") or task["title"]))]
    if task.get("acceptance_criteria"):
        blocks += [_h("Acceptance criteria"), _ul(task["acceptance_criteria"])]
    if task.get("repo"):
        blocks.append(_p(_text("Repository: "), _text(task["repo"], ctx["repo_urls"].get(task["repo"], ""))))
    if task.get("depends_on"):
        blocks.append(
            _p(
                _text(
                    "Depends on: "
                    + ", ".join(f"{ref} ({keys[ref]})" if ref in keys else ref for ref in task["depends_on"])
                )
            )
        )
    if task.get("compliance"):
        blocks.append(
            _p(
                _text(
                    "Compliance: " + ", ".join(ctx["compliance_names"].get(k, k) for k in task["compliance"])
                )
            )
        )
    if task.get("quotes"):
        blocks += [
            _h("From the PRD"),
            _ul(
                [
                    f"Line {q['line']}"
                    + (f" ({q['section']})" if q.get("section") else "")
                    + f": {q['text']}"
                    for q in task["quotes"]
                ]
            ),
        ]
    return _doc(blocks + _footer(ctx))


# --- Writing ---------------------------------------------------------------------------------------------


async def preflight(jira: AtlassianRest, project: str, kinds: set[str]) -> tuple[dict[str, str], list[str]]:
    """Issue type ids per task type, or the reasons nothing can be created."""
    try:
        available = await jira.issue_types(project)
    except AtlassianError as exc:
        if exc.status == 404:
            return {}, [f"Project {project} wasn't found, or {jira.account} can't create issues in it."]
        return {}, [str(exc)]
    chosen: dict[str, str] = {}
    problems: list[str] = []
    for kind in sorted(kinds):
        name = next((n for n in TYPE_CHOICES[kind] if n in available), None)
        if name is None:
            problems.append(
                f"{project} has no {' or '.join(TYPE_CHOICES[kind])} issue type for {kind.lower()}s."
            )
            continue
        chosen[kind] = available[name]
    for kind, type_id in chosen.items():
        try:
            required = await jira.required_fields(project, type_id)
        except AtlassianError as exc:
            problems.append(str(exc))
            continue
        for f in required:
            if (f.get("key") or f.get("fieldId")) not in FILLED:
                problems.append(
                    f"{project} requires “{f.get('name') or f.get('key')}” on {kind.lower()}s, "
                    "which Feature Kickoff can't fill in. Make it optional or give it a default."
                )
    return chosen, problems


async def _create(jira: AtlassianRest, fields: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Create, and if Jira refuses the epic parent, create without it and say so."""
    try:
        return await jira.create_issue(fields), ""
    except AtlassianError as exc:
        if "parent" not in fields or exc.status != 400:
            raise
        issue = await jira.create_issue({k: v for k, v in fields.items() if k != "parent"})
        return issue, f" Not placed under the epic: {exc}"


async def create(
    jira: AtlassianRest,
    *,
    analysis_id: int,
    plan: dict[str, Any],
    ref: dict[str, Any],
    actor: str,
    drafted_by: str,
    prd: dict[str, Any],
    compliance_names: dict[str, str],
    repo_urls: dict[str, str],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    project = ref["project_key"]
    tasks = plan["tasks"]
    kinds = {"Epic", *(t["type"] for t in tasks)}
    type_ids, problems = await preflight(jira, project, kinds)
    if problems:
        raise Refused("Nothing was created: fix these in Jira first.", problems)

    label = label_for(analysis_id)
    try:
        found = await jira.search_issues(f'project = "{project}" AND labels = "{label}"')
    except AtlassianError as exc:
        raise Refused(
            "Nothing was created: Jira couldn't be searched for tickets already made.", [str(exc)]
        ) from exc
    existing = {i["summary"].strip().lower(): i for i in found}
    ctx = {
        "analysis_id": analysis_id,
        "actor": actor,
        "drafted_by": drafted_by,
        "prd_title": prd["title"],
        "prd_url": prd["url"],
        "compliance_names": compliance_names,
        "repo_urls": repo_urls,
    }
    labels = [label, TRACKING_LABEL]

    # The epic
    title = plan["epic_title"]
    epic: dict[str, Any]
    if title.strip().lower() in existing:
        hit = existing[title.strip().lower()]
        epic = {
            "ref": "epic",
            "title": title,
            "status": "exists",
            "key": hit["key"],
            "url": jira.issue_url(hit["key"]),
            "message": "Already in Jira from an earlier create.",
        }
    else:
        try:
            made = await jira.create_issue(
                {
                    "project": {"key": project},
                    "issuetype": {"id": type_ids["Epic"]},
                    "summary": title,
                    "description": epic_description(plan, ctx),
                    "labels": labels,
                }
            )
            epic = {
                "ref": "epic",
                "title": title,
                "status": "created",
                "key": made["key"],
                "url": made["url"],
                "message": "Created.",
            }
        except AtlassianError as exc:
            epic = {
                "ref": "epic",
                "title": title,
                "status": "failed",
                "key": "",
                "url": "",
                "message": str(exc),
            }

    # The tasks, in order
    keys: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    for task in tasks:
        summary = task["title"].strip()
        if summary.lower() in existing:
            hit = existing[summary.lower()]
            keys[task["ref"]] = hit["key"]
            results.append(
                {
                    "ref": task["ref"],
                    "title": summary,
                    "status": "exists",
                    "key": hit["key"],
                    "url": jira.issue_url(hit["key"]),
                    "message": "Already in Jira from an earlier create.",
                }
            )
            continue
        fields: dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"id": type_ids[task["type"]]},
            "summary": summary,
            "description": task_description(task, keys, ctx),
            "labels": labels,
        }
        if epic.get("key"):
            fields["parent"] = {"key": epic["key"]}
        try:
            made, note = await _create(jira, fields)
        except AtlassianError as exc:
            results.append(
                {
                    "ref": task["ref"],
                    "title": summary,
                    "status": "failed",
                    "key": "",
                    "url": "",
                    "message": str(exc),
                }
            )
            continue
        keys[task["ref"]] = made["key"]
        results.append(
            {
                "ref": task["ref"],
                "title": summary,
                "status": "created",
                "key": made["key"],
                "url": made["url"],
                "message": "Created." + note,
            }
        )

    # Order between tasks, as Blocks links
    link_note = ""
    wanted = [
        (dep, t["ref"]) for t in tasks for dep in t.get("depends_on", []) if dep in keys and t["ref"] in keys
    ]
    fresh = {r["ref"] for r in results if r["status"] == "created"}
    wanted = [(a, b) for a, b in wanted if a in fresh or b in fresh]
    if wanted:
        try:
            has_blocks = "Blocks" in await jira.link_types()
        except AtlassianError:
            has_blocks = False
        if not has_blocks:
            link_note = "Jira has no Blocks link type, so the order is in each description only."
        for blocker, blocked in wanted if has_blocks else []:
            try:
                await jira.link_outward("Blocks", keys[blocker], keys[blocked])
            except AtlassianError as exc:
                row = next(r for r in results if r["ref"] == blocked)
                row["message"] += f" Couldn't link {keys[blocker]} blocks {keys[blocked]}: {exc}"

    failed = sum(1 for r in [epic, *results] if r["status"] == "failed")
    return {
        "url": ref["url"],
        "site": jira.site,
        "project_key": project,
        "board_id": ref.get("board_id", ""),
        "label": label,
        "created_by": actor,
        "created_at": now(),
        "epic": epic,
        "tickets": results,
        "note": link_note,
        "failed": failed,
        "attempts": (previous or {}).get("attempts", 0) + 1,
    }
