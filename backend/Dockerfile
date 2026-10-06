FROM python:3.13-slim

# uv (Section 4.5: current stable at planning time).
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

# FFmpeg for GET /api/health and later media processing.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Non-root backend user (Phase 1 decision). /data is created here, owned by
# `app`, so the named volume Compose mounts over it inherits this ownership
# on first start.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY alembic.ini docker-entrypoint.sh ./

USER app

EXPOSE 8000

CMD ["sh", "docker-entrypoint.sh"]
