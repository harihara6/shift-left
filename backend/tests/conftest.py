import os
import sys
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
import pytest_asyncio

os.environ.setdefault("SHIFTLEFT_DATABASE_URL", "")
# Environment variables outrank backend/.env, so a developer's local integrations (a real
# Anthropic key, a Rovo token) can never leak into a test run and call out.
os.environ.update(
    {
        "SHIFTLEFT_ENVIRONMENT": "test",
        "SHIFTLEFT_ANTHROPIC_API_KEY": "",
        # A signed-in Cursor CLI on the developer's machine would otherwise answer, and bill them.
        "SHIFTLEFT_CURSOR_CLI": "off",
        "SHIFTLEFT_CURSOR_API_KEY": "",
        "SHIFTLEFT_ATLASSIAN_MCP_TOKEN": "",
        "SHIFTLEFT_ATLASSIAN_SITE_URL": "",
        "SHIFTLEFT_AUTH_MODE": "dev-header",
    }
)


@asynccontextmanager
async def _booted(env: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    """A fresh app over a fresh SQLite file, with `env` applied to its settings."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        db_path = handle.name
    overrides = {"SHIFTLEFT_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}", **env}
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)

    # Config and engine are module-level singletons; import after the environment is set.
    for module in [m for m in list(sys.modules) if m == "app" or m.startswith("app.")]:
        del sys.modules[module]
    from app.main import app

    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                yield c
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        os.unlink(db_path)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with _booted({}) as c:
        yield c


@pytest.fixture
def boot() -> Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]:
    """For tests that need the service started under different settings."""
    return lambda **env: _booted(env)


@pytest.fixture
def admin() -> dict[str, str]:
    return {"X-ShiftLeft-User": "h.nuti@backbase.com"}


@pytest.fixture
def viewer() -> dict[str, str]:
    """Reaches Entitlements through an SSO group with the viewer role."""
    return {"X-ShiftLeft-User": "qa@backbase.com", "X-ShiftLeft-Groups": "bb-qa-shared"}


@pytest.fixture
def contributor() -> dict[str, str]:
    return {"X-ShiftLeft-User": "dev@backbase.com", "X-ShiftLeft-Groups": "bb-eng-entitlements"}


@pytest.fixture
def stranger() -> dict[str, str]:
    return {"X-ShiftLeft-User": "nobody@backbase.com"}
