"""
API Management router.

Registered in main.py at prefix /api/v1 so routes resolve to:

  API Keys
  ─────────────────────────────────────────────────────────────────────────
  POST   /api/v1/api-keys                     Create a new API key (JWT)
  GET    /api/v1/api-keys                     List org API keys (JWT)
  DELETE /api/v1/api-keys/{key_id}            Revoke an API key (JWT)

  Webhooks
  ─────────────────────────────────────────────────────────────────────────
  POST   /api/v1/webhooks                     Create webhook + return signing secret
  GET    /api/v1/webhooks                     List org webhooks
  GET    /api/v1/webhooks/{webhook_id}         Get single webhook
  PATCH  /api/v1/webhooks/{webhook_id}         Update webhook
  DELETE /api/v1/webhooks/{webhook_id}         Soft delete webhook
  GET    /api/v1/webhooks/{webhook_id}/deliveries  Delivery history

  All management endpoints require a valid JWT (Bearer token).
  API key auth (X-API-Key: sk_live_...) is available for programmatic access
  to other modules — see dependencies.py.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_redis
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.rbac.dependencies import get_current_org_id
from app.modules.api_management.dependencies import get_api_key_auth, require_scope
from app.modules.api_management.models import APIKey
from app.modules.api_management.schemas import (
    APIKeyListResponse,
    APIKeyResponse,
    CreateKeyRequest,
    CreateKeyResponse,
    CreateWebhookRequest,
    CreateWebhookResponse,
    UpdateWebhookRequest,
    WebhookDeliveryListResponse,
    WebhookListResponse,
    WebhookResponse,
)
from app.modules.api_management.service import APIKeyService, WebhookService

router = APIRouter()

# ── Type aliases ─────────────────────────────────────────────────────────────

CurrentUser = Annotated[User, Depends(get_current_user)]
OrgID       = Annotated[UUID, Depends(get_current_org_id)]
DB          = Annotated[AsyncSession, Depends(get_db)]
Redis       = Annotated[aioredis.Redis, Depends(get_redis)]


# ═══════════════════════════════════════════════════════════════════════════
# API KEY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/api-keys",
    response_model=CreateKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
    tags=["API Keys"],
)
async def create_api_key(
    body: CreateKeyRequest,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> CreateKeyResponse:
    """
    Generate a new API key for the organisation.

    **The raw key is returned only once — store it immediately.**
    Only the prefix and a SHA-256 hash are persisted.
    """
    svc = APIKeyService(db, redis)
    return await svc.create_api_key(org_id, current_user, body)


@router.get(
    "/api-keys",
    response_model=APIKeyListResponse,
    summary="List API keys",
    tags=["API Keys"],
)
async def list_api_keys(
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_revoked: bool = Query(default=False),
) -> APIKeyListResponse:
    """List all API keys belonging to the organisation (no raw keys returned)."""
    svc = APIKeyService(db, redis)
    return await svc.list_keys(
        org_id,
        page=page,
        page_size=page_size,
        include_revoked=include_revoked,
    )


@router.delete(
    "/api-keys/{key_id}",
    response_model=APIKeyResponse,
    summary="Revoke API key",
    tags=["API Keys"],
)
async def revoke_api_key(
    key_id: UUID,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
    redis: Redis,
) -> APIKeyResponse:
    """Revoke an API key. Revoked keys are rejected immediately."""
    svc = APIKeyService(db, redis)
    return await svc.revoke_key(key_id, org_id)


# ═══════════════════════════════════════════════════════════════════════════
# WEBHOOK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/webhooks",
    response_model=CreateWebhookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create webhook",
    tags=["Webhooks"],
)
async def create_webhook(
    body: CreateWebhookRequest,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
) -> CreateWebhookResponse:
    """
    Register a new webhook endpoint.

    **The HMAC signing secret is returned only once — store it immediately.**
    Use it to verify `X-Webhook-Signature` on incoming deliveries.
    """
    svc = WebhookService(db)
    return await svc.create_webhook(org_id, current_user, body)


@router.get(
    "/webhooks",
    response_model=WebhookListResponse,
    summary="List webhooks",
    tags=["Webhooks"],
)
async def list_webhooks(
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> WebhookListResponse:
    """List all webhooks for the organisation."""
    svc = WebhookService(db)
    return await svc.list_webhooks(org_id, page=page, page_size=page_size)


@router.get(
    "/webhooks/{webhook_id}/deliveries",
    response_model=WebhookDeliveryListResponse,
    summary="Webhook delivery history",
    tags=["Webhooks"],
)
async def list_webhook_deliveries(
    webhook_id: UUID,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> WebhookDeliveryListResponse:
    """List delivery attempts for a specific webhook, newest first."""
    svc = WebhookService(db)
    return await svc.list_deliveries(
        webhook_id, org_id, page=page, page_size=page_size
    )


@router.get(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Get webhook",
    tags=["Webhooks"],
)
async def get_webhook(
    webhook_id: UUID,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
) -> WebhookResponse:
    """Retrieve a single webhook by ID."""
    svc = WebhookService(db)
    return await svc.get_webhook(webhook_id, org_id)


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Update webhook",
    tags=["Webhooks"],
)
async def update_webhook(
    webhook_id: UUID,
    body: UpdateWebhookRequest,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
) -> WebhookResponse:
    """Update webhook URL, events subscription, or active status."""
    svc = WebhookService(db)
    return await svc.update_webhook(webhook_id, org_id, body)


@router.delete(
    "/webhooks/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete webhook",
    tags=["Webhooks"],
)
async def delete_webhook(
    webhook_id: UUID,
    current_user: CurrentUser,
    org_id: OrgID,
    db: DB,
) -> None:
    """Soft-delete a webhook. Active deliveries are not affected."""
    svc = WebhookService(db)
    await svc.delete_webhook(webhook_id, org_id)


# ═══════════════════════════════════════════════════════════════════════════
# API KEY AUTHENTICATION TEST ENDPOINT
# Demonstrates programmatic API-key auth and scope enforcement.
# ═══════════════════════════════════════════════════════════════════════════


class APIKeyInfoResponse(APIKeyResponse):
    """Extends APIKeyResponse with the authenticated scopes visible at runtime."""
    pass


@router.get(
    "/api-keys/verify",
    response_model=APIKeyInfoResponse,
    summary="Verify API key",
    tags=["API Keys"],
    description=(
        "Authenticate using `X-API-Key: sk_live_...` or `Authorization: Bearer sk_live_...`. "
        "Returns the key's metadata if valid. Used for testing API-key auth."
    ),
)
async def verify_api_key(
    api_key: Annotated[APIKey, Depends(get_api_key_auth)],
) -> APIKeyInfoResponse:
    """
    Returns API key metadata when authenticated via X-API-Key or Bearer sk_...
    """
    return APIKeyInfoResponse.model_validate(api_key)


@router.get(
    "/api-keys/verify-scoped",
    response_model=APIKeyInfoResponse,
    summary="Verify scoped API key",
    tags=["API Keys"],
    description=(
        "Like /verify but also enforces the `api:read` scope. "
        "Returns 403 if the key lacks that scope."
    ),
)
async def verify_scoped_api_key(
    api_key: Annotated[APIKey, Depends(require_scope("api:read"))],
) -> APIKeyInfoResponse:
    """Returns key metadata for a key that possesses the ``api:read`` scope."""
    return APIKeyInfoResponse.model_validate(api_key)
