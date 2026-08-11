# --- builder: install deps in a separate layer for cache ---
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System deps for asyncpg + bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# --- runtime ---
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UPLOAD_DIR=/app/uploads \
    # Railway injects PORT; this default keeps `docker run -p 8000:8000` working
    # and keeps docker-compose.prod.yml (which expects 8000) unchanged.
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10001 -m -d /app app

COPY --from=builder /install /usr/local
WORKDIR /app

# Copy only what the service runs on. Everything else (.venv, tests, local
# uploads) is excluded by .dockerignore, but naming the paths means a new
# top-level file cannot quietly enlarge the production image.
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

# UPLOAD_DIR only matters for STORAGE_BACKEND=local. On Railway this directory
# is ephemeral and must NOT hold photographs — see docs/DEPLOYMENT.md. It still
# has to exist because main.py mounts /static from it unconditionally.
RUN mkdir -p /app/uploads && chown -R app:app /app/uploads

# Non-root. Nothing this process does needs write access outside /app/uploads,
# and a container that cannot modify its own code is one less thing an RCE buys.
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Migrate, then seed, then serve — in one shell so a failed migration aborts the
# boot instead of serving traffic against a schema that is one revision behind.
#
# This is safe at one replica, which is what Railway gives you by default. If
# you ever scale the backend past one instance, move `alembic upgrade head` out
# of here into a release step: two containers racing the same migration will
# deadlock on the alembic_version row.
#
# --proxy-headers so request logs and redirects see the real client scheme/IP
# through Railway's edge. Only the immediate hop is trusted by default: with
# '*', uvicorn believes any X-Forwarded-For a caller sends, which hands every
# client the ability to choose its own IP — and the login rate limit, which
# buckets on that IP, stops limiting anything. Set FORWARDED_ALLOW_IPS to the
# platform's proxy range if it is not on the loopback.
# --forwarded-allow-ips is needed because that edge is not
# 127.0.0.1.
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
