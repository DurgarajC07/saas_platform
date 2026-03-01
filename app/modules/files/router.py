"""
Files router.

Registered in main.py at prefix /api/v1/files.  All routes:

  POST   /files/upload                    Upload a file (multipart/form-data)
  GET    /files                           List files (paginated, filterable)
  GET    /files/{file_id}                 Get file metadata
  GET    /files/{file_id}/download        Presigned redirect (S3) or byte stream (local)
  DELETE /files/{file_id}                 Soft-delete + async storage cleanup

All endpoints require a valid JWT (Bearer token).
Org context is read from the X-Organization-ID header via TenantContextMiddleware.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.dependencies import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.rbac.dependencies import get_current_org_id
from app.modules.files.schemas import (
    DeleteFileResponse,
    DownloadUrlResponse,
    FileListResponse,
    FileResponse,
    UploadResponse,
)
from app.modules.files.service import FileService

router = APIRouter()

# ── Type aliases ─────────────────────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_user)]
DB          = Annotated[AsyncSession, Depends(get_db)]
OrgID       = Annotated[UUID | None, Depends(get_current_org_id)]


def _svc(db: DB) -> FileService:
    return FileService(session=db)


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file",
    description=(
        "Accepts multipart/form-data. MIME type is detected from file content "
        "via libmagic (not extension). Identical files are deduplicated via "
        "SHA-256 checksum — the existing record is returned with `deduplicated=true`."
    ),
)
async def upload_file(
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
    file: UploadFile = File(..., description="File to upload (max 100 MB)"),
    attachable_type: str | None = Query(None, description="Polymorphic owner type, e.g. 'invoice'"),
    attachable_id: UUID | None = Query(None, description="Polymorphic owner UUID"),
    is_public: bool = Query(False, description="Whether the file is publicly accessible"),
) -> UploadResponse:
    svc = FileService(session=db)
    return await svc.upload_file(
        file=file,
        uploader=current_user,
        org_id=org_id,
        attachable_type=attachable_type,
        attachable_id=attachable_id,
        is_public=is_public,
    )


# ── List ──────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=FileListResponse,
    summary="List files",
)
async def list_files(
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
    attachable_type: str | None = Query(None),
    attachable_id: UUID | None = Query(None),
    mime_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> FileListResponse:
    svc = FileService(session=db)
    return await svc.list_files(
        org_id=org_id,
        attachable_type=attachable_type,
        attachable_id=attachable_id,
        mime_type=mime_type,
        page=page,
        page_size=page_size,
    )


# ── Get metadata ──────────────────────────────────────────────────────────────

@router.get(
    "/{file_id}",
    response_model=FileResponse,
    summary="Get file metadata",
)
async def get_file(
    file_id: UUID,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
) -> FileResponse:
    svc = FileService(session=db)
    return await svc.get_file(
        file_id=file_id,
        requesting_user=current_user,
        org_id=org_id,
    )


# ── Download ──────────────────────────────────────────────────────────────────

@router.get(
    "/{file_id}/download",
    summary="Download a file",
    description=(
        "For S3 storage: redirects (302) to a time-limited presigned URL. "
        "For local storage: streams the file bytes directly."
    ),
    responses={
        200: {"description": "File bytes (local storage)"},
        302: {"description": "Redirect to presigned URL (S3 storage)"},
    },
)
async def download_file(
    file_id: UUID,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
) -> Response:
    settings = get_settings()
    svc = FileService(session=db)

    if settings.STORAGE_PROVIDER == "s3":
        # Redirect the client to the time-limited presigned S3 URL
        url_resp: DownloadUrlResponse = await svc.get_download_url(
            file_id=file_id,
            requesting_user=current_user,
            org_id=org_id,
        )
        return RedirectResponse(url=url_resp.url, status_code=302)

    # Local storage: stream bytes
    content, mime_type = await svc.stream_file(
        file_id=file_id,
        requesting_user=current_user,
        org_id=org_id,
    )
    # Retrieve the original filename for Content-Disposition
    file_meta = await svc.get_file(
        file_id=file_id,
        requesting_user=current_user,
        org_id=org_id,
    )
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file_meta.original_name}"',
            "Content-Length": str(len(content)),
        },
    )


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete(
    "/{file_id}",
    response_model=DeleteFileResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a file",
    description=(
        "Soft-deletes the DB record immediately and enqueues async Celery task "
        "to remove the physical object from storage."
    ),
)
async def delete_file(
    file_id: UUID,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
) -> DeleteFileResponse:
    svc = FileService(session=db)
    return await svc.delete_file(
        file_id=file_id,
        requesting_user=current_user,
        org_id=org_id,
    )
