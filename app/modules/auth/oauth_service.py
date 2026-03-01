"""
OAuth2 Social Login service.

Supports Google, GitHub, and Microsoft via the authorization code grant.

Flow:
  1. GET /oauth/{provider}              → returns authorization_url + state
  2. Provider redirects → GET /oauth/{provider}/callback?code=…&state=…
  3. Exchange code → fetch profile → upsert user_oauth_accounts
  4. Issue JWT pair → redirect front-end to FRONTEND_URL with tokens

State is stored in Redis (TTL 10 min) to prevent CSRF.
"""

from __future__ import annotations

import secrets
import string
from typing import Any
from uuid import uuid4

import httpx
import structlog
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from app.core.security.encryption import encrypt
from app.modules.auth.models import User
from app.modules.auth.repository import OAuthAccountRepository, UserRepository
from app.modules.auth.schemas import TokenResponse
from app.modules.auth.service import AuthService

logger = structlog.get_logger(__name__)

# ── Provider configurations ───────────────────────────────────────────────

def _get_providers() -> dict[str, dict[str, str]]:
    """Build provider config from settings (lazy, so settings are loaded once)."""
    settings = get_settings()
    return {
        "google": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
            "scope": "openid email profile",
        },
        "github": {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "emails_url": "https://api.github.com/user/emails",
            "scope": "read:user user:email",
        },
        "microsoft": {
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "authorize_url": (
                "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
            ),
            "token_url": (
                "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            ),
            "userinfo_url": "https://graph.microsoft.com/v1.0/me",
            "scope": "openid email profile",
        },
    }


_OAUTH_STATE_PREFIX = "oauth_state:"
_OAUTH_STATE_TTL = 600  # 10 minutes


def _normalize_profile(
    provider: str, raw: dict[str, Any], *, extra_email: str = ""
) -> dict[str, Any]:
    """
    Normalise provider-specific profile dicts into a common shape:
    {id, email, first_name, last_name, raw}
    """
    alphabet = string.ascii_uppercase + string.digits
    if provider == "google":
        return {
            "id": raw["sub"],
            "email": raw.get("email") or extra_email,
            "first_name": raw.get("given_name", ""),
            "last_name": raw.get("family_name", ""),
            "raw": raw,
        }
    elif provider == "github":
        parts = (raw.get("name") or "").split(" ", 1)
        return {
            "id": str(raw["id"]),
            "email": extra_email or raw.get("email") or "",
            "first_name": parts[0],
            "last_name": parts[1] if len(parts) > 1 else "",
            "raw": raw,
        }
    elif provider == "microsoft":
        return {
            "id": raw.get("id", ""),
            "email": raw.get("mail") or raw.get("userPrincipalName") or extra_email,
            "first_name": raw.get("givenName", ""),
            "last_name": raw.get("surname", ""),
            "raw": raw,
        }
    raise BadRequestException(f"Unknown OAuth provider: {provider}")


class OAuthService:
    """Handles the OAuth2 authorization code grant for all supported providers."""

    def __init__(self, session: AsyncSession, redis: aioredis.Redis) -> None:
        self.user_repo = UserRepository(User, session)
        self.oauth_repo = OAuthAccountRepository(session)
        self.session = session
        self.redis = redis

    def _get_provider_config(self, provider: str) -> dict[str, str]:
        providers = _get_providers()
        cfg = providers.get(provider)
        if not cfg:
            raise NotFoundException(f"OAuth provider '{provider}' is not supported")
        return cfg

    def _redirect_uri(self, provider: str) -> str:
        base = get_settings().OAUTH_REDIRECT_BASE_URL.rstrip("/")
        return f"{base}/api/v1/auth/oauth/{provider}/callback"

    # ── Step 1: Generate authorization URL ────────────────────────────────

    async def get_authorization_url(self, provider: str) -> tuple[str, str]:
        """
        Build the provider's authorization URL and persist a CSRF state token.
        Returns (authorization_url, state).
        """
        cfg = self._get_provider_config(provider)

        state = secrets.token_urlsafe(32)
        await self.redis.setex(
            f"{_OAUTH_STATE_PREFIX}{state}", _OAUTH_STATE_TTL, provider
        )

        params = {
            "client_id": cfg["client_id"],
            "redirect_uri": self._redirect_uri(provider),
            "response_type": "code",
            "scope": cfg["scope"],
            "state": state,
        }
        if provider == "google":
            params["access_type"] = "offline"
            params["prompt"] = "select_account"

        query = "&".join(f"{k}={v}" for k, v in params.items())
        auth_url = f"{cfg['authorize_url']}?{query}"
        return auth_url, state

    # ── Step 2: Exchange code and fetch profile ────────────────────────────

    async def _exchange_code(
        self, provider: str, code: str
    ) -> dict[str, Any]:
        """Exchange the authorization code for an access token."""
        cfg = self._get_provider_config(provider)
        redirect_uri = self._redirect_uri(provider)

        payload = {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        headers: dict[str, str] = {"Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(cfg["token_url"], data=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def _fetch_profile(
        self, provider: str, token_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Fetch the user's profile from the provider's userinfo endpoint."""
        cfg = self._get_provider_config(provider)
        access_token = token_data.get("access_token", "")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(cfg["userinfo_url"], headers=headers)
            resp.raise_for_status()
            raw = resp.json()

            extra_email = ""
            # GitHub: email may be null when set to private — fetch from emails API
            if provider == "github" and not raw.get("email"):
                emails_url = cfg.get("emails_url", "")
                if emails_url:
                    emails_resp = await client.get(emails_url, headers=headers)
                    if emails_resp.is_success:
                        for entry in emails_resp.json():
                            if entry.get("primary") and entry.get("verified"):
                                extra_email = entry["email"]
                                break

        return _normalize_profile(provider, raw, extra_email=extra_email)

    # ── Step 3: Upsert user + oauth account ───────────────────────────────

    async def get_or_create_user(
        self, provider: str, profile: dict[str, Any]
    ) -> User:
        """
        Find or create a User from an OAuth profile.

        Priority:
          1. Existing oauth_account row → return linked user
          2. Existing user with matching email → link accounts
          3. Create new user (email_verified=True from OAuth)
        """
        provider_user_id = str(profile["id"])
        email = (profile.get("email") or "").lower().strip()
        if not email:
            raise BadRequestException(
                "OAuth provider did not return an email address. "
                "Ensure your account has a verified email."
            )

        # 1. Check if OAuth account already linked
        oauth_account = await self.oauth_repo.get_by_provider(provider, provider_user_id)
        if oauth_account:
            user = await self.user_repo.get_active_by_id(oauth_account.user_id)
            if not user:
                raise UnauthorizedException("Account is inactive")
            return user

        # 2. Find existing user by email — link the new OAuth provider
        user = await self.user_repo.get_by_email(email)
        if not user:
            # 3. Register new user — email is trusted (verified by provider)
            user = await self.user_repo.create(
                id=uuid4(),
                email=email,
                email_verified=True,
                first_name=profile.get("first_name", ""),
                last_name=profile.get("last_name", ""),
                display_name=(
                    f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
                    or email
                ),
            )

        # Create OAuth account record
        raw_profile = profile.get("raw", {})
        await self.oauth_repo.create(
            id=uuid4(),
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=email,
            raw_profile=raw_profile,
        )

        # If user was unverified (registered by password before), verify now
        if not user.email_verified:
            await self.user_repo.update(user.id, email_verified=True)

        await self.session.commit()
        logger.info(
            "oauth_account_linked",
            provider=provider,
            user_id=str(user.id),
        )
        return user

    # ── Full callback flow ─────────────────────────────────────────────────

    async def handle_callback(
        self,
        provider: str,
        code: str,
        state: str,
        ip: str | None = None,
        user_agent: str = "",
    ) -> TokenResponse:
        """
        Validate state, exchange code, fetch profile, upsert user, issue tokens.
        Raises UnauthorizedException on invalid state.
        """
        # Verify CSRF state
        stored = await self.redis.get(f"{_OAUTH_STATE_PREFIX}{state}")
        if not stored or stored != provider:
            raise UnauthorizedException("Invalid or expired OAuth state")
        await self.redis.delete(f"{_OAUTH_STATE_PREFIX}{state}")

        try:
            token_data = await self._exchange_code(provider, code)
        except httpx.HTTPError as exc:
            raise BadRequestException(f"OAuth token exchange failed: {exc}") from exc

        try:
            profile = await self._fetch_profile(provider, token_data)
        except httpx.HTTPError as exc:
            raise BadRequestException(f"OAuth profile fetch failed: {exc}") from exc

        user = await self.get_or_create_user(provider, profile)

        # Use AuthService._issue_tokens to build the JWT pair + session row
        auth_service = AuthService(self.session, self.redis)
        return await auth_service._issue_tokens(user, ip, user_agent)
