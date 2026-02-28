"""
Password hashing with Argon2id via argon2-cffi.

Argon2id is the recommended variant — resistant to both
side-channel and GPU-based attacks.

DO NOT import passlib or bcrypt in this project.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP-recommended parameters for interactive logins (2024)
_ph = PasswordHasher(
    time_cost=2,        # iterations
    memory_cost=65536,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Return an Argon2id hash of *password*."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Return True if *plain_password* matches *hashed_password*.
    Safe against timing attacks — argon2-cffi uses constant-time comparison.
    """
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """
    Return True if the hash was generated with outdated parameters.
    Call this after a successful verify and rehash transparently.
    """
    return _ph.check_needs_rehash(hashed_password)
