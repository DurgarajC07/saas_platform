"""
Cryptographically-secure random token helpers.

Used for email verification codes, password-reset tokens, and
API key generation - anything that needs an opaque, hard-to-guess value.
"""

import secrets
import string


def generate_token(length: int = 64) -> str:
    """Return a URL-safe random token of *length* bytes."""
    return secrets.token_urlsafe(length)


def generate_otp(length: int = 6) -> str:
    """Return a zero-padded numeric OTP of *length* digits."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_api_key(prefix: str = "sk") -> str:
    """Return an API key in the style ``sk_<random>``."""
    return f"{prefix}_{secrets.token_urlsafe(36)}"
