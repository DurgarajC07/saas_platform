"""
Audit service — writes immutable audit-log entries.

Design rules:
  - log() NEVER raises — a failed audit write must never block the caller.
  - Callers may optionally await log() on the same session (same tx).
  - Query helpers (list_logs, get_log) raise NotFoundException on miss.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.core.exceptions import NotFoundException
from app.core.pagination import PaginationParams, paginate
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditRepository
from app.modules.audit.schemas import (
    AuditLogDetailResponse,
    AuditLogListResponse,
    AuditLogResponse,
)

logger = structlog.get_logger(__name__)


class AuditService:
    """Cross-cutting audit log service — injectable into any other service."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditRepository(session)

    # ── Write (never throws) ────────────────────────────────────────────

    async def log(
        self,
        *,
        action: str,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        org_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_type: str = "user",
        request: Request | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
        description: str | None = None,
    ) -> AuditLog | None:
        """
        Insert an AuditLog row and flush (does NOT commit — caller owns tx).
        Returns the persisted AuditLog instance, or None if write failed.
        **Never propagates exceptions.**
        """
        try:
            ip_address: str | None = None
            user_agent: str | None = None
            request_id: str | None = None

            if request is not None:
                ip_address = request.client.host if request.client else None
                user_agent = request.headers.get("User-Agent")
                request_id = str(getattr(request.state, "request_id", None) or "")

            return await self.repo.create(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                organization_id=org_id,
                actor_user_id=actor_user_id,
                actor_type=actor_type,
                old_values=old_values,
                new_values=new_values,
                description=description,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id or None,
                created_at=datetime.now(UTC),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "audit.log_write_failed",
                action=action,
                error=str(exc),
            )
            return None

    # ── Query ───────────────────────────────────────────────────────────

    async def list_logs(
        self,
        params: PaginationParams,
        *,
        org_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> AuditLogListResponse:
        rows, total = await self.repo.list_with_filters(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            start_date=start_date,
            end_date=end_date,
            limit=params.limit,
            offset=params.offset,
        )
        return AuditLogListResponse(
            logs=[AuditLogResponse.model_validate(r) for r in rows],
            pagination=paginate(total, params),
        )

    async def get_log(self, log_id: UUID) -> AuditLogDetailResponse:
        entry = await self.repo.get_by_id(log_id)
        if not entry:
            raise NotFoundException("Audit log entry not found")
        obj = AuditLogDetailResponse.model_validate(entry)
        # Compute and attach diff
        if obj.old_values and obj.new_values:
            all_keys = set(obj.old_values) | set(obj.new_values)
            diff: dict = {}
            for key in all_keys:
                old = obj.old_values.get(key)
                new = obj.new_values.get(key)
                if old != new:
                    diff[key] = {"before": old, "after": new}
            obj.diff = diff
        return obj

    async def export_csv(
        self,
        *,
        org_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> str:
        """
        Return CSV string of matching audit logs (up to 10,000 rows).
        For very large exports a Celery task would be enqueued; this
        synchronous version covers normal operational volumes.
        """
        rows, _ = await self.repo.list_with_filters(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            start_date=start_date,
            end_date=end_date,
            limit=10_000,
            offset=0,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "created_at", "organization_id", "actor_user_id",
            "actor_type", "action", "resource_type", "resource_id",
            "description", "ip_address", "request_id",
        ])
        for row in rows:
            writer.writerow([
                str(row.id),
                row.created_at.isoformat(),
                str(row.organization_id) if row.organization_id else "",
                str(row.actor_user_id) if row.actor_user_id else "",
                row.actor_type,
                row.action,
                row.resource_type or "",
                str(row.resource_id) if row.resource_id else "",
                row.description or "",
                row.ip_address or "",
                row.request_id or "",
            ])
        return output.getvalue()
