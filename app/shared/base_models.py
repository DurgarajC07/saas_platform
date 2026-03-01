"""
SQLAlchemy declarative base model + reusable audit mixins.

Every concrete ORM model should inherit from Base + the relevant mixins:

    class MyModel(Base, TimestampMixin, SoftDeleteMixin):
        __tablename__ = "my_table"
        id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
        ...

Mixins are kept separate so models that don't need soft-delete can
opt out without losing timestamping.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


# Re-export Base so module models only need to import from shared.base_models
__all__ = ["Base", "TimestampMixin", "SoftDeleteMixin", "TimestampedModel"]


# ── Mixins ────────────────────────────────────────────────────────────────

class TimestampMixin:
    """Adds created_at / updated_at to any model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds deleted_at for soft-delete patterns."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        default=None,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# ── Convenience base combining all mixins ─────────────────────────────────

class TimestampedModel(Base, TimestampMixin, SoftDeleteMixin):
    """
    Abstract base used by most models — provides id, timestamps and soft-delete.
    Override __tablename__ in every concrete subclass.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

