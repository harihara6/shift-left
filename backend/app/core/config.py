from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration. Secrets never carry a default."""

    model_config = SettingsConfigDict(env_prefix="SHIFTLEFT_", env_file=".env", extra="ignore")

    app_name: str = "ShiftLeft Quality Observability Service"
    # "production" turns the guards in `_production_guards` on. Anything else is a dev or test box.
    environment: Literal["development", "test", "production"] = "development"

    # Postgres is the production store (TDD s10). SQLite keeps local dev runnable with no daemon.
    database_url: str = "sqlite+aiosqlite:///./shiftleft.db"
    database_echo: bool = False
    # Alembic owns the schema wherever it is deployed (`alembic upgrade head`). Creating tables
    # from the models at startup is a local-dev convenience only.
    auto_create_schema: bool = True
    cors_origins: list[str] = ["http://localhost:4200"]
    seed_on_startup: bool = True

    log_level: str = "INFO"
    # One JSON object per line, for the log pipeline. Plain text reads better in a dev terminal.
    log_json: bool = False

    # --- Identity -----------------------------------------------------------------------
    # "dev-header": the caller names themselves on X-ShiftLeft-User. Anyone can claim to be
    #   anyone, which is why production refuses to start in this mode.
    # "trusted-proxy": an SSO proxy in front of the service authenticates the person and sets
    #   the same headers, and proves it did so with a shared secret the service checks.
    auth_mode: Literal["dev-header", "trusted-proxy"] = "dev-header"
    proxy_shared_secret: SecretStr | None = None
    # A small, audited set for the service's own operators. Everything else is project-scoped.
    platform_admins: list[str] = ["h.nuti@backbase.com"]

    # A connector past this many minutes without a successful sync renders Stale and can never
    # contribute to a green RAG state (PRD s8). Per-connector overrides live on connector_types.
    default_staleness_minutes: int = 30

    # Rationales that are never acceptable for scoping an artifact down (PRD s6). Matching
    # waivers render flagged and surface to platform owners as a planning signal.
    waiver_rationale_denylist: list[str] = [
        "capacity pressure", "no time", "deadline", "will revisit next release",
    ]

    # --- Smart onboarding (all optional; every one of these absent means manual setup) ---
    # Rovo MCP is Cloud-only and org-admin-gated, so discovery is an alternate path, never a
    # prerequisite. Both values below are read at call time and never returned by any endpoint.
    atlassian_mcp_url: str = "https://mcp.atlassian.com/v2/mcp"
    atlassian_site_url: str = ""
    # A per-user OAuth 2.1 access token. Vault-held in production; env only for local dev.
    atlassian_mcp_token: str | None = None

    # Claude resolves which discovered candidate is which team. Without a key the resolver
    # falls back to deterministic name matching, which is weaker but never unavailable.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    # Discovery is interactive: a slow model call degrades to name matching rather than
    # holding the request open for the SDK's ten-minute default.
    anthropic_timeout_seconds: float = 30.0
    # Feature Kickoff's analysis reads a PRD, several repos and their docs in one call and drafts
    # the whole plan, which takes minutes rather than seconds. A timeout degrades to the rule-based
    # draft, labelled as such, rather than failing the step.
    kickoff_model_timeout_seconds: float = 300.0

    # --- Feature Kickoff ---------------------------------------------------------------------
    # Credentials come from Settings -> Connectors first (Confluence, Jira, GitHub), then from
    # the variables below. Nothing is ever read from example data: a source that can't be
    # reached says why.
    #
    # Jira and Confluence REST (Cloud). The site is `atlassian_site_url`. An API token acts as
    # the account that owns it; every created ticket also names the person who created it.
    atlassian_email: str = ""
    atlassian_api_token: SecretStr | None = None

    # GitHub REST, for reading the repos a feature is coded in and relies on. Enterprise hosts set
    # the URL. Public repos are readable without a token, at GitHub's lower anonymous rate limit.
    github_api_url: str = "https://api.github.com"
    github_token: SecretStr | None = None

    # Xray Cloud (GraphQL). EU and AU tenants use their regional host.
    xray_base_url: str = "https://xray.cloud.getxray.app"
    xray_client_id: str = ""
    xray_client_secret: SecretStr | None = None

    # Cursor's API lists the models the team's account can use. It has no call that answers a
    # prompt, so these models run in the editor, never on this server.
    cursor_api_key: SecretStr | None = None

    # Encrypts every value behind a "vault://..." reference (app/services/vault.py) - what makes
    # a credential typed into Settings -> Connectors resolvable again when a connector actually
    # calls out, instead of a placeholder pointing nowhere. Local dev derives and persists its
    # own key on first use so setup stays zero-config; every other environment must set this
    # explicitly, or a fresh key on restart makes every rotated credential unreadable.
    vault_encryption_key: SecretStr | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        """Refuse to start a production service in a configuration that is only safe locally."""
        if not self.is_production:
            return self
        problems = []
        if self.auth_mode != "trusted-proxy":
            problems.append(
                "SHIFTLEFT_AUTH_MODE must be 'trusted-proxy' - in dev-header mode any caller can "
                "claim any identity, including a platform admin"
            )
        if self.auth_mode == "trusted-proxy" and not self.proxy_shared_secret:
            problems.append("SHIFTLEFT_PROXY_SHARED_SECRET is required in trusted-proxy mode")
        if self.database_url.startswith("sqlite"):
            problems.append("SHIFTLEFT_DATABASE_URL must point at PostgreSQL, not SQLite")
        if self.seed_on_startup:
            problems.append(
                "SHIFTLEFT_SEED_ON_STARTUP must be false - seed rows are prototype fixtures, not data"
            )
        if self.auto_create_schema:
            problems.append(
                "SHIFTLEFT_AUTO_CREATE_SCHEMA must be false - run `alembic upgrade head` instead"
            )
        if "*" in self.cors_origins:
            problems.append("SHIFTLEFT_CORS_ORIGINS cannot be '*' when credentials are allowed")
        if not self.platform_admins:
            problems.append("SHIFTLEFT_PLATFORM_ADMINS must name at least one operator")
        if not self.vault_encryption_key:
            problems.append(
                "SHIFTLEFT_VAULT_ENCRYPTION_KEY must be set - a random per-boot key would make "
                "every stored connector credential unrecoverable after the next restart"
            )
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
