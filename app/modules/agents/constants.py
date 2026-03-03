"""Agents module constants."""

from __future__ import annotations

# Valid values for agent_type column
AGENT_TYPES: tuple[str, ...] = (
    "speaker_only",
    "conversational",
    "rag_bot",
    "db_bot",
)

# Valid values for status column
AGENT_STATUSES: tuple[str, ...] = (
    "draft",
    "active",
    "paused",
    "archived",
)

# Noise removal modes
NOISE_REMOVAL_LEVELS: tuple[str, ...] = (
    "none",
    "rnnoise",
    "deepfilternet",
)

# Phone providers
PHONE_PROVIDERS: tuple[str, ...] = (
    "twilio",
    "vonage",
    "own",
)

# Call directions
CALL_DIRECTIONS: tuple[str, ...] = ("inbound", "outbound")

# Call transports
CALL_TRANSPORTS: tuple[str, ...] = ("webrtc", "websocket", "twilio")

# Call statuses
CALL_STATUSES: tuple[str, ...] = ("connected", "completed", "failed", "no-answer")

# Default analytics window (days)
DEFAULT_ANALYTICS_DAYS: int = 30

# Test-call WS token TTL
TEST_CALL_TTL_SECONDS: int = 300
