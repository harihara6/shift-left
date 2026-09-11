"""Drill-down resolution.

Every metric resolves to a source record. The base URL comes from the connector instance's own
config, so a drill link is never a hardcoded guess about someone's Atlassian tenant.
"""

from urllib.parse import quote, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connector import ConnectorInstance
from app.schemas.common import DrillDown


def jql_string(value: str) -> str:
    """A JQL string literal. A quote in a team or release name must not end the clause early."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _web_base(url: str) -> str | None:
    """Only an absolute http(s) URL is a drill base. Anything else - a typo, a javascript: URL
    pasted into connector config - yields no link rather than a broken or unsafe one."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return url.strip().rstrip("/")


async def base_urls(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(ConnectorInstance))).scalars().all()
    out: dict[str, str] = {}
    for row in rows:
        config = row.config or {}
        url = config.get("site_url") or config.get("server_url") or config.get("base_url")
        if not url and config.get("workspace"):
            # Slack names a workspace host rather than a URL.
            url = f"https://{config['workspace']}"
        if not url and row.connector_key == "github" and config.get("organisation"):
            url = f"https://github.com/{config['organisation']}"
        base = _web_base(str(url)) if url else None
        if base:
            out[row.connector_key] = base
    return out


SYSTEM_NAMES = {
    "jira": "Jira", "confluence": "Confluence", "github": "GitHub", "slack": "Slack",
    "xray": "Xray", "ci": "CI",
}


def at(bases: dict[str, str], connector: str, ref: str, label: str) -> DrillDown | None:
    """A path under a connector's own base URL. No configured base means no link, not a guess."""
    base = bases.get(connector)
    if not base or not ref:
        return None
    system = SYSTEM_NAMES.get(connector, connector)
    return DrillDown(label=label, url=f"{base}/{ref.lstrip('/')}", system=system)


def jira_jql(bases: dict[str, str], jql: str, label: str = "Open in Jira") -> DrillDown | None:
    base = bases.get("jira")
    if not base:
        # No Jira instance configured: the widget says so rather than offering a dead link.
        return None
    return DrillDown(label=label, url=f"{base}/issues/?jql={quote(jql)}", system="Jira")


def linearb(
    bases: dict[str, str], team_id: str | None, label: str = "Open in LinearB"
) -> DrillDown | None:
    if team_id is None:
        return None
    return DrillDown(label=label, url=f"https://app.linearb.io/teams/{team_id}/metrics", system="LinearB")


def evidence_record(
    bases: dict[str, str], connector: str, feature_key: str, artifact_name: str
) -> DrillDown | None:
    """Resolve one checklist row to the record it was read from.

    Confluence artifacts resolve to a label search scoped to the feature key rather than to a
    guessed page id; everything else resolves to the Jira issue the evidence hangs off.
    """
    if connector == "confluence":
        base = bases.get("confluence") or bases.get("jira")
        if not base:
            return None
        label = quote(_LABELS.get(artifact_name, "shiftleft"))
        return DrillDown(
            label="Open in Confluence",
            url=f"{base}/search?text={quote(feature_key)}&label={label}",
            system="Confluence",
        )
    base = bases.get(connector) or bases.get("jira")
    if not base:
        return None
    system = {"xray": "Xray", "ci": "CI", "figma": "Figma"}.get(connector, "Jira")
    return DrillDown(
        label=f"Open in {system}", url=f"{base}/browse/{quote(feature_key)}", system=system
    )


# The Confluence label convention each artifact is expected to carry (DESIGN-HANDOFF s7).
# Proposed, not observed - it is surfaced in the widget guide so teams can confirm it.
_LABELS = {
    "Requirements incl. visual design": "sl-requirements",
    "Test plan incl. NFR testing": "sl-testplan",
    "High-level design": "sl-hld",
    "Low-level design, per platform": "sl-lld",
    "Threat model": "sl-threatmodel",
    "Performance verification": "sl-performance",
    "Accessibility, WCAG 2.2 AA": "sl-accessibility",
}
