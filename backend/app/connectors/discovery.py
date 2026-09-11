"""Discovery: finding a team's sources from the name people already call it.

This is an *optional* capability layered over the connector contract (TDD s6), not a seventh
method on it. A connector advertises `discovery` from `list_capabilities()` and implements
`search_entities()`; one that does neither simply contributes nothing, and the slot it would
have filled renders Missing rather than being quietly skipped.

Nothing here writes. Discovery reads candidate identifiers - a Jira project key, a Confluence
page id, a repository name - so a human can confirm which ones are actually this team's.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

DISCOVERY_CAPABILITY = "discovery"

# The identifiers a project setup actually needs. Each one is a slot in the proposal, and each
# slot is filled by exactly one candidate - or left empty, which renders Missing.
SLOTS = (
    "jira_project",       # ENT — the Jira project key
    "jira_team",          # Entitlements — the Team field value on the shared MAINT project
    "confluence_root",    # 4915231 — the page every sl-* artifact page hangs under
    "repository",         # backbase/entitlements
    "sonar_component",    # bb:entitlements
    "linearb_team",       # 418
    "figma_file",         # BB-Entitlements
)


@dataclass(frozen=True)
class Candidate:
    """One thing a source system says might be this team.

    `ref` is the value that would be substituted into a query; `url` is where a human goes to
    check it. A candidate with no url is not shippable - every proposal has to be verifiable
    at source, the same rule the widgets live under.
    """

    connector_key: str
    slot: str
    ref: str
    title: str
    url: str
    detail: dict[str, Any] = field(default_factory=dict)
    # Why this row came back at all: the hint terms the source matched on.
    matched_on: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"{self.connector_key}:{self.slot}:{self.ref}"


@runtime_checkable
class Discoverable(Protocol):
    """Implemented by connectors that can search their source by a human name."""

    async def search_entities(self, hint: str, limit: int = 10) -> list[Candidate]: ...


def terms(hint: str) -> list[str]:
    """The hint split into the tokens a source would plausibly match on."""
    cleaned = "".join(c if c.isalnum() else " " for c in hint.lower())
    return [t for t in cleaned.split() if len(t) > 1]
