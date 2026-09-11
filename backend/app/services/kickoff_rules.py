"""Feature Kickoff: which checks and outputs a PRD needs, decided from what the PRD says.

Reading the PRD is the only step that takes judgement (a model, or the keyword reader when no
model is chosen). Everything in this module is deterministic: given the same facts it gives the
same answer, and every answer carries the criterion it applied (docs/PROPOSAL-PRD-Intake.md s3).

Each action resolves to one of three outcomes, and none is silent:

* **applies** — the facts meet the criterion; the reason quotes the PRD.
* **not_applicable** — the facts rule it out, and the reason says which fact did.
* **undetermined** — a fact the rule needs is missing. This is treated as *applies* and comes
  with a question, because the costly error is a check that should have run and didn't. It is
  PRD s6's "ambiguous defaults to the higher tier", applied to scope.

Change the proposal first, then the rule.
"""

from dataclasses import dataclass, field
from typing import Literal

Outcome = Literal["applies", "not_applicable", "undetermined"]

# --- Facts ------------------------------------------------------------------------------------

FACT_LABELS: dict[str, str] = {
    "regions": "Regions and markets",
    "domain": "Product domain",
    "third_party_access": "Third-party access",
    "channels": "Channels",
    "change_kind": "Kind of change",
    "introduces_api": "Introduces an API",
    "services": "Internal services touched",
    "third_parties": "Third parties named",
    "data_classes": "Data carried",
}

# Facts with a closed vocabulary. A reader may only ever return these values; anything else is
# dropped on the way in, the same way guided setup drops a candidate id no source returned.
ENUMS: dict[str, tuple[str, ...]] = {
    "regions": ("NL", "DE", "FR", "BE", "ES", "IE", "IT", "EU", "EEA", "UK", "US"),
    "domain": ("payments", "accounts", "onboarding", "cards", "lending"),
    "third_party_access": ("exposes", "consumes", "none"),
    "channels": ("web", "mobile", "api"),
    "change_kind": (
        "new_service", "new_journey", "new_api", "trust_boundary", "new_integration",
        "behaviour_change", "config_copy",
    ),
    "introduces_api": ("yes", "no"),
    "data_classes": ("payment_data", "account_data", "pii", "credentials"),
}

VALUE_LABELS: dict[str, str] = {
    "NL": "Netherlands", "DE": "Germany", "FR": "France", "BE": "Belgium", "ES": "Spain",
    "IE": "Ireland", "IT": "Italy", "EU": "EU", "EEA": "EEA", "UK": "United Kingdom",
    "US": "United States",
    "payments": "Payments", "accounts": "Accounts", "onboarding": "Onboarding", "cards": "Cards",
    "lending": "Lending",
    "exposes": "Third parties access our APIs", "consumes": "We call third parties as a TPP",
    "none": "None",
    "web": "Web", "mobile": "Mobile", "api": "API only",
    "new_service": "New service", "new_journey": "New customer-facing journey",
    "new_api": "New API or endpoint", "trust_boundary": "New trust boundary",
    "new_integration": "New integration", "behaviour_change": "Behaviour change",
    "config_copy": "Config or copy only",
    "yes": "Yes", "no": "No",
    "payment_data": "Payment data", "account_data": "Account data", "pii": "Personal data (PII)",
    "credentials": "Credentials",
}

# Markets that put a PRD under EU/EEA rules. The list grows with the markets Backbase builds for.
EU_EEA = frozenset({"NL", "DE", "FR", "BE", "ES", "IE", "IT", "EU", "EEA"})


@dataclass
class Fact:
    key: str
    values: list[str] = field(default_factory=list)
    # "stated" (read from the PRD, with quotes), "not_stated", or "confirmed" (set by a person).
    status: str = "not_stated"
    quotes: list[dict] = field(default_factory=list)
    confirmed_by: str | None = None

    @property
    def known(self) -> bool:
        return self.status in ("stated", "confirmed")

    def shown(self) -> str:
        return ", ".join(VALUE_LABELS.get(v, v) for v in self.values) or "none"


def fact_from(data: dict) -> Fact:
    return Fact(
        key=data["key"], values=list(data.get("values", [])), status=data.get("status", "not_stated"),
        quotes=list(data.get("quotes", [])), confirmed_by=data.get("confirmed_by"),
    )


Facts = dict[str, Fact]


def _has(facts: Facts, key: str, *values: str) -> bool | None:
    """Three-valued: True, False, or None when the fact is not known."""
    fact = facts.get(key)
    if fact is None or not fact.known:
        return None
    return any(v in fact.values for v in values)


def _quotes(facts: Facts, *keys: str) -> list[dict]:
    """The sentences behind an outcome, without repeats. Two are enough to check a reason by."""
    seen: list[dict] = []
    for key in keys:
        fact = facts.get(key)
        for quote in fact.quotes if fact is not None else []:
            if quote not in seen:
                seen.append(quote)
    return seen[:2]


# --- Actions ----------------------------------------------------------------------------------

ActionGroup = Literal["create", "update", "verify", "standards"]

GROUP_LABELS: dict[str, str] = {
    "create": "Create",
    "update": "Update",
    "verify": "Verify",
    "standards": "Check API standards",
}


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    group: ActionGroup
    target: str
    description: str


ACTIONS: tuple[Action, ...] = (
    Action("jira_backlog", "Create the Jira backlog", "create", "Jira",
           "An epic, a story per feature, and the evidence tasks this change's risk tier needs."),
    Action("xray_plan", "Create the Xray test plan", "create", "Xray",
           "A test plan, with a test drafted from each acceptance criterion."),
    Action("feasibility_page", "Publish the feasibility record", "create", "Confluence",
           "One page with the facts, every rule outcome (including what was ruled out) and the findings."),
    Action("software_catalog", "Update the software catalog", "update", "Confluence",
           "The rows this change adds to or changes in the software catalog, as a diff."),
    Action("product_index", "Update the product index", "update", "Confluence",
           "The product feature this PRD adds or changes, as a diff."),
    Action("dependency_check", "Verify dependencies in GitHub", "verify", "GitHub",
           "Whether each service the PRD relies on exposes the operation it needs."),
    Action("third_party_check", "Check third-party readiness", "verify", "Vendor docs",
           "Sandbox, auth model, rate limits, versioning and status page for each third party."),
    Action("std_berlin_group", "Berlin Group NextGenPSD2", "standards", "Pinned standard",
           "EU/EEA access to accounts by third parties."),
    Action("std_obie", "UK Open Banking (OBIE)", "standards", "Pinned standard",
           "UK Read/Write API, security profile and client registration."),
    Action("std_fdx", "FDX", "standards", "Pinned standard", "US consumer data sharing."),
    Action("std_iso20022", "ISO 20022", "standards", "Pinned standard",
           "Payment message and field mapping."),
    Action("std_bian", "BIAN", "standards", "Pinned standard",
           "Service-domain alignment for a new service or API. A reference model: alignment, "
           "never compliance."),
)

ACTION_BY_KEY = {a.key: a for a in ACTIONS}
STANDARD_FOR_ACTION = {
    "std_berlin_group": "berlin_group", "std_obie": "obie", "std_fdx": "fdx",
    "std_iso20022": "iso20022", "std_bian": "bian",
}


@dataclass
class Resolution:
    outcome: Outcome
    reason: str
    quotes: list[dict] = field(default_factory=list)
    question: str = ""

    @property
    def recommended(self) -> bool:
        # Undetermined runs: the expensive mistake is the check that should have happened.
        return self.outcome != "not_applicable"


def _applies(reason: str, quotes: list[dict]) -> Resolution:
    return Resolution("applies", reason, quotes)


def _na(reason: str, quotes: list[dict]) -> Resolution:
    return Resolution("not_applicable", reason, quotes)


def _undetermined(reason: str, question: str, quotes: list[dict] | None = None) -> Resolution:
    return Resolution("undetermined", reason, quotes or [], question)


def _is_copy_only(facts: Facts) -> bool:
    change = facts.get("change_kind")
    return bool(change and change.known and change.values == ["config_copy"])


def _market_standard(
    facts: Facts, *, markets: frozenset[str], market_name: str, standard: str, access: tuple[str, ...]
) -> Resolution:
    criterion = f"Applies when the region is {market_name} and third parties access accounts."
    if _is_copy_only(facts):
        return _na(f"{criterion} Copy only: no API changes.", _quotes(facts, "change_kind"))
    regions = facts.get("regions")
    in_market = None if regions is None or not regions.known else bool(markets & set(regions.values))
    access_known = _has(facts, "third_party_access", *access)
    if in_market is False:
        return _na(f"{criterion} Region is {regions.shown()}, so {standard} is not triggered.",
                   _quotes(facts, "regions"))
    if access_known is False:
        return _na(
            f"{criterion} Third-party access: {facts['third_party_access'].shown()}, so {standard} "
            "is not triggered.",
            _quotes(facts, "third_party_access"),
        )
    if in_market and access_known:
        return _applies(criterion, _quotes(facts, "regions", "third_party_access"))
    missing = "region" if in_market is None else "third-party access"
    return _undetermined(
        f"{criterion} The PRD doesn't state the {missing}, so this runs until someone says otherwise.",
        "Which markets is this built for?" if in_market is None
        else "Will third-party providers access these APIs, or will we call them as a TPP?",
        _quotes(facts, "regions", "third_party_access"),
    )


def resolve(action: str, facts: Facts) -> Resolution:
    """The outcome for one action. Pure: the same facts always give the same answer."""
    if action == "jira_backlog":
        return _applies("Every PRD becomes a backlog: epic, stories and its tier's evidence tasks.", [])

    if action == "feasibility_page":
        return _applies(
            "Always, so what was checked, what was ruled out and why is on record next to the PRD.", []
        )

    if action == "xray_plan":
        return _applies("Applies whenever stories are created: each acceptance criterion gets a test.", [])

    if action == "software_catalog":
        criterion = "Applies when the change adds a service or an API."
        if _is_copy_only(facts):
            return _na(f"{criterion} This is a config or copy change.", _quotes(facts, "change_kind"))
        new = _has(facts, "introduces_api", "yes")
        if new is True or _has(facts, "change_kind", "new_service"):
            return _applies(criterion, _quotes(facts, "introduces_api", "change_kind"))
        if new is False:
            return _na(f"{criterion} The PRD says it introduces no API.", _quotes(facts, "introduces_api"))
        return _undetermined(
            f"{criterion} The PRD doesn't say whether it adds an API.",
            "Does this add a new API or endpoint, or only use existing ones?",
        )

    if action == "product_index":
        criterion = "Applies when a product feature is added or changed."
        if _is_copy_only(facts):
            return _na(f"{criterion} Copy only: no product feature changes.", _quotes(facts, "change_kind"))
        return _applies(criterion, _quotes(facts, "change_kind"))

    if action == "dependency_check":
        criterion = "Applies when the PRD relies on internal services."
        services = facts.get("services")
        if services is not None and services.known and services.values:
            return _applies(criterion, _quotes(facts, "services"))
        if _is_copy_only(facts):
            return _na(f"{criterion} Copy only, and no service is named.", _quotes(facts, "change_kind"))
        return _undetermined(
            f"{criterion} The PRD names none.",
            "Which internal services does this change call or modify?",
        )

    if action == "third_party_check":
        criterion = "Applies when the PRD names a third party."
        parties = facts.get("third_parties")
        if parties is not None and parties.known and parties.values:
            return _applies(criterion, _quotes(facts, "third_parties"))
        moves_money = _has(facts, "domain", "payments") and not _is_copy_only(facts)
        if moves_money and _has(facts, "change_kind", "new_journey", "new_service", "new_api"):
            return _undetermined(
                f"{criterion} None is named, but new payment flows reach other banks through a scheme "
                "or clearing provider.",
                "Which scheme or clearing provider carries these payments?",
                _quotes(facts, "domain"),
            )
        return _na(f"{criterion} The PRD names none.", [])

    if action == "std_berlin_group":
        return _market_standard(facts, markets=EU_EEA, market_name="in the EU/EEA",
                                standard="NextGenPSD2", access=("exposes", "consumes"))

    if action == "std_obie":
        return _market_standard(facts, markets=frozenset({"UK"}), market_name="the UK",
                                standard="UK Open Banking", access=("exposes", "consumes"))

    if action == "std_fdx":
        return _market_standard(facts, markets=frozenset({"US"}), market_name="the US",
                                standard="FDX", access=("exposes", "consumes"))

    if action == "std_iso20022":
        criterion = "Applies when payment messages are created or changed, in any region."
        payments = _has(facts, "domain", "payments")
        if payments is False:
            return _na(f"{criterion} Domain is {facts['domain'].shown()}.", _quotes(facts, "domain"))
        if payments and _is_copy_only(facts):
            return _na(f"{criterion} Copy only: no payment message changes.", _quotes(facts, "change_kind"))
        if payments:
            return _applies(criterion, _quotes(facts, "domain"))
        return _undetermined(f"{criterion} The PRD doesn't state its domain.",
                             "Does this change create or alter payment messages?")

    if action == "std_bian":
        criterion = "Applies when the change adds a service or an API."
        if _is_copy_only(facts):
            return _na(f"{criterion} This is a config or copy change.", _quotes(facts, "change_kind"))
        new = _has(facts, "introduces_api", "yes")
        if new is True or _has(facts, "change_kind", "new_service"):
            return _applies(criterion, _quotes(facts, "introduces_api", "change_kind"))
        if new is False:
            return _na(f"{criterion} The PRD says it introduces no API.", _quotes(facts, "introduces_api"))
        return _undetermined(
            f"{criterion} The PRD doesn't say whether it adds an API.",
            "Does this add a new API or endpoint, or only use existing ones?",
        )

    raise KeyError(action)


# --- Risk tier (PRD s6) -----------------------------------------------------------------------

TIERS = ("New capability", "Major change", "Minor change", "Config / copy")

# Highest tier first: a change that is both a new journey and a copy tweak is a new journey.
TIER_BY_CHANGE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("New capability", ("new_service", "new_journey")),
    ("Major change", ("new_api", "trust_boundary", "new_integration")),
    ("Minor change", ("behaviour_change",)),
    ("Config / copy", ("config_copy",)),
)

ALL_ARTIFACTS = (
    "requirements", "acceptance_criteria", "test_plan", "hld", "lld", "threat_model",
    "traceability", "test_evidence", "performance", "accessibility", "ai_evidence",
)

# What each tier requires. Anything else it may scope down, but only with a recorded rationale.
TIER_REQUIRES: dict[str, tuple[str, ...]] = {
    "New capability": ALL_ARTIFACTS,
    "Major change": ALL_ARTIFACTS,
    "Minor change": ("requirements", "acceptance_criteria", "test_plan", "lld", "test_evidence"),
    "Config / copy": ("acceptance_criteria", "test_evidence"),
}


@dataclass
class Tier:
    tier: str
    reason: str
    undetermined: bool = False
    quotes: list[dict] = field(default_factory=list)


def tier_for(facts: Facts) -> Tier:
    change = facts.get("change_kind")
    if change is None or not change.known or not change.values:
        return Tier(
            "New capability",
            "The PRD doesn't say what kind of change this is. Ambiguous defaults to the higher tier "
            "(PRD §6), so every artifact is required until someone says otherwise.",
            undetermined=True,
        )
    for tier, kinds in TIER_BY_CHANGE:
        hit = [k for k in change.values if k in kinds]
        if hit:
            return Tier(
                tier,
                f"{VALUE_LABELS[hit[0]]} → {tier} (PRD §6).",
                quotes=change.quotes[:2],
            )
    return Tier("New capability", "No recognised change kind; defaults to the higher tier.", True)


def accessibility_in_scope(facts: Facts) -> bool | None:
    """True with a web or mobile channel, False for API-only, None when channels are unknown."""
    channels = facts.get("channels")
    if channels is None or not channels.known:
        return None
    return bool({"web", "mobile"} & set(channels.values))
