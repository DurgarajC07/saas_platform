"""
Auth-module-specific exceptions.
"""

from app.core.exceptions import AppException, ForbiddenException, UnauthorizedException


class InvalidTokenException(UnauthorizedException):
    """Verification / password-reset token is invalid, expired, or already used."""

    code = "INVALID_TOKEN"
    message = "The token is invalid or has expired"


class AccountLockedException(ForbiddenException):
    """Account temporarily locked due to too many failed login attempts."""

    status_code = 423
    code = "ACCOUNT_LOCKED"
    message = "Account is temporarily locked due to too many failed login attempts"


class EmailNotVerifiedException(ForbiddenException):
    """User has not verified their email address yet."""

    code = "EMAIL_NOT_VERIFIED"
    message = "Please verify your email address before logging in"


class TwoFactorRequiredException(AppException):
    """
    Raised during login when 2FA is enabled.
    Returns HTTP 200 with a partial challenge token so the client
    can prompt for the OTP without revealing whether credentials were correct.
    """

    status_code = 200
    code = "TWO_FACTOR_REQUIRED"
    message = "Two-factor authentication is required to complete login"

    def __init__(self, user_id: str) -> None:
        super().__init__(self.message)
        self.user_id = user_id
