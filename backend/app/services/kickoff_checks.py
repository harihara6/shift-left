"""Feature Kickoff's read-only checks. Each one runs only when the person kept it selected.

A finding is `ok`, `gap`, `blocker` or `not_checked`, and every one links to what it read. The
summary never says a PRD is feasible: it says where no blocker was found and what wasn't checked
(docs/PROPOSAL-PRD-Intake.md s7, rule 1). A check that could not look is a gap, not a pass.
"""

from dataclasses import asdict, dataclass, field

from app.schemas.common import RagState
from app.services.kickoff_extract import Line, Structure
from app.services.kickoff_rules import ACTION_BY_KEY, STANDARD_FOR_ACTION
from app.services.kickoff_sources import Snap

FINDING_STATES = ("ok", "gap", "blocker", "not_checked")


@dataclass
class Finding:
    id: str
    status: str
    title: str
    detail: str = ""
    link: dict | None = None
    quote: dict | None = None


@dataclass
class CheckResult:
    key: str
    label: str
    note: str = ""
    findings: list[Finding] = field(default_factory=list)

    @property
    def looked(self) -> bool:
        return any(f.status != "not_checked" for f in self.findings)


def dependency_check(shape: Structure, snap: Snap) -> CheckResult:
    result = CheckResult("dependency_check", ACTION_BY_KEY["dependency_check"].label,
                         "Each operation the PRD relies on, against the owning service's API spec in GitHub.")
    if not shape.dependencies:
        result.findings.append(Finding(
            "dependency:none", "not_checked", "The PRD names no internal service to check",
            "Answer the question on the context step, or deselect this check with a reason.",
        ))
        return result
    catalog = snap.catalog
    for dep in shape.dependencies:
        service, operation = dep["service"], dep["operation"]
        fid = f"dependency:{service}:{operation or '-'}"
        if not catalog["available"]:
            result.findings.append(Finding(
                fid, "not_checked", f"{service} couldn't be looked up", catalog["note"], None, dep["quote"],
            ))
            continue
        item = snap.component(service)
        if item is None:
            result.findings.append(Finding(
                fid, "not_checked", f"{service} isn't in the software catalog",
                "Without a catalog entry there is no repository or spec to read. Check the name, or "
                "add the service to the catalog.",
                snap.catalog_link(), dep["quote"],
            ))
            continue
        spec = item["spec"]
        if not spec["read"]:
            result.findings.append(Finding(
                fid, "not_checked", f"{service}'s API spec couldn't be read", spec["note"],
                {"label": item["repo"], "url": spec["url"]} if spec["url"] else snap.catalog_link(),
                dep["quote"],
            ))
            continue
        link = {"label": f"{item['repo']} @ {spec['commit']}", "url": spec["url"]}
        if not operation:
            result.findings.append(Finding(
                fid, "gap", f"The PRD names {service} but not the operation it needs",
                "Add the method and path to the PRD so the spec can be checked.", link, dep["quote"],
            ))
        elif operation in spec["deprecated"]:
            result.findings.append(Finding(
                fid, "gap", f"{operation} is deprecated in {service}",
                f"It still exists, but {item['owner']} has marked it for removal. Agree a replacement "
                "before building on it.",
                link, dep["quote"],
            ))
        elif operation in spec["operations"]:
            result.findings.append(Finding(
                fid, "ok", f"{operation} exists in {service}", f"Owned by {item['owner']}.",
                link, dep["quote"],
            ))
        else:
            result.findings.append(Finding(
                fid, "blocker", f"{operation} doesn't exist in {service}",
                f"Not in the service's API spec. {item['owner']} ({item['jira_project']}) would have to "
                "build it first.",
                link, dep["quote"],
            ))
    return result


def third_party_check(parties: list[str], snap: Snap) -> CheckResult:
    result = CheckResult("third_party_check", ACTION_BY_KEY["third_party_check"].label,
                         "Each third party's published docs, as last retrieved.")
    if not parties:
        result.findings.append(Finding(
            "third_party:none", "not_checked", "No third party is named in the PRD",
            "Answer the question on the context step to name the scheme or provider.",
        ))
        return result
    for name in parties:
        item = snap.vendor(name)
        if item is None:
            result.findings.append(Finding(
                f"third_party:{name}:docs", "not_checked", f"No published docs are registered for {name}",
                "Nothing to read, so nothing is assumed. Confirm their API docs, sandbox and support.",
            ))
            continue
        link = {"label": f"{name} docs, retrieved {item['retrieved']}", "url": item["docs_url"]}
        for row in item["findings"]:
            result.findings.append(Finding(
                f"third_party:{name}:{row['aspect'].lower().replace(' ', '_')}", row["status"],
                f"{name}: {row['aspect']}", row["text"], link,
            ))
        result.findings.append(Finding(
            f"third_party:{name}:commercial", "not_checked",
            f"{name}: contract and commercial status",
            "Not checkable from documentation. Ask the partnership owner.",
        ))
    return result


def standard_check(action: str, lines: list[Line], snap: Snap) -> CheckResult:
    key = STANDARD_FOR_ACTION[action]
    spec = snap.standard(key)
    label = ACTION_BY_KEY[action].label
    if spec is None or not spec["pinned"]:
        reason = (spec or {}).get("not_pinned_reason") or "No version of this standard is pinned."
        return CheckResult(action, label, "Nothing pinned to check against.", [
            Finding(f"{key}:unpinned", "not_checked", f"{label} is not pinned", reason,
                    {"label": "Standard's home page", "url": spec["source"]} if spec else None),
        ])
    result = CheckResult(
        action, label,
        f"Pinned: {spec['version']}. Checked against the PRD's text, not code: the API design isn't "
        "written yet. Alignment only; this never certifies.",
    )
    link = {"label": spec["version"], "url": spec["source"]}
    for clause in spec["clauses"]:
        hit = next(
            (ln for ln in lines if any(word in ln.text.lower() for word in clause["look_for"])), None
        )
        if hit:
            result.findings.append(Finding(
                f"{key}:{clause['key']}", "ok", clause["label"], "The PRD covers it.", link,
                {"text": hit.text, "section": hit.section},
            ))
        else:
            result.findings.append(Finding(
                f"{key}:{clause['key']}", "gap", clause["label"],
                "The PRD doesn't cover this yet. Add an acceptance criterion, or record why it doesn't "
                "apply.",
                link,
            ))
    return result


def run(
    selected: list[str], shape: Structure, lines: list[Line], parties: list[str], snap: Snap
) -> list[CheckResult]:
    results: list[CheckResult] = []
    if "dependency_check" in selected:
        results.append(dependency_check(shape, snap))
    if "third_party_check" in selected:
        results.append(third_party_check(parties, snap))
    for action in STANDARD_FOR_ACTION:
        if action in selected:
            results.append(standard_check(action, lines, snap))
    return results


def dump(results: list[CheckResult]) -> list[dict]:
    return [
        {"key": r.key, "label": r.label, "note": r.note, "findings": [asdict(f) for f in r.findings]}
        for r in results
    ]


def load(data: list[dict]) -> list[CheckResult]:
    return [
        CheckResult(r["key"], r["label"], r["note"], [Finding(**f) for f in r["findings"]])
        for r in data
    ]


def headline(results: list[CheckResult]) -> RagState:
    """Reasons, never a verdict. There is no 'feasible': only what was found and what wasn't looked at."""
    if not results:
        return RagState.of("neutral", ["No checks were selected, so nothing was verified."])
    blockers = [f for r in results for f in r.findings if f.status == "blocker"]
    gaps = [f for r in results for f in r.findings if f.status == "gap"]
    unchecked = [f for r in results for f in r.findings if f.status == "not_checked"]
    clean = [r.label for r in results
             if r.looked and not any(f.status in ("blocker", "gap") for f in r.findings)]

    reasons = [f"Blocker: {f.title}." for f in blockers]
    reasons += [f"Gap: {f.title}." for f in gaps]
    if clean:
        reasons.append(f"No blockers or gaps found in: {', '.join(clean)}.")
    if unchecked:
        reasons.append(f"Not checked: {'; '.join(f.title for f in unchecked)}.")

    if blockers:
        return RagState.of("poor", reasons)
    if not any(r.looked for r in results):
        return RagState.of("missing", reasons)
    if gaps or unchecked:
        return RagState.of("watch", reasons)
    # Even all-clear is a list of what was looked at, never a statement that the PRD is feasible.
    return RagState.of("good", reasons)
