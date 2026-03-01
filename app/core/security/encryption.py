"""
Symmetric field-level encryption with Fernet (AES-128-CBC + HMAC-SHA256).

Used to encrypt PII columns (phone numbers, API keys, etc.) at rest.
The ENCRYPTION_KEY must be a valid 32-byte URL-safe base64 Fernet key.

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    key = get_settings().ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> str:
    """Return a URL-safe encrypted ciphertext string."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a ciphertext produced by :func:`encrypt`.
    Raises cryptography.fernet.InvalidToken if the token is invalid or tampered.
    """
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def safe_decrypt(ciphertext: str, default: str = "") -> str:
    """Decrypt silently — return *default* if the token is invalid."""
    try:
        return decrypt(ciphertext)
    except (InvalidToken, Exception):
        return default
