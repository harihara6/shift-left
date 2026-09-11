"""Feature Kickoff: recommended next steps, and the plan of everything that would be written.

The plan is computed from what is stored (facts, choices, findings, decisions) on every read,
never stored itself until it is applied. Item ids are derived from content, so a person's
"leave this out" survives a recompute.

Every item says what it was drawn from, a PRD quote, a finding, or the tier rule, because a
ticket nobody can trace back is a claim, not a plan (product rule 3). Nothing here writes.
"""

import re
from dataclasses import asdict, dataclass, field

from app.services.kickoff_checks import CheckResult
from app.services.kickoff_extract import Structure
from app.services.kickoff_rules import (
    ACTION_BY_KEY,
    STANDARD_FOR_ACTION,
    TIER_REQUIRES,
    Facts,
    Tier,
    accessibility_in_scope,
)
from app.services.kickoff_sources import Snap

# How the plan covers each artifact the tier requires. "task" is an evidence task in Jira.
COVERED_BY: dict[str, str] = {
    "requirements": "epic", "acceptance_criteria": "stories", "traceability": "xray",
    "test_evidence": "xray",
}
# The Confluence template label each document-shaped artifact is created from (CLAUDE.md
# conventions: proposed, not observed — confirm with the teams).
TEMPLATE_LABEL: dict[str, str] = {
    "test_plan": "sl-test-plan", "hld": "sl-hld", "lld": "sl-lld", "threat_model": "sl-threat-model",
    "performance": "sl-performance", "accessibility": "sl-accessibility",
}
TRACKED = "shiftleft-tracked"
DENIED_NOTE = (
    "Rationale and owner are recorded by a person. “Capacity pressure” is not an acceptable rationale."
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def feature_name(prd: dict) -> str:
    return re.sub(r"^PRD\s*[—-]\s*", "", prd["title"]).strip()


# --- Suggestions --------------------------------------------------------------------------------


@dataclass
class Suggestion:
    key: str
    label: str
    why: str
    target: str
    source: str  # "context" (from the facts and tier) or "check" (from a finding)
    kind: str
    project: str = ""
    drawn_from: list[dict] = field(default_factory=list)


def context_suggestions(facts: Facts, tier: Tier, shape: Structure, project_key: str) -> list[Suggestion]:
    out: list[Suggestion] = []
    required = set(TIER_REQUIRES[tier.tier])
    rule = {"kind": "rule", "text": f"{tier.tier}: {tier.reason}"}
    if "hld" in required:
        out.append(Suggestion("hld_page", "Create the HLD page",
                              "The HLD is due at Ready for this tier (PRD §6).", "Confluence", "context",
                              "page", project_key, [rule]))
    if "lld" in required:
        services = facts["services"].values if facts.get("services") else []
        scope = f" covering {', '.join(services)}" if services else ""
        out.append(Suggestion("lld_page", f"Create the LLD page{scope}",
                              "The LLD is drafted at Ready and complete at Done (PRD §6).", "Confluence",
                              "context", "page", project_key, [rule]))
    if "test_plan" in required:
        out.append(Suggestion("test_plan_page", "Create the test plan page, including NFR testing",
                              "The test plan is due at Ready (PRD §6).", "Confluence", "context", "page",
                              project_key, [rule]))
    sensitive = [v for v in (facts["data_classes"].values if facts.get("data_classes") else [])
                 if v in ("payment_data", "pii", "credentials")]
    boundary = facts.get("change_kind") and "trust_boundary" in facts["change_kind"].values
    if "threat_model" in required and (sensitive or boundary):
        reason = "It carries sensitive data" if sensitive else "It adds a trust boundary"
        evidence_key = "data_classes" if sensitive else "change_kind"
        drawn = [_quote(q) for q in facts[evidence_key].quotes[:1]] + [rule]
        out.append(Suggestion(
            "threat_model_session", "Book a threat-model session",
            f"{reason}. Tracked as presence and status only; the model itself stays in Confluence.",
            "Jira", "context", "task", project_key, drawn,
        ))
    return out


def finding_suggestions(checks: list[CheckResult], snap: Snap) -> list[Suggestion]:
    out: list[Suggestion] = []
    for check in checks:
        for finding in check.findings:
            drawn = [{"kind": "finding", "text": finding.title, "url": (finding.link or {}).get("url", "")}]
            if check.key == "dependency_check":
                parts = finding.id.split(":", 2)
                if len(parts) < 3:
                    continue
                _, service, operation = parts
                item = snap.component(service)
                if finding.status == "blocker" and item:
                    out.append(Suggestion(
                        f"dependency:{service}:{operation}",
                        f"Raise a dependency ticket in {item['jira_project']} for {operation} on {service}",
                        f"{item['owner']} has to build it before this feature can use it.",
                        "Jira", "check", "dependency", item["jira_project"], drawn))
                elif finding.status == "gap" and item and operation in item["spec"]["deprecated"]:
                    out.append(Suggestion(
                        f"deprecation:{service}:{operation}",
                        f"Agree a replacement for deprecated {operation} with {item['owner']}",
                        "Building on a deprecated operation schedules rework.",
                        "Jira", "check", "dependency", item["jira_project"], drawn))
                elif finding.status == "not_checked" and snap.catalog["available"] and item is None:
                    out.append(Suggestion(
                        f"catalog_entry:{service}", f"Add {service} to the software catalog",
                        "It isn't listed, so nobody can check its API or find its owner.",
                        "Software catalog", "check", "catalog_row", "", drawn))
            elif check.key == "third_party_check":
                parts = finding.id.split(":")
                if finding.status == "gap":
                    out.append(Suggestion(
                        f"spike:{parts[1]}:{parts[2]}", f"Spike: {finding.title}", finding.detail,
                        "Jira", "check", "spike", "", drawn))
                elif parts[-1] == "docs":
                    out.append(Suggestion(
                        f"spike:{parts[1]}:docs",
                        f"Spike: confirm {parts[1]}'s API docs, sandbox and support",
                        "Nothing is registered to read.", "Jira", "check", "spike", "", drawn))
            elif check.key in STANDARD_FOR_ACTION:
                std = STANDARD_FOR_ACTION[check.key]
                if finding.status == "gap":
                    out.append(Suggestion(
                        f"standard_gap:{finding.id}", f"Add an acceptance criterion for: {finding.title}",
                        f"{check.label} expects it and the PRD doesn't cover it yet.", "Jira", "check",
                        "story", "", drawn))
                elif finding.status == "not_checked":
                    out.append(Suggestion(
                        f"standard_access:{std}", f"Confirm access to the {check.label} specification",
                        finding.detail, "Jira", "check", "task", "", drawn))
        if check.key in STANDARD_FOR_ACTION:
            spec = snap.standard(STANDARD_FOR_ACTION[check.key])
            if spec and spec.get("conformance"):
                out.append(Suggestion(
                    f"conformance:{spec['key']}", f"Plan {check.label} conformance testing",
                    spec["conformance"], "Jira", "check", "task", "",
                    [{"kind": "rule", "text": spec["conformance"], "url": spec["source"]}]))
    return out


# --- The plan -----------------------------------------------------------------------------------


@dataclass
class PlanItem:
    id: str
    group: str  # jira | xray | confluence | software_catalog | product_index | waivers
    kind: str
    title: str
    detail: str = ""
    project: str = ""
    labels: list[str] = field(default_factory=list)
    drawn_from: list[dict] = field(default_factory=list)
    diff: dict | None = None
    included: bool = True


@dataclass
class Coverage:
    artifact: str
    name: str
    gate: str
    state: str  # covered | waiver_draft | not_applicable | not_covered
    item_id: str | None
    note: str = ""


@dataclass
class Plan:
    items: list[PlanItem]
    coverage: list[Coverage]
    notes: list[str]


def _quote(q: dict) -> dict:
    return {"kind": "quote", "text": q["text"], "section": q.get("section", "")}


def build(
    *,
    project_key: str,
    project_name: str,
    prd: dict,
    facts: Facts,
    shape: Structure,
    tier: Tier,
    selected: list[str],
    checks: list[CheckResult],
    suggestions: list[Suggestion],
    decisions: dict[str, str],
    excluded: set[str],
    artifacts: list[dict],
    snap: Snap,
) -> Plan:
    items: list[PlanItem] = []
    coverage: list[Coverage] = []
    notes: list[str] = []
    name = feature_name(prd)
    tier_label = f"sl-tier-{_slug(tier.tier)}"
    page = {"kind": "source", "text": f"{prd['title']} (v{prd['version']})", "url": prd["url"]}
    rule = {"kind": "rule", "text": f"{tier.tier}: {tier.reason}"}

    # Jira: the epic, a story per feature, and the evidence tasks the tier needs.
    if "jira_backlog" in selected:
        items.append(PlanItem("epic", "jira", "Epic", name, shape.summary, project_key,
                              [TRACKED, tier_label], [page]))
        stories = shape.features or ([{"text": name, "quote": {"text": shape.summary, "section": "Summary"}}]
                                     if shape.summary else [])
        for i, story in enumerate(stories, start=1):
            items.append(PlanItem(f"story:{i}", "jira", "Story", story["text"], "Child of the epic.",
                                  project_key, [TRACKED], [_quote(story["quote"])]))

    required = set(TIER_REQUIRES[tier.tier])
    a11y = accessibility_in_scope(facts)
    for artifact in artifacts:
        key = artifact["key"]
        covered = COVERED_BY.get(key, "task")
        if key == "accessibility" and a11y is False:
            coverage.append(Coverage(key, artifact["name"], artifact["gate"], "not_applicable", None,
                                     f"No web or mobile channel: {facts['channels'].shown()}."))
            continue
        if key not in required:
            wid = f"waiver:{key}"
            items.append(PlanItem(wid, "waivers", "Waiver draft", f"Scope out: {artifact['name']}",
                                  f"{tier.tier} lets this be scoped down with a recorded rationale. "
                                  f"{DENIED_NOTE}",
                                  project_key, [], [rule]))
            coverage.append(Coverage(key, artifact["name"], artifact["gate"], "waiver_draft", wid))
            continue
        if covered == "xray" and "xray_plan" not in selected:
            covered = "task"
        if "jira_backlog" not in selected and covered in ("epic", "stories", "task"):
            coverage.append(Coverage(key, artifact["name"], artifact["gate"], "not_covered", None,
                                     "The Jira backlog isn't selected, so nothing in this plan covers it."))
            continue
        item_id = {"epic": "epic", "stories": "story:1", "xray": "xray:plan"}.get(covered, f"evidence:{key}")
        if covered == "task":
            status_only = key == "threat_model"
            detail = (
                f"Evidence for {name}. Accountable: {artifact['accountable']}. Due at {artifact['gate']}."
                + (" Presence and status only: the content stays in Confluence." if status_only else "")
            )
            labels = [TRACKED, "sl-evidence", f"sl-artifact-{key.replace('_', '-')}",
                      f"sl-gate-{artifact['gate'].lower()}", tier_label]
            if key in TEMPLATE_LABEL:
                labels.append(TEMPLATE_LABEL[key])
            items.append(PlanItem(item_id, "jira", "Evidence task", artifact["name"], detail, project_key,
                                  labels, [rule]))
        coverage.append(Coverage(key, artifact["name"], artifact["gate"], "covered", item_id))

    # Xray: a plan, and a test drafted from each acceptance criterion.
    if "xray_plan" in selected:
        items.append(PlanItem("xray:plan", "xray", "Test plan", f"Test plan — {name}",
                              "Tests are linked to the epic, so traceability exists from day one.",
                              project_key, [TRACKED], [page]))
        for i, ac in enumerate(shape.acceptance_criteria, start=1):
            items.append(PlanItem(
                f"xray:test:{i}", "xray", "Test", ac["text"],
                "Level tag (@L1–@L4) is left for the SDET to assign; the PRD doesn't state it.",
                project_key, [TRACKED], [_quote(ac["quote"])]))
        if not shape.acceptance_criteria:
            notes.append("The PRD has no acceptance criteria section, so no tests could be drafted.")

    if "feasibility_page" in selected:
        items.append(PlanItem(
            "page:feasibility", "confluence", "Page", f"Feasibility — {name}",
            "The facts with their quotes, every rule outcome including what was ruled out and why, and "
            "every finding with its link. Page Properties carry the epic key and status.",
            prd["space"], ["sl-feasibility"], [page]))

    # Recommended steps a person accepted.
    for s in suggestions:
        if decisions.get(s.key) != "accepted":
            continue
        group = {"Confluence": "confluence", "Software catalog": "software_catalog"}.get(s.target, "jira")
        if group == "software_catalog":
            continue  # folded into the catalog diff below
        labels = [TRACKED] if group == "jira" else []
        if s.key in ("hld_page", "lld_page", "test_plan_page"):
            labels = [TEMPLATE_LABEL[s.key.removesuffix("_page")]]
        items.append(PlanItem(f"suggestion:{s.key}", group, s.kind.replace("_", " ").capitalize(), s.label,
                              s.why, s.project or (prd["space"] if group == "confluence" else project_key),
                              labels, s.drawn_from))

    # Software catalog: a diff, never a rewrite, against the page version that was read.
    if "software_catalog" in selected:
        catalog = snap.catalog
        by_service: dict[str, list[str]] = {}
        for check in checks:
            if check.key != "dependency_check":
                continue
            for finding in check.findings:
                if finding.status == "blocker":
                    _, service, operation = finding.id.split(":", 2)
                    by_service.setdefault(service, []).append(operation)
        for service, operations in by_service.items():
            item = snap.component(service)
            if item is None:
                continue
            planned = item.get("planned", [])
            items.append(PlanItem(
                f"catalog:{service}", "software_catalog", "Catalog row", f"Change {service}",
                "Recorded as planned on the service's row until its owner ships them.", "",
                [], [{"kind": "finding", "text": f"{op} doesn't exist yet"} for op in operations],
                {"op": "change", "field": "planned", "label": "Planned operations", "row": item["name"],
                 "before": planned, "after": planned + [op for op in operations if op not in planned]}))
        new_api = facts.get("introduces_api") and "yes" in facts["introduces_api"].values
        if new_api or (facts.get("change_kind") and "new_service" in facts["change_kind"].values):
            api = shape.api_name or f"{name} API"
            standards = [ACTION_BY_KEY[a].label for a in STANDARD_FOR_ACTION if a in selected]
            items.append(PlanItem(
                f"catalog:{_slug(api)}", "software_catalog", "Catalog row", f"Add {api}",
                "A new row, owned by this project, status Planned.", "", [],
                [_quote(q) for q in facts["introduces_api"].quotes[:1]] or [page],
                {"op": "add", "fields": {
                    "name": api, "owner": project_name, "jira_project": project_key, "status": "Planned",
                    "depends_on": ", ".join(facts["services"].values) or "none named",
                    "standards": ", ".join(standards) or "none selected",
                }}))
        for s in suggestions:
            if s.target == "Software catalog" and decisions.get(s.key) == "accepted":
                service = s.key.split(":", 1)[1]
                items.append(PlanItem(
                    f"catalog:{service}", "software_catalog", "Catalog row", f"Add {service}",
                    "Owner and repository to confirm; added so the service can be checked next time.",
                    "", [], s.drawn_from,
                    {"op": "add",
                     "fields": {"name": service, "owner": "To confirm", "status": "To confirm"}}))
        if not catalog["available"]:
            notes.append(f"The software catalog couldn't be read: {catalog['note']} Rows below were drafted "
                         "without it, and can't be applied until it can be read.")
        elif not any(i.group == "software_catalog" for i in items):
            notes.append(f"No software catalog rows change. Read {catalog['title']} v{catalog['version']}.")

    if "product_index" in selected:
        index = snap.index
        listed = next((f for f in index["features"] if f["feature"].strip().lower() == name.lower()), None)
        if listed:
            notes.append(f"The product index already lists {listed['feature']} ({listed.get('product', '')}, "
                         f"{listed.get('status') or 'no status'}), so no row is added.")
        else:
            detail = (f"New row on {index['title']} (read at {index['version']})." if index["available"] else
                      f"The product index couldn't be read. {index['note']} So it isn't known whether this "
                      "feature is already listed: check before adding it.")
            items.append(PlanItem(
                "index:feature", "product_index", "Index row", f"Add {name}", detail, "", [], [page],
                {"op": "add", "fields": {
                    "feature": name, "product": project_name, "status": "Planned",
                    "capabilities": "; ".join(f["text"] for f in shape.features) or shape.summary,
                }}))

    for item in items:
        item.included = item.id not in excluded
    return Plan(items, coverage, notes)


def result_line(item: PlanItem, catalog_version: int, index_version: str) -> str:
    """What applying this item does. In this slice every write is a dry run, and says so."""
    if item.group == "jira":
        return f"Would create {item.kind} in {item.project}: {item.title}"
    if item.group == "xray":
        return f"Would create Xray {item.kind.lower()} in {item.project}: {item.title}"
    if item.group == "confluence":
        return f"Would create a Confluence page in {item.project}: {item.title}"
    if item.group == "software_catalog":
        verb = item.diff["op"] if item.diff else "change"
        return f"Would {verb} a row on the software catalog (v{catalog_version}): {item.title}"
    if item.group == "product_index":
        return f"Would add a row to the product index ({index_version or 'not read'}): {item.title}"
    return f"Would record a draft waiver awaiting a rationale: {item.title}"


def dump(plan: Plan) -> dict:
    return {"items": [asdict(i) for i in plan.items], "coverage": [asdict(c) for c in plan.coverage],
            "notes": plan.notes}
