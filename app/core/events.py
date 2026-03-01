"""
FastAPI lifespan context manager.

Handles application startup and shutdown:
  - Creates / disposes the SQLAlchemy async engine
  - Initialises / closes the Redis connection pool
  - Configures structured logging
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI

from app.config import get_settings
from app.core.database import create_engine, create_session_factory
from app.core.logging import configure_logging
from app.core.redis import close_redis, get_redis

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── STARTUP ───────────────────────────────────────────────────────────
    settings = get_settings()

    configure_logging(debug=settings.DEBUG)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = await get_redis()
    app.state.settings = settings

    await logger.ainfo("Application startup complete", environment=settings.ENVIRONMENT)

    yield

    # ── SHUTDOWN ──────────────────────────────────────────────────────────
    await engine.dispose()
    await close_redis()
    await logger.ainfo("Application shutdown complete")
