"""
Auth module constants.
"""

# Verification token expiry
VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

# Redis rate-limit for login attempts
LOGIN_RATE_LIMIT_ATTEMPTS: int = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 15 * 60  # 15 minutes

# Redis key prefixes
DENYLIST_PREFIX = "denylist:"         # denylist:{token}
LOGIN_RATE_PREFIX = "rate:login:"     # rate:login:{ip}
