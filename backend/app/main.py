"""The FastAPI application factory.

Middleware order matters: the first entry in `middleware=` below is the
outermost, so every request meets the Host check before the Origin check
(ANALYSIS.md Section 3.7; Phase 1's security baseline).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import api_router
from app.core import outbound
from app.core.config import get_config
from app.core.logging import configure_logging
from app.core.security import OriginCheckMiddleware
from app.db.session import engine
from app.services.ffmpeg import tool_version

_logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = get_config()
    config.media_dir.mkdir(parents=True, exist_ok=True)

    # Read once at startup (Phase 1 decision): GET /api/health just reports these,
    # it never shells out on every request.
    app.state.ffmpeg_version = await tool_version("ffmpeg")
    app.state.ffprobe_version = await tool_version("ffprobe")
    _logger.info(
        "startup: ffmpeg=%s ffprobe=%s", app.state.ffmpeg_version, app.state.ffprobe_version
    )

    outbound.start()

    yield

    await outbound.close()
    await engine.dispose()


def create_app() -> FastAPI:
    configure_logging(get_config().log_level)

    app = FastAPI(
        title="Visio Studio",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url=None,
        lifespan=_lifespan,
        middleware=[
            # Outermost: reject requests to a Host other than localhost/127.0.0.1.
            Middleware(
                TrustedHostMiddleware,
                allowed_hosts=["localhost", "127.0.0.1"],
                www_redirect=False,
            ),
            # Inside that: reject state-changing requests whose Origin doesn't match Host.
            Middleware(OriginCheckMiddleware),
        ],
    )
    app.include_router(api_router)
    return app


app = create_app()
