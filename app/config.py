"""
Centralised application settings — loaded once, injected everywhere.
Uses pydantic-settings to read from environment / .env file.
All config is typed, validated at startup, and accessed via get_settings().
"""

from functools import lru_cache
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    APP_NAME: str = "SaaS Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production

    # ── Server ─────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ── Database ───────────────────────────────────────────────────────────
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host:5432/db
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_ECHO: bool = False

    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT / Auth ─────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Security ───────────────────────────────────────────────────────────
    ENCRYPTION_KEY: str = ""  # 32-byte Fernet key for sensitive field encryption
    MAX_LOGIN_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 30

    # ── CORS ───────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            import json
            return json.loads(v)
        return v

    # ── Storage ────────────────────────────────────────────────────────────
    STORAGE_PROVIDER: str = "s3"  # s3 | local
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_BUCKET_NAME: str = ""
    AWS_REGION: str = "us-east-1"
    LOCAL_STORAGE_PATH: str = "/tmp/uploads"

    # ── MinIO (call recordings — written by services/pipeline/call_recorder.py) ──
    # Mirrors the pipeline service's own env vars so presigned URLs are generated
    # against the same bucket/endpoint the recording was actually uploaded to.
    MINIO_ENDPOINT: str = "http://minio:9100"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "call-recordings"

    # ── Email (SMTP) ───────────────────────────────────────────────────────
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "noreply@example.com"
    SMTP_FROM_NAME: str = "SaaS Platform"
    SMTP_TLS: bool = False

    # ── Billing / Payment ──────────────────────────────────────────────────
    BILLING_PROVIDER: str = "stripe"  # stripe | razorpay | none

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # Subscription cache (seconds)
    SUBSCRIPTION_CACHE_TTL: int = 300

    # ── Frontend ───────────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:3000"

    # ── OAuth2 Social Login ────────────────────────────────────────────────
    # Google
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # GitHub
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # # Microsoft
    # MICROSOFT_CLIENT_ID: str = ""
    # MICROSOFT_CLIENT_SECRET: str = ""

    # Base URL used to build OAuth2 redirect URIs (e.g. https://api.example.com)
    OAUTH_REDIRECT_BASE_URL: str = "http://localhost:8000"

    # ── Qdrant / RAG ───────────────────────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""       # leave blank for local / single-node
    RAG_EMBED_MODEL: str = "BAAI/bge-small-en-v1.5"   # 384-dim, ~130 MB
    RAG_CHUNK_SIZE: int = 512      # approximate token budget per chunk
    RAG_CHUNK_OVERLAP: int = 50    # overlap between consecutive chunks
    RAG_SCORE_THRESHOLD: float = 0.6
    RAG_DEFAULT_TOP_K: int = 3

    # ── Pipeline service ───────────────────────────────────────────────────
    PIPELINE_SERVICE_URL: str = "http://localhost:7000"

    # ── Twilio PSTN ────────────────────────────────────────────────────────
    # Get these from https://console.twilio.com → Account Info
    TWILIO_ACCOUNT_SID: str = ""          # AC…
    TWILIO_AUTH_TOKEN: str = ""           # used for signature validation & REST API
    # Your publicly reachable hostname (no scheme, no trailing slash)
    # e.g. "api.example.com" or for local dev: use ngrok subdomain
    PUBLIC_HOST: str = "localhost:8000"
    PUBLIC_PROTOCOL: str = "https"        # http for local dev with ngrok http tunnels
    # Internal WS base URL the saas_platform passes to the pipeline service
    # when creating Twilio sessions so Twilio can reach the stream endpoint
    PIPELINE_WS_PUBLIC_URL: str = "ws://localhost:7000"  # override with public wss:// in prod

    # ── WebRTC / ICE ───────────────────────────────────────────────────────
    # ICE_SERVERS: comma-separated STUN/TURN URLs served to browser clients.
    # For production add a TURN entry:  turn:your-turn.server:3478
    ICE_SERVERS: str = "stun:stun.l.google.com:19302"

    # Optional TURN credentials (only needed when ICE_SERVERS contains TURN)
    TURN_SERVER_URL: str = ""      # e.g. turn:coturn.example.com:3478
    TURN_USERNAME: str = ""
    TURN_CREDENTIAL: str = ""

    @property
    def ice_server_list(self) -> list[dict]:
        """
        Return a JSON-serialisable ICE server list for the browser SDK.

        STUN entries are plain ``{"urls": "stun:..."}`` dicts.
        If ``TURN_SERVER_URL`` is set a TURN entry with credentials is appended.
        """
        servers = [
            {"urls": url.strip()}
            for url in self.ICE_SERVERS.split(",")
            if url.strip()
        ]
        if self.TURN_SERVER_URL:
            servers.append({
                "urls": self.TURN_SERVER_URL,
                "username": self.TURN_USERNAME,
                "credential": self.TURN_CREDENTIAL,
            })
        return servers

    # ── Helpers ────────────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]