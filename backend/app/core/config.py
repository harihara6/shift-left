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
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
