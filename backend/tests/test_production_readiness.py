"""What the service needs to be safe to deploy: configuration guards, probes, request ids,
and a schema that Alembic - not the models - owns."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[1]

SAFE_PRODUCTION = {
    "environment": "production",
    "auth_mode": "trusted-proxy",
    "proxy_shared_secret": "s3cret",
    "database_url": "postgresql+asyncpg://u:p@db/shiftleft",
    "seed_on_startup": False,
    "auto_create_schema": False,
    "cors_origins": ["https://shiftleft.backbase.com"],
    "kickoff_sources": "live",
}


def _settings(**overrides):
    from app.core.config import Settings

    return Settings(_env_file=None, **{**SAFE_PRODUCTION, **overrides})


def test_a_safe_production_configuration_starts():
    assert _settings().is_production


@pytest.mark.parametrize(
    ("override", "complaint"),
    [
        ({"auth_mode": "dev-header"}, "AUTH_MODE"),
        ({"proxy_shared_secret": None}, "PROXY_SHARED_SECRET"),
        ({"database_url": "sqlite+aiosqlite:///./x.db"}, "PostgreSQL"),
        ({"seed_on_startup": True}, "SEED_ON_STARTUP"),
        ({"auto_create_schema": True}, "alembic upgrade head"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"platform_admins": []}, "PLATFORM_ADMINS"),
        ({"kickoff_sources": "fixtures"}, "KICKOFF_SOURCES"),
    ],
)
def test_production_refuses_a_configuration_that_is_only_safe_locally(override, complaint):
    with pytest.raises(ValidationError, match=complaint):
        _settings(**override)


def test_live_kickoff_writes_are_refused_from_example_pages_in_any_environment():
    from app.core.config import Settings

    with pytest.raises(ValidationError, match="KICKOFF_WRITE_MODE"):
        Settings(_env_file=None, environment="development", kickoff_write_mode="live")
    live = Settings(_env_file=None, kickoff_sources="live", kickoff_write_mode="live")
    assert live.kickoff_write_mode == "live"


def test_development_keeps_its_one_command_defaults():
    from app.core.config import Settings

    settings = Settings(_env_file=None, environment="development")
    assert settings.auth_mode == "dev-header"
    assert settings.seed_on_startup and settings.auto_create_schema


async def test_a_store_without_example_data_still_starts_and_is_usable(boot, admin):
    """Production never seeds. Guides and catalogs are product content, so they load anyway -
    without them the guide check would refuse to boot and Settings would have nothing to set."""
    async with boot(SHIFTLEFT_SEED_ON_STARTUP="false") as c:
        assert (await c.get("/api/projects", headers=admin)).json() == []
        connectors = (await c.get("/api/connectors", headers=admin)).json()
        assert connectors, "the connector catalog is reference data"
        assert all(conn["state"] == "not_configured" for conn in connectors)
        assert (await c.get("/api/guides/delivery", headers=admin)).json()["widgets"]

        created = await c.post(
            "/api/projects", headers=admin, json={"key": "NEW", "name": "New Team", "owner": "A. B."}
        )
        assert created.status_code == 201
        templates = (await c.get("/api/projects/new-team/templates", headers=admin)).json()
        assert templates, "the template catalog is reference data"


async def test_liveness_and_readiness(client):
    assert (await client.get("/health")).json()["status"] == "ok"
    ready = await client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["database"] == "ok"


async def test_every_response_carries_a_request_id(client, admin):
    minted = await client.get("/api/projects", headers=admin)
    assert len(minted.headers["x-request-id"]) == 32

    forwarded = await client.get("/api/projects", headers={**admin, "X-Request-ID": "edge-abc.123"})
    assert forwarded.headers["x-request-id"] == "edge-abc.123"

    # A caller-supplied id lands in logs, so one that is not a plain token is replaced.
    hostile = await client.get("/api/projects", headers={**admin, "X-Request-ID": "x\ninjected"})
    assert hostile.headers["x-request-id"] != "x\ninjected"


async def test_an_unhandled_error_returns_the_request_id_and_nothing_else(client):
    from app.main import app

    async def explode() -> None:
        raise RuntimeError("internal detail that must not reach the caller")

    app.add_api_route("/__explode", explode)
    response = await client.get("/__explode")
    assert response.status_code == 500
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "internal detail" not in response.text


def _alembic(*args: str, url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "SHIFTLEFT_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )


def test_migrations_build_exactly_the_schema_the_models_declare():
    """A model change without a migration fails here, not in the first deployment."""
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite+aiosqlite:///{tmp}/migrated.db"
        upgrade = _alembic("upgrade", "head", url=url)
        assert upgrade.returncode == 0, upgrade.stderr
        check = _alembic("check", url=url)
        assert check.returncode == 0, check.stdout + check.stderr
        downgrade = _alembic("downgrade", "base", url=url)
        assert downgrade.returncode == 0, downgrade.stderr
