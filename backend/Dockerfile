# syntax=docker/dockerfile:1

# --- build: a wheel of the service, so the runtime image carries no build tooling ---
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels .

# --- runtime ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Safe by default: this image refuses to start until it is configured for production
    # (trusted-proxy auth, PostgreSQL, no seeding, Alembic-owned schema). See the README.
    SHIFTLEFT_ENVIRONMENT=production \
    SHIFTLEFT_LOG_JSON=true \
    SHIFTLEFT_SEED_ON_STARTUP=false \
    SHIFTLEFT_AUTO_CREATE_SCHEMA=false \
    SHIFTLEFT_AUTH_MODE=trusted-proxy

RUN useradd --create-home --uid 10001 shiftleft
WORKDIR /srv
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
# Migrations run from here as a separate step before the new version takes traffic:
#   docker run --rm <image> alembic upgrade head
COPY alembic.ini ./
COPY migrations ./migrations

USER shiftleft
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
# Worker count comes from WEB_CONCURRENCY; trusted proxy addresses from FORWARDED_ALLOW_IPS.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
