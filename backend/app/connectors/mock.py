"""A mock adapter standing in for every real connector until each is built.

It answers the full contract so Settings -> Connectors is functionally real: testing a
connection, previewing a query and reading capabilities all work end to end. What it never
does is invent data that a real source would not have returned - an unrecognised query comes
back empty, and empty renders as a gap.
"""

from datetime import datetime, timezone
from typing import Any

from app.connectors.base import Connector, SyncResult, TestResult
from app.connectors.discovery import DISCOVERY_CAPABILITY, Candidate, terms

CAPABILITIES: dict[str, list[str]] = {
    "jira": ["issues", "changelog", "story_points", "versions", "links", "custom_fields",
             "discovery"],
    "confluence": ["pages", "labels", "ancestors", "versions", "discovery"],
    "xray": ["test_sets", "test_executions", "traceability", "automated_results"],
    "github": ["pull_requests", "reviews", "changed_files", "checks", "deployments", "discovery"],
    "ci": ["workflow_runs", "durations", "artifacts", "first_attempt_pass_rate"],
    "sonarqube": ["coverage", "new_violations", "quality_gate", "discovery"],
    "linearb": ["pr_cycle_time", "pr_size", "review_latency", "discovery"],
    "jsm": ["incidents", "escaped_defects", "alert_routing"],
    "slack": ["chat_write", "channels_read"],
    "sentry": ["releases", "regressions", "crash_rate"],
    "figma": ["file_presence", "frame_names", "discovery"],
    "security": ["finding_status"],
}

FILTERS: dict[str, list[str]] = {
    "jira": ["project", "fixVersion", "labels", "issuetype", "resolutiondate", "team"],
    "linearb": ["team_id", "repository", "period"],
    "xray": ["project", "fixVersion", "test_set"],
}

# Sample rows a preview returns per connector. Deliberately small and obviously shaped like
# the source record, so a preview reads as "this is what your query would touch".
PREVIEW_ROWS: dict[str, list[dict[str, Any]]] = {
    "jira": [
        {"key": "ENT-412", "type": "Story", "status": "In Review", "points": 8, "team": "Entitlements"},
        {"key": "ENT-420", "type": "Story", "status": "In Progress", "points": 13, "team": "Entitlements"},
        {"key": "MAINT-8841", "type": "Bug", "status": "Open", "priority": "Blocker", "team": "Entitlements"},
    ],
    "linearb": [
        {"pr": 4821, "repo": "APPR", "changed_lines": 84, "cycle_time_days": 0.02, "merged": True},
        {"pr": 4830, "repo": "LIM", "changed_lines": 1420, "cycle_time_days": 0.63, "merged": True},
    ],
    "confluence": [
        {"page_id": 4915231, "title": "ENT-412 Test plan", "labels": ["sl-testplan"], "version": 4},
    ],
    "xray": [
        {"execution": "QA-118", "status": "PASS", "tests": 214, "fixVersion": "2026.3"},
    ],
    "ci": [
        {"run": 4821, "workflow": "verify.yml", "conclusion": "success", "artifacts": ["junit-results"]},
    ],
}


# What a search across the real sources would have returned. Keyed by the names people already
# use for a team, because that is the only thing an onboarding hint ever contains.
#
# Three of these teams have no ShiftLeft project yet - which is the case discovery exists for.
# The seeded ones are here too, so that proposing a project that already exists is exercised.
DISCOVERY_INDEX: list[dict[str, Any]] = [
    {
        "aliases": ["retail", "onboarding", "rto", "retail onboarding"],
        "name": "Retail Onboarding",
        "owner": "A. Kowalski",
        "jira_project": ("RTO", "Retail Onboarding", {"lead": "A. Kowalski", "issues_90d": 412}),
        "jira_team": ("Retail Onboarding", "Team field value on MAINT", {"open_bugs": 23}),
        "confluence_root": ("5218804", "Retail Onboarding — Engineering",
                            {"labels": ["sl-hld", "sl-testplan"]}),
        "repository": ("backbase/retail-onboarding", "retail-onboarding", {"open_prs": 9}),
        "sonar_component": ("bb:retail-onboarding", "Retail Onboarding", {"coverage": 71.4}),
        "linearb_team": ("631", "Retail Onboarding", {"repos": ["RTO", "RTO-BFF"]}),
        "figma_file": ("BB-RetailOnboarding", "BB Retail Onboarding", {"frames": 84}),
    },
    {
        "aliases": ["identity", "idp", "identity platform", "iam"],
        "name": "Identity Platform",
        "owner": "S. Haugen",
        "jira_project": ("IDP", "Identity Platform", {"lead": "S. Haugen", "issues_90d": 288}),
        "jira_team": ("Identity Platform", "Team field value on MAINT", {"open_bugs": 11}),
        "confluence_root": ("5104772", "Identity Platform — Engineering",
                            {"labels": ["sl-hld", "sl-threatmodel"]}),
        "repository": ("backbase/identity-platform", "identity-platform", {"open_prs": 4}),
        "sonar_component": ("bb:identity-platform", "Identity Platform", {"coverage": 80.2}),
        # No LinearB team and no Figma file: this team is not onboarded to either. The slots
        # stay empty and the widgets that need them render Missing.
    },
    {
        "aliases": ["cards", "cards ops", "cpo", "card operations"],
        "name": "Cards Operations",
        "owner": "L. Fernandes",
        "jira_project": ("CPO", "Cards Operations", {"lead": "L. Fernandes", "issues_90d": 173}),
        "confluence_root": ("5330119", "Cards Operations — Engineering", {"labels": ["sl-requirements"]}),
        "repository": ("backbase/cards-ops", "cards-ops", {"open_prs": 2}),
    },
    {
        "aliases": ["entitlements", "ent"],
        "name": "Entitlements",
        "owner": "M. Okonjo",
        "jira_project": ("ENT", "Entitlements", {"lead": "M. Okonjo", "issues_90d": 522}),
        "jira_team": ("Entitlements", "Team field value on MAINT", {"open_bugs": 31}),
        "confluence_root": ("4915231", "Entitlements — Engineering", {"labels": ["sl-hld", "sl-lld"]}),
        "repository": ("backbase/entitlements", "entitlements", {"open_prs": 12}),
        "sonar_component": ("bb:entitlements", "Entitlements", {"coverage": 76.9}),
        "linearb_team": ("418", "Entitlements", {"repos": ["APPR", "LIM", "AC", "AG", "LE-LEGALENTITY"]}),
        "figma_file": ("BB-Entitlements", "BB Entitlements", {"frames": 121}),
    },
]

# Which connector owns which slot, and how a candidate for it is addressed at source.
SLOT_OWNER = {
    "jira_project": ("jira", "https://backbase.atlassian.net/browse/{ref}"),
    "jira_team": ("jira", "https://backbase.atlassian.net/issues/?jql=%22Team%22%3D%22{ref}%22"),
    "confluence_root": ("confluence", "https://backbase.atlassian.net/wiki/pages/viewpage.action?pageId={ref}"),
    "repository": ("github", "https://github.com/{ref}"),
    "sonar_component": ("sonarqube", "https://sonar.backbase.net/dashboard?id={ref}"),
    "linearb_team": ("linearb", "https://app.linearb.io/teams/{ref}"),
    "figma_file": ("figma", "https://figma.com/files/search?q={ref}"),
}


async def discover(key: str, capabilities: list[str], hint: str, limit: int = 10) -> list[Candidate]:
    """Everything `key` can find under `hint`, shared by every connector - mock or live - that
    declares the "discovery" capability. Onboarding's index is still fixture data regardless of
    which class answers `test_connection`; a live connector reads it exactly the same way.
    """
    wanted = terms(hint)
    if not wanted or DISCOVERY_CAPABILITY not in capabilities:
        return []

    found: list[Candidate] = []
    for entry in DISCOVERY_INDEX:
        matched = tuple(t for t in wanted if any(t in alias for alias in entry["aliases"]))
        if not matched:
            continue
        for slot, (owner, url_template) in SLOT_OWNER.items():
            if owner != key or slot not in entry:
                continue
            ref, title, detail = entry[slot]
            found.append(
                Candidate(
                    connector_key=key, slot=slot, ref=ref, title=title,
                    url=url_template.format(ref=ref),
                    detail={**detail, "team": entry["name"], "owner": entry["owner"]},
                    matched_on=matched,
                )
            )
    return found[:limit]


class MockConnector(Connector):
    def __init__(self, key: str, name: str, config: dict[str, Any], secrets: dict[str, str]) -> None:
        super().__init__(config, secrets)
        self.key = key
        self.name = name

    async def test_connection(self) -> TestResult:
        required = [k for k, v in self.config.items() if v in (None, "", "—")]
        if not self.secrets and not self.config:
            return TestResult(ok=False, message="Not configured — no credentials or scope set.")
        if required:
            return TestResult(ok=False, message=f"Missing configuration: {', '.join(required)}")
        return TestResult(
            ok=True,
            message="Reachable · capabilities and filters refreshed",
            capabilities=await self.list_capabilities(),
            filters=await self.list_available_filters(),
        )

    async def list_capabilities(self) -> list[str]:
        return CAPABILITIES.get(self.key, [])

    async def list_available_filters(self) -> list[str]:
        return FILTERS.get(self.key, [])

    async def preview_data(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        return PREVIEW_ROWS.get(self.key, [])[:limit]

    async def sync(self, query: str, mode: str = "incremental") -> SyncResult:
        rows = await self.preview_data(query, limit=100)
        return SyncResult(
            ok=True,
            records=len(rows),
            synced_at=datetime.now(timezone.utc),
            message=f"{mode} sync completed",
        )

    async def search_entities(self, hint: str, limit: int = 10) -> list[Candidate]:
        """Everything this connector can find under `hint`. Unrecognised hints find nothing.

        A near-miss is not a match: the caller has to be able to tell "no such team here" from
        "here is something vaguely similar", because the first one means set the project up by
        hand and the second one means confirm a guess.
        """
        return await discover(self.key, await self.list_capabilities(), hint, limit)

    def map_to_canonical_model(self, raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"source": self.key, "source_ref": r.get("key") or r.get("pr") or r.get("page_id"), "raw": r}
                for r in raw]
