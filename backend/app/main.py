import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    access_model,
    connectors,
    insights,
    kickoff,
    kickoff_settings,
    onboarding,
    projects,
    readiness,
    rollout,
    templates,
)
from app.core.config import get_settings
from app.core.logging import RequestContextMiddleware, configure_logging
from app.db import schema
from app.db.session import SessionLocal, engine, ping
from app.seed.loader import seed, seed_reference
from app.services.guides import verify as verify_guides

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger("shiftleft")

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_schema:
        # Alembic owns schema in every deployed environment; this keeps local dev one command.
        # It reconciles rather than only creating: `create_all` cannot add a column to a table that
        # already exists, which used to surface as a 500 from a column the database never had.
        await schema.reconcile(engine)
    async with SessionLocal() as session:
        # Guides, catalogs and canonical artifacts are product content: every environment has them.
        if await seed_reference(session):
            logger.info("Loaded reference data: guides, connector and template catalogs, artifacts")
        if settings.seed_on_startup and await seed(session):
            logger.info("Seeded example projects from the design prototype's data")
        # Refuses to start if any rendered widget lacks its four guide fields.
        await verify_guides(session)
    logger.info("Started in %s mode, auth mode %s", settings.environment, settings.auth_mode)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=VERSION,
    description=(
        "Reads engineering systems, normalizes them, and reports on evidence and flow. "
        "Evidence outranks flow: a flow view always carries a link back to the evidence record."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-ShiftLeft-User", "X-ShiftLeft-Groups", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)
# Outermost, so the request id is set before anything else logs, the access line covers every
# response including CORS preflights, and an unhandled error becomes a 500 naming the request id.
app.add_middleware(RequestContextMiddleware)


api = "/api"
app.include_router(projects.router, prefix=api)
app.include_router(templates.router, prefix=api)
app.include_router(connectors.router, prefix=api)
app.include_router(readiness.router, prefix=api)
app.include_router(rollout.router, prefix=api)
app.include_router(insights.router, prefix=api)
app.include_router(access_model.router, prefix=api)
app.include_router(onboarding.router, prefix=api)
app.include_router(kickoff.router, prefix=api)
app.include_router(kickoff_settings.router, prefix=api)


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness: the process is up. Deliberately touches nothing else."""
    return {"status": "ok", "version": VERSION}


@app.get("/health/ready", tags=["ops"])
async def ready() -> JSONResponse:
    """Readiness: the database answers. A 503 takes the instance out of rotation."""
    try:
        await ping()
    except Exception:
        logger.warning("Readiness check failed: database unreachable", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": "unreachable"},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
