"""
Auth router — mounts all authentication endpoints under /api/v1/auth.

Endpoints
---------
POST   /register                 Create account + send verification email
GET    /verify-email             Verify email via token in query string
POST   /login                    Authenticate → issue JWT access + refresh tokens
POST   /refresh                  Rotate refresh token → new token pair
POST   /logout                   Denylist tokens (requires valid access token)
POST   /forgot-password          Request a password-reset link (anti-enumeration safe)
POST   /reset-password           Set new password via reset token
GET    /me                       Return current user profile (requires auth)
--- OAuth2 ---
GET    /oauth/{provider}         Initiate OAuth2 flow → return authorization URL
GET    /oauth/{provider}/callback  Handle OAuth2 callback → issue JWT pair
--- Two-Factor Authentication ---
POST   /2fa/setup                Generate TOTP secret + provisioning URI
POST   /2fa/confirm              Confirm setup with first code → get backup codes
DELETE /2fa/disable              Disable 2FA (requires password + TOTP)
POST   /2fa/verify               Complete 2FA-required login with TOTP code
POST   /2fa/backup               Complete 2FA-required login with backup code
--- Sessions ---
GET    /sessions                 List all active sessions for current user
DELETE /sessions/{session_id}   Revoke a specific session
DELETE /sessions                 Revoke all sessions except current
--- Account ---
POST   /password/change          Change password (requires current password)
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings

from app.core.rate_limit import (
    ForgotPasswordLimit,
    LoginRateLimit,
    RefreshTokenLimit,
    RegisterRateLimit,
)
from app.modules.auth.dependencies import (
    AuthDeps,
    get_current_session_id,
    get_current_user,
    oauth2_scheme,
)
from app.modules.auth.exceptions import TwoFactorRequiredException
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    BackupCodeRequest,
    BackupCodesResponse,
    ChangePasswordRequest,
    Confirm2FARequest,
    Disable2FARequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    OAuthRedirectResponse,
    OAuthProvidersResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionListResponse,
    SessionResponse,
    Setup2FAResponse,
    TokenResponse,
    TwoFactorChallengeResponse,
    UpdateProfileRequest,
    UserResponse,
    Verify2FARequest,
)
from app.modules.auth.service import AuthService

router = APIRouter()

_REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """
    Carry the refresh token to the browser as an httpOnly cookie instead of
    (only) the response body, so a frontend that stops persisting it to
    localStorage/JS-readable storage still gets silent token refresh.

    The response body still includes ``refresh_token`` too (unchanged) —
    non-browser API clients that store it themselves keep working exactly
    as before; this is additive, not a breaking change to the API contract.
    Scoped to ``/api/v1/auth`` (the only paths that ever need to read it)
    rather than the whole site.
    """
    settings = get_settings()
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
        secure=settings.is_production,
        samesite="lax",
    )


# ── Register ───────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
    dependencies=[Depends(RegisterRateLimit)],
)
async def register(
    data: RegisterRequest,
    deps: Annotated[AuthDeps, Depends()],
) -> User:
    """
    Create a new user account and send an email-verification link.
    Returns the created user (email_verified=False until the link is clicked).
    """
    service = AuthService(deps.db, deps.redis)
    return await service.register(data)


# ── Email Verification ─────────────────────────────────────────────────────

@router.get(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email address",
)
async def verify_email(
    token: str = Query(..., description="Verification token from the email link"),
    deps: AuthDeps = Depends(),
) -> MessageResponse:
    """Activate the user's account by consuming an email-verification token."""
    service = AuthService(deps.db, deps.redis)
    await service.verify_email(token)
    return MessageResponse(message="Email verified successfully")


# ── Login ──────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=None,
    summary="Login — obtain access and refresh tokens",
    responses={
        200: {"model": TokenResponse, "description": "Successful login — token pair returned"},
        202: {"model": TwoFactorChallengeResponse, "description": "2FA required"},
    },
    dependencies=[Depends(LoginRateLimit)],
)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    deps: Annotated[AuthDeps, Depends()],
) -> TokenResponse | TwoFactorChallengeResponse:
    """
    Authenticate with email + password.
    Returns a TokenResponse on success.
    Returns a TwoFactorChallengeResponse (HTTP 200) when 2FA is enabled.
    Rate-limited to 5 attempts per IP per 15 minutes.
    """
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("User-Agent", "")
    service = AuthService(deps.db, deps.redis)
    try:
        result = await service.login(data, ip, user_agent)
        _set_refresh_cookie(response, result.refresh_token)
        return result
    except TwoFactorRequiredException as exc:
        return TwoFactorChallengeResponse(user_id=exc.user_id)


@router.post(
    "/login/form",
    response_model=TokenResponse,
    include_in_schema=False,  # OpenAPI /docs "Try it out" needs form-encoded login
    summary="Login (form-encoded, for Swagger UI)",
    dependencies=[Depends(LoginRateLimit)],
)
async def login_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    deps: Annotated[AuthDeps, Depends()],
) -> TokenResponse:
    """Adapter that maps OAuth2PasswordRequestForm to LoginRequest."""
    data = LoginRequest(email=form.username, password=form.password)
    ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("User-Agent", "")
    service = AuthService(deps.db, deps.redis)
    try:
        result = await service.login(data, ip, user_agent)
        _set_refresh_cookie(response, result.refresh_token)
        return result
    except TwoFactorRequiredException:
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("2FA is required — use the /login endpoint")


# ── Refresh Tokens ─────────────────────────────────────────────────────────

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate refresh token",
    dependencies=[Depends(RefreshTokenLimit)],
)
async def refresh(
    data: RefreshRequest,
    request: Request,
    response: Response,
    deps: Annotated[AuthDeps, Depends()],
) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    The old refresh token is immediately denylisted (rotation).

    The token is taken from the request body if present (non-browser API
    clients), otherwise from the httpOnly ``refresh_token`` cookie set by
    ``/login`` (browser clients, which no longer send it in the body at
    all). Either way the rotated token is written back to both the body
    and the cookie.
    """
    from app.core.exceptions import UnauthorizedException

    token = data.refresh_token or request.cookies.get(_REFRESH_COOKIE_NAME)
    if not token:
        raise UnauthorizedException("Refresh token missing")

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent", "")
    service = AuthService(deps.db, deps.redis)
    result = await service.refresh_tokens(
        RefreshRequest(refresh_token=token), ip=ip, user_agent=user_agent
    )
    _set_refresh_cookie(response, result.refresh_token)
    return result


# ── Logout ─────────────────────────────────────────────────────────────────

@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout — revoke tokens",
)
async def logout(
    data: LogoutRequest,
    request: Request,
    response: Response,
    access_token: Annotated[str, Depends(oauth2_scheme)],
    _current_user: Annotated[User, Depends(get_current_user)],  # validates token first
    deps: Annotated[AuthDeps, Depends()],
) -> None:
    """
    Denylist the current access token and (optionally) the refresh token.
    The access token is extracted from the Authorization header automatically.
    Pass the refresh token in the request body to revoke it in the same call,
    or it's read from the httpOnly cookie if the body omits it. The cookie
    is cleared either way.
    """
    refresh_token = data.refresh_token or request.cookies.get(_REFRESH_COOKIE_NAME)
    service = AuthService(deps.db, deps.redis)
    await service.logout(access_token, refresh_token)
    _clear_refresh_cookie(response)


# ── Forgot Password ────────────────────────────────────────────────────────

@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password-reset link",
    dependencies=[Depends(ForgotPasswordLimit)],
)
async def forgot_password(
    data: ForgotPasswordRequest,
    deps: Annotated[AuthDeps, Depends()],
) -> MessageResponse:
    """
    Send a password-reset email if the address is registered.
    Always returns success to prevent user-enumeration attacks.
    """
    service = AuthService(deps.db, deps.redis)
    await service.forgot_password(data)
    return MessageResponse(
        message="If that email is registered, a reset link has been sent"
    )


# ── Reset Password ─────────────────────────────────────────────────────────

@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password via token",
)
async def reset_password(
    data: ResetPasswordRequest,
    deps: Annotated[AuthDeps, Depends()],
) -> MessageResponse:
    """
    Validate the password-reset token and update the user's password.
    All existing sessions are revoked — the user must log in again.
    """
    service = AuthService(deps.db, deps.redis)
    await service.reset_password(data)
    return MessageResponse(message="Password updated successfully. Please log in again.")


# ── Current User ───────────────────────────────────────────────────────────

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the profile of the currently authenticated user."""
    return current_user


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile",
)
async def update_me(
    data: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    deps: Annotated[AuthDeps, Depends()],
) -> User:
    """Update mutable profile fields (name, timezone, locale, avatar, phone)."""
    svc = AuthService(deps.db, deps.redis)
    return await svc.update_profile(current_user, data)


# ── OAuth2 ─────────────────────────────────────────────────────────────────

@router.get(    "/oauth/providers",
    response_model=OAuthProvidersResponse,
    summary="List configured OAuth2 providers",
)
async def oauth_providers() -> OAuthProvidersResponse:
    """
    Return the list of OAuth2 providers that have credentials configured.
    The frontend uses this to conditionally show/hide social login buttons.
    """
    from app.modules.auth.oauth_service import _get_providers

    return OAuthProvidersResponse(providers=list(_get_providers().keys()))


@router.get(    "/oauth/{provider}",
    response_model=OAuthRedirectResponse,
    summary="Initiate OAuth2 social login",
)
async def oauth_authorize(
    provider: str,
    deps: Annotated[AuthDeps, Depends()],
) -> OAuthRedirectResponse:
    """
    Generate the authorization URL for the given OAuth2 provider.
    The frontend should redirect the user's browser to `authorization_url`.
    The `state` value will be validated in the callback to prevent CSRF.
    """
    from app.modules.auth.oauth_service import OAuthService

    service = OAuthService(deps.db, deps.redis)
    auth_url, state = await service.get_authorization_url(provider)
    return OAuthRedirectResponse(authorization_url=auth_url, state=state)


@router.get(
    "/oauth/{provider}/callback",
    summary="Handle OAuth2 callback from provider",
    response_class=RedirectResponse,
)
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query(..., description="CSRF state token"),
    deps: AuthDeps = Depends(),
) -> RedirectResponse:
    """
    Receive the OAuth2 authorization code, exchange it for tokens,
    upsert the user account, and redirect to the frontend with the access
    token.

    Redirect target: FRONTEND_URL/oauth/callback?accessToken=…&tokenType=…&expiresIn=…

    The refresh token is deliberately NOT put in this URL — a query string
    ends up in browser history and in any server/proxy access log it
    passes through, which is a worse exposure than localStorage ever was.
    It's set as the same httpOnly cookie ``/login`` uses instead.
    """
    from app.config import get_settings
    from app.modules.auth.oauth_service import OAuthService

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent", "")
    service = OAuthService(deps.db, deps.redis)
    tokens = await service.handle_callback(provider, code, state, ip, user_agent)

    frontend_url = get_settings().FRONTEND_URL.rstrip("/")
    redirect_to = (
        f"{frontend_url}/oauth/callback"
        f"?accessToken={tokens.access_token}"
        f"&tokenType={tokens.token_type}"
        f"&expiresIn={tokens.expires_in}"
    )
    response = RedirectResponse(url=redirect_to, status_code=status.HTTP_302_FOUND)
    _set_refresh_cookie(response, tokens.refresh_token)
    return response


# ── Two-Factor Authentication (TOTP) ──────────────────────────────────────

@router.post(
    "/2fa/setup",
    response_model=Setup2FAResponse,
    summary="Initiate TOTP 2FA setup",
)
async def setup_2fa(
    current_user: Annotated[User, Depends(get_current_user)],
    deps: Annotated[AuthDeps, Depends()],
) -> Setup2FAResponse:
    """
    Generate a TOTP secret and provisioning URI for QR code display.
    The user must scan the QR code and confirm with POST /2fa/confirm.
    """
    from app.modules.auth.two_factor_service import TwoFactorService

    service = TwoFactorService(deps.db, deps.redis)
    result = await service.setup_totp(current_user)
    return Setup2FAResponse(secret=result["secret"], qr_uri=result["qr_uri"])


@router.post(
    "/2fa/confirm",
    response_model=BackupCodesResponse,
    summary="Confirm TOTP setup and receive backup codes",
)
async def confirm_2fa(
    data: Confirm2FARequest,
    current_user: Annotated[User, Depends(get_current_user)],
    deps: Annotated[AuthDeps, Depends()],
) -> BackupCodesResponse:
    """
    Validate the first TOTP code from the authenticator app.
    On success, 2FA is enabled and 10 one-time backup codes are returned.
    Store these backup codes safely — they are displayed only once.
    """
    from app.modules.auth.two_factor_service import TwoFactorService

    service = TwoFactorService(deps.db, deps.redis)
    raw_codes = await service.confirm_totp_setup(current_user, data.code)
    return BackupCodesResponse(backup_codes=raw_codes)


@router.delete(
    "/2fa/disable",
    response_model=MessageResponse,
    summary="Disable two-factor authentication",
)
async def disable_2fa(
    data: Disable2FARequest,
    current_user: Annotated[User, Depends(get_current_user)],
    deps: Annotated[AuthDeps, Depends()],
) -> MessageResponse:
    """
    Disable TOTP 2FA after verifying the current password and a valid TOTP code.
    All backup codes are also deleted.
    """
    from app.modules.auth.two_factor_service import TwoFactorService

    service = TwoFactorService(deps.db, deps.redis)
    await service.disable_2fa(current_user, data.password, data.code)
    return MessageResponse(message="Two-factor authentication has been disabled")


@router.post(
    "/2fa/verify",
    response_model=TokenResponse,
    summary="Complete 2FA login with TOTP code",
)
async def verify_2fa(
    data: Verify2FARequest,
    request: Request,
    response: Response,
    deps: Annotated[AuthDeps, Depends()],
) -> TokenResponse:
    """
    Step 2 of a 2FA login — submit the 6-digit TOTP code.
    Call this after POST /login returns a TwoFactorChallengeResponse.
    The `user_id` comes from that challenge response.
    """
    from app.modules.auth.two_factor_service import TwoFactorService

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent", "")
    service = TwoFactorService(deps.db, deps.redis)
    result = await service.complete_2fa_login(data.user_id, data.code, ip, user_agent)
    _set_refresh_cookie(response, result.refresh_token)
    return result


@router.post(
    "/2fa/backup",
    response_model=TokenResponse,
    summary="Complete 2FA login with a backup code",
)
async def use_backup_code(
    data: BackupCodeRequest,
    request: Request,
    response: Response,
    deps: Annotated[AuthDeps, Depends()],
) -> TokenResponse:
    """
    Step 2 alternative — use a one-time backup code instead of TOTP.
    Each backup code is single-use and invalidated after consumption.
    """
    from app.modules.auth.two_factor_service import TwoFactorService

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent", "")
    service = TwoFactorService(deps.db, deps.redis)
    result = await service.use_backup_code(data.user_id, data.code, ip, user_agent)
    _set_refresh_cookie(response, result.refresh_token)
    return result


# ── Session Management ─────────────────────────────────────────────────────

@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List all active sessions",
)
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    current_session_id: Annotated[UUID | None, Depends(get_current_session_id)],
    deps: Annotated[AuthDeps, Depends()],
) -> SessionListResponse:
    """
    Return all active (non-revoked, non-expired) sessions for the current user.
    The session that made this request is marked with `is_current: true`.
    """
    service = AuthService(deps.db, deps.redis)
    sessions, sid = await service.list_sessions(current_user.id, current_session_id)
    return SessionListResponse(
        sessions=[
            SessionResponse(
                id=s.id,
                ip_address=str(s.ip_address) if s.ip_address else None,
                user_agent=s.user_agent,
                device_type=s.device_type,
                last_active_at=s.last_active_at,
                created_at=s.created_at,
                is_current=(str(s.id) == str(sid)) if sid else False,
            )
            for s in sessions
        ]
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a specific session",
)
async def revoke_session(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    deps: Annotated[AuthDeps, Depends()],
) -> None:
    """
    Revoke a specific session by ID.
    Only the owner of the session may revoke it.
    """
    service = AuthService(deps.db, deps.redis)
    await service.revoke_session(current_user.id, session_id)


@router.delete(
    "/sessions",
    response_model=MessageResponse,
    summary="Revoke all sessions except current",
)
async def revoke_all_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    current_session_id: Annotated[UUID | None, Depends(get_current_session_id)],
    deps: Annotated[AuthDeps, Depends()],
) -> MessageResponse:
    """
    Revoke all active sessions for the current user, except the one making this request.
    Use this to sign out all other devices (e.g. after a suspected account compromise).
    """
    from app.core.exceptions import BadRequestException

    if not current_session_id:
        raise BadRequestException(
            "Cannot determine current session. "
            "Ensure you are using an up-to-date access token."
        )
    service = AuthService(deps.db, deps.redis)
    await service.revoke_all_other_sessions(current_user.id, current_session_id)
    return MessageResponse(message="All other sessions have been revoked")


# ── Password Change ────────────────────────────────────────────────────────

@router.post(
    "/password/change",
    response_model=MessageResponse,
    summary="Change password",
)
async def change_password(
    data: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    deps: Annotated[AuthDeps, Depends()],
) -> MessageResponse:
    """
    Change the current user's password.
    Requires the existing password for verification.
    Existing sessions remain active — revoke them separately if needed.
    """
    service = AuthService(deps.db, deps.redis)
    await service.change_password(current_user, data)
    return MessageResponse(message="Password changed successfully")
