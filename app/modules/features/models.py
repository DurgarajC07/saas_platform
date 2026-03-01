"""
Feature flags module ORM models.

Tables: features, plan_features, organization_feature_overrides
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import TimestampMixin


# ── Feature ───────────────────────────────────────────────────────────────

class Feature(Base, TimestampMixin):
    __tablename__ = "features"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    module: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Relationships
    plan_features: Mapped[list["PlanFeature"]] = relationship(
        "PlanFeature", back_populates="feature", cascade="all, delete-orphan", lazy="noload"
    )
    org_overrides: Mapped[list["OrganizationFeatureOverride"]] = relationship(
        "OrganizationFeatureOverride", back_populates="feature", cascade="all, delete-orphan", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<Feature key={self.key}>"


# ── PlanFeature ───────────────────────────────────────────────────────────

class PlanFeature(Base, TimestampMixin):
    __tablename__ = "plan_features"

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscription_plans.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    feature_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("features.id", ondelete="CASCADE"), primary_key=True, nullable=False)
    limit_value: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = boolean flag

    # Relationships
    plan: Mapped["SubscriptionPlan"] = relationship(
        "SubscriptionPlan", back_populates="plan_features", lazy="noload"
    )
    feature: Mapped["Feature"] = relationship("Feature", back_populates="plan_features", lazy="noload")

    def __repr__(self) -> str:
        return f"<PlanFeature plan={self.plan_id} feature={self.feature_id}>"


# ── OrganizationFeatureOverride ───────────────────────────────────────────

class OrganizationFeatureOverride(Base, TimestampMixin):
    __tablename__ = "organization_feature_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    feature_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("features.id", ondelete="CASCADE"), nullable=False)
    limit_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    feature: Mapped["Feature"] = relationship("Feature", back_populates="org_overrides", lazy="noload")

    __table_args__ = (
        UniqueConstraint("organization_id", "feature_id", name="uq_org_feature_override"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationFeatureOverride org={self.organization_id} feature={self.feature_id}>"
