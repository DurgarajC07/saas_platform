"""
Org-level encrypted secrets for AI tool-calling (SQL DSNs, API keys, auth headers).

Tool executors (``services/pipeline/processors/executors.py``) resolve
``{SECRET_NAME}`` tokens in a tool's URL/headers/query template from an
``org_secrets`` dict handed to the pipeline on session creation. This module
is where those secrets live on the platform side: encrypted at rest inside
``Organization.settings["ai_secrets"]`` (no new table/migration required),
decrypted only in-process right before being attached to a session payload.

The pipeline service never sees ciphertext or touches ``ENCRYPTION_KEY`` —
it only ever receives already-decrypted values for the duration of a call.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.core.security.encryption import decrypt, encrypt
from app.modules.tenancy.repository import OrganizationRepository

_SETTINGS_KEY = "ai_secrets"


class OrgSecretsService:
    """CRUD + decrypt for an organisation's tool-executor secrets."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._org_repo = OrganizationRepository(session)

    # ── Write ────────────────────────────────────────────────────────────────

    async def set_secret(self, org_id: UUID, key: str, value: str) -> None:
        """Encrypt *value* and store it under *key* for the org."""
        if not key or not key.replace("_", "").isalnum() or not key.isupper():
            raise ValidationException(
                "Secret key must be UPPER_SNAKE_CASE (it is substituted as a "
                "{TOKEN} in tool executor templates)"
            )
        org = await self._org_repo.get_by_id(org_id)
        if not org:
            raise NotFoundException(f"Organization {org_id} not found")

        settings = dict(org.settings or {})
        secrets = dict(settings.get(_SETTINGS_KEY, {}))
        secrets[key] = encrypt(value)
        settings[_SETTINGS_KEY] = secrets
        await self._org_repo.update(org_id, settings=settings)

    async def delete_secret(self, org_id: UUID, key: str) -> None:
        org = await self._org_repo.get_by_id(org_id)
        if not org:
            raise NotFoundException(f"Organization {org_id} not found")

        settings = dict(org.settings or {})
        secrets = dict(settings.get(_SETTINGS_KEY, {}))
        secrets.pop(key, None)
        settings[_SETTINGS_KEY] = secrets
        await self._org_repo.update(org_id, settings=settings)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_keys(self, org_id: UUID) -> list[str]:
        """Return the configured secret *names* only — never the values."""
        org = await self._org_repo.get_by_id(org_id)
        if not org:
            raise NotFoundException(f"Organization {org_id} not found")
        return sorted((org.settings or {}).get(_SETTINGS_KEY, {}).keys())

    async def get_decrypted(self, org_id: UUID) -> dict[str, str]:
        """
        Return the org's secrets decrypted, keyed by name.

        Never log or return this dict to a client — it is attached directly
        to the pipeline session payload as ``AgentConfig.org_secrets``.
        An entry that fails to decrypt (corrupted ciphertext / rotated
        ``ENCRYPTION_KEY``) is skipped rather than failing the whole call.
        """
        org = await self._org_repo.get_by_id(org_id)
        if not org:
            return {}
        encrypted: dict[str, str] = (org.settings or {}).get(_SETTINGS_KEY, {})
        out: dict[str, str] = {}
        for key, ciphertext in encrypted.items():
            try:
                out[key] = decrypt(ciphertext)
            except Exception:  # noqa: BLE001 — corrupted/undecryptable entry, skip it
                continue
        return out
