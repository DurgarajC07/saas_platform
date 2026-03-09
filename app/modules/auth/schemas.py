"""
Auth module Pydantic schemas.

Request / response models for all auth endpoints.
All schemas inherit from CamelModel so they serialise to camelCase on the wire.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field, field_validator

from app.shared.base_schemas import CamelModel


# ── Registration / Login ───────────────────────────────────────────────────

class RegisterRequest(CamelModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=150)
    last_name: str = Field(min_length=1, max_length=150)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class LogoutRequest(CamelModel):
    """Optionally carry the refresh token so it can be denylisted too."""

    refresh_token: str | None = None


class RefreshRequest(CamelModel):
    refresh_token: str


class ForgotPasswordRequest(CamelModel):
    email: EmailStr


class ResetPasswordRequest(CamelModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class VerifyEmailRequest(CamelModel):
    token: str


# ── Responses ─────────────────────────────────────────────────────────────

class TokenResponse(CamelModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry


class UserResponse(CamelModel):
    id: UUID
    email: EmailStr
    first_name: str | None
    last_name: str | None
    display_name: str | None
    is_active: bool
    is_platform_admin: bool
    email_verified: bool
    two_factor_enabled: bool
    timezone: str
    locale: str
    created_at: datetime


class MessageResponse(CamelModel):
    message: str


class TwoFactorChallengeResponse(CamelModel):
    """Returned when 2FA is required to complete login."""

    code: str = "TWO_FACTOR_REQUIRED"
    message: str = "Two-factor authentication required"
    user_id: str  # Opaque — used in step 2 of 2FA flow


# ── OAuth2 ─────────────────────────────────────────────────────────────────

class OAuthRedirectResponse(CamelModel):
    """Returned from GET /oauth/{provider} — frontend performs the redirect."""

    authorization_url: str
    state: str


class OAuthProvidersResponse(CamelModel):
    """Returned from GET /oauth/providers — lists configured providers."""

    providers: list[str]  # e.g. ["google", "github"]


# ── Two-Factor Authentication (TOTP) ──────────────────────────────────────

class Setup2FAResponse(CamelModel):
    """Returned from POST /2fa/setup — contains provisioning URI for the QR code."""

    secret: str        # Raw base32 secret — show once, store nowhere client-side
    qr_uri: str        # otpauth:// URI — pass to a frontend QR renderer


class Confirm2FARequest(CamelModel):
    """Confirm TOTP setup by providing the first code from the authenticator app."""

    code: str = Field(min_length=6, max_length=8)


class BackupCodesResponse(CamelModel):
    """One-time delivery of backup codes — displayed once, never again."""

    backup_codes: list[str]


class Disable2FARequest(CamelModel):
    """Disable 2FA — requires current password and a valid TOTP code."""

    password: str
    code: str = Field(min_length=6, max_length=8)


class Verify2FARequest(CamelModel):
    """Step 2 of 2FA login — submit the TOTP code to complete authentication."""

    user_id: str
    code: str = Field(min_length=6, max_length=8)


class BackupCodeRequest(CamelModel):
    """Authenticate with a one-time backup code instead of TOTP."""

    user_id: str
    code: str = Field(min_length=8, max_length=20)


# ── Session Management ─────────────────────────────────────────────────────

class SessionResponse(CamelModel):
    """A single active session with device metadata."""

    id: UUID
    ip_address: str | None
    user_agent: str | None
    device_type: str | None
    last_active_at: datetime
    created_at: datetime
    is_current: bool = False


class SessionListResponse(CamelModel):
    sessions: list[SessionResponse]


# ── Password Change ────────────────────────────────────────────────────────

class ChangePasswordRequest(CamelModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v
