FROM python:3.14-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Unprivileged runtime user: a compromised process cannot modify the image or the code.
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- development: adds test tooling, code is bind-mounted by docker compose ----
FROM base AS dev
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app --no-server-header"]

# ---- production ----
FROM base AS prod
COPY --chown=root:root app ./app
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root alembic.ini .
USER app
EXPOSE 8000
# Behind a proxy, set FORWARDED_ALLOW_IPS to the proxy address (uvicorn reads it from the env).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers"]
