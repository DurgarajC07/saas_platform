"""
Async SQLAlchemy engine + session factory + declarative Base.

Usage:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

The module-level ``engine`` and ``AsyncSessionFactory`` are kept for
convenience in tests and Alembic migrations; the app itself uses the
factory functions so the engine is bound to lifespan.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings, get_settings


# ── Declarative Base ───────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """All ORM models inherit from this Base."""


# ── Factory functions (used by lifespan) ──────────────────────────────────
def create_engine(settings: Settings) -> AsyncEngine:
    """Create an async SQLAlchemy engine from settings."""
    return create_async_engine(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,    # drops stale connections
        pool_recycle=3600,     # recycle connections every hour
        echo=settings.DATABASE_ECHO,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# ── Module-level singletons (tests / Alembic) ─────────────────────────────
_settings = get_settings()

engine = create_engine(_settings)

AsyncSessionFactory: async_sessionmaker[AsyncSession] = create_session_factory(engine)


# ── FastAPI dependency ─────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional database session per request."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise