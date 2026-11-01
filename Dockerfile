# Liquid Glass Crypto Lab - paper-only trading lab.
# The service must run as a single uvicorn worker: the in-process risk lock is
# only authoritative when one process owns the database writes.

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project

COPY app ./app
COPY frontend ./frontend
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts

RUN useradd --create-home --shell /usr/sbin/nologin lab \
    && mkdir -p /app/data \
    && chown -R lab:lab /app

USER lab

EXPOSE 8000

# Migrations run before the server starts; create_all in the lifespan is a
# no-op once Alembic has built the schema.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
