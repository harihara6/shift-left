from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AccessGrant(BaseModel):
    id: int
    principal: str
    role: str
    via: str
    granted_by: str = "system"

    model_config = {"from_attributes": True}


class AccessGrantWrite(BaseModel):
    # The Literals mirror ROLES and GRANT_SOURCES on the model; a test keeps them in step.
    principal: str = Field(min_length=1, max_length=200)
    role: Literal["viewer", "contributor", "admin"]
    via: Literal["SSO group", "Explicit grant"]

    @field_validator("principal")
    @classmethod
    def _principal(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("principal cannot be blank")
        return v


class ProjectSummary(BaseModel):
    id: str
    key: str
    name: str
    owner: str
    created_on: date
    dashboards: int = 0
    archived: bool = False


class ProjectDetail(ProjectSummary):
    access: list[AccessGrant] = Field(default_factory=list)


class ProjectWrite(BaseModel):
    key: str = Field(min_length=2, max_length=16, pattern=r"^[A-Z][A-Z0-9]{1,15}$")
    # Must contain a letter or digit: the project id is minted from it and appears in URLs.
    name: str = Field(min_length=1, max_length=160, pattern=r"[A-Za-z0-9]")
    owner: str = Field(min_length=1, max_length=160)


class ProjectRename(BaseModel):
    name: str = Field(min_length=1, max_length=160, pattern=r"[A-Za-z0-9]")


class WidgetBindingOut(BaseModel):
    id: int
    name: str
    connector_key: str
    connector_name: str = ""
    query: str
    refresh_interval: str
    drill_template: str = ""
    last_sync: datetime | None = None
    stale: bool = False
    guide_key: str | None = None


class WidgetBindingWrite(BaseModel):
    query: str | None = Field(default=None, max_length=4000)
    refresh_interval: str | None = Field(default=None, max_length=32)
    drill_template: str | None = Field(default=None, max_length=1000)


class ProjectTemplateOut(BaseModel):
    id: int | None = None
    template_key: str
    name: str
    perspective: str
    enabled: bool
    copied_from_version: int | None = None
    copied_at: datetime | None = None
    widgets: list[WidgetBindingOut] = Field(default_factory=list)


class TemplateToggle(BaseModel):
    enabled: bool


class QueryPreview(BaseModel):
    connector_key: str
    query: str
    ok: bool
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    note: str = ""
    stale: bool = False


class ConnectorField(BaseModel):
    key: str
    label: str
    help: str
    type: str = "text"
    value: str | None = None
    # Secrets are write-only: the API returns a vault placeholder, never a value.
    placeholder: str = ""


class ConnectorAuthMethod(BaseModel):
    label: str
    recommended: bool = False


class ConnectorSummary(BaseModel):
    key: str
    name: str
    category: str
    state: str
    state_label: str
    last_successful_sync: datetime | None = None
    sync_label: str = "—"
    instances: int = 0
    stale: bool = False


class ConnectorDetail(ConnectorSummary):
    description: str
    auth_methods: list[ConnectorAuthMethod] = Field(default_factory=list)
    selected_auth: str | None = None
    fields: list[ConnectorField] = Field(default_factory=list)
    scopes: str = ""
    rate_limits: str = ""
    staleness_minutes: int = 30
    status_only: bool = False


class ConnectorConfigWrite(BaseModel):
    auth_method: str | None = Field(default=None, max_length=160)
    # Non-secret values only. Secret fields are written through /secrets, never here.
    config: dict[str, str] = Field(default_factory=dict, max_length=50)

    @field_validator("config")
    @classmethod
    def _bounded_values(cls, v: dict[str, str]) -> dict[str, str]:
        if any(len(value) > 2000 for value in v.values()):
            raise ValueError("configuration values are limited to 2000 characters")
        return v


class SecretRotate(BaseModel):
    field_key: str = Field(min_length=1, max_length=64)
    # The value is forwarded to the vault and never persisted or logged by this service.
    # repr=False keeps it out of any log line or traceback that formats this model.
    value: str = Field(min_length=1, max_length=8192, repr=False)


class ConnectorTestResult(BaseModel):
    ok: bool
    message: str
    capabilities: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    checked_at: datetime


class AccessModelEntry(BaseModel):
    title: str
    detail: str


class WhoAmI(BaseModel):
    email: str
    groups: list[str] = Field(default_factory=list)
    platform_admin: bool = False
    platform_admin_count: int = 0
