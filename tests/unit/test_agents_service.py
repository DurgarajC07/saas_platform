"""
Unit tests for app.modules.agents.service — focused on the audit-remediation
fixes that previously had zero coverage:

  * CallLogService.write_call_log — tenant-binding check (cross-tenant
    call-log forgery fix) and credit/concurrency-slot wiring on call end.
  * AgentService.create_agent — ai.agents.max plan-limit enforcement.
  * _build_agent_config — the shared payload builder that fixed the
    WebRTC/Twilio session-creation schema mismatch.

All DB/Redis I/O is mocked — these test the service's own orchestration
logic, not the repository/ORM layer underneath it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.agents.schemas import CreateAgentRequest, WriteCallLogRequest
from app.modules.agents.service import AgentService, CallLogService, _build_agent_config


def _fake_agent(**overrides) -> SimpleNamespace:
    """A minimal stand-in for the Agent ORM model with every field
    _build_agent_config / write_call_log touch."""
    defaults = dict(
        id=uuid4(),
        org_id=uuid4(),
        created_by=uuid4(),
        name="Aria",
        slug="aria",
        agent_type="conversational",
        status="draft",
        llm_model="qwen2.5:3b",
        system_prompt="You are Aria.",
        temperature=0.7,
        max_tokens=512,
        language=None,
        tts_voice="af_heart",
        tts_speed=1.0,
        vad_threshold=0.5,
        min_speech_ms=250,
        silence_ms=700,
        allow_interruptions=True,
        noise_removal_level="rnnoise",
        qdrant_collection=None,
        rag_top_k=3,
        tools_json=None,
        welcome_message=None,
        max_call_duration_sec=300,
        record_calls=True,
        metadata_={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_call_log(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=uuid4(),
        agent_id=uuid4(),
        org_id=uuid4(),
        session_id=None,
        caller_id="+15551234567",
        direction="inbound",
        transport="webrtc",
        status="completed",
        started_at=None,
        ended_at=None,
        duration_sec=60,
        transcript=None,
        recording_url=None,
        cost_credits=1,
        stt_ms=None,
        llm_ttft_ms=None,
        tts_ttfb_ms=None,
        metadata_={},
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_call_log_service(redis=None) -> CallLogService:
    """Build a CallLogService with the DB session mocked and sub-collaborators
    replaced with mocks after construction (so __init__'s real repo/service
    wiring runs, but no real SQL/network happens)."""
    svc = CallLogService(MagicMock(), redis=redis)
    svc.agent_repo = MagicMock()
    svc.agent_repo.get_by_id_and_org = AsyncMock()
    svc.repo = MagicMock()
    svc.repo.create = AsyncMock()
    svc._audit = MagicMock()
    svc._audit.log = AsyncMock()
    return svc


# ── write_call_log — tenant-binding check ──────────────────────────────────────

class TestWriteCallLogTenantBinding:
    @pytest.mark.asyncio
    async def test_rejects_when_agent_does_not_belong_to_org(self):
        """
        The core regression test: a caller supplies an agent_id/org_id pair
        where the agent exists but belongs to a DIFFERENT org. Before the
        fix, write_call_log trusted the body unconditionally and would have
        written the row — corrupting that other org's call history/billing.
        """
        svc = _make_call_log_service()
        svc.agent_repo.get_by_id_and_org.return_value = None  # mismatch → not found

        body = WriteCallLogRequest(
            agent_id=uuid4(),
            org_id=uuid4(),
            status="completed",
            duration_sec=60,
        )

        with pytest.raises(NotFoundException):
            await svc.write_call_log(body)

        # Must check ownership BEFORE ever attempting to persist the row.
        svc.agent_repo.get_by_id_and_org.assert_called_once_with(body.agent_id, body.org_id)
        svc.repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_persists_when_agent_belongs_to_org(self):
        svc = _make_call_log_service()
        agent_id, org_id = uuid4(), uuid4()
        svc.agent_repo.get_by_id_and_org.return_value = _fake_agent(id=agent_id, org_id=org_id)
        svc.repo.create.return_value = _fake_call_log(agent_id=agent_id, org_id=org_id)

        body = WriteCallLogRequest(
            agent_id=agent_id, org_id=org_id, status="completed", duration_sec=90
        )
        result = await svc.write_call_log(body)

        svc.repo.create.assert_called_once()
        assert result.agent_id == agent_id
        assert result.org_id == org_id


# ── write_call_log — credit deduction + concurrency-slot release ──────────────

class TestWriteCallLogCreditWiring:
    @pytest.mark.asyncio
    async def test_terminal_status_releases_slot_and_deducts_credits(self, monkeypatch):
        redis = AsyncMock()
        svc = _make_call_log_service(redis=redis)
        agent_id, org_id = uuid4(), uuid4()
        svc.agent_repo.get_by_id_and_org.return_value = _fake_agent(id=agent_id, org_id=org_id)
        svc.repo.create.return_value = _fake_call_log(
            agent_id=agent_id, org_id=org_id, status="completed", duration_sec=120
        )

        released = AsyncMock()
        deducted = AsyncMock()
        usage_result = SimpleNamespace(used_minutes=1, allowed_minutes=60)

        class _FakeCreditService:
            def __init__(self, *a, **k):
                pass

            release_call_slot = released
            check_and_deduct = deducted

            async def get_usage(self, _org_id):
                return usage_result

        monkeypatch.setattr(
            "app.modules.agents.service.CallCreditService", _FakeCreditService
        )

        body = WriteCallLogRequest(
            agent_id=agent_id, org_id=org_id, status="completed", duration_sec=120
        )
        await svc.write_call_log(body)

        released.assert_called_once_with(org_id)
        deducted.assert_called_once_with(org_id, 120)

    @pytest.mark.asyncio
    async def test_connected_status_does_not_release_or_deduct(self, monkeypatch):
        """'connected' is a live, non-terminal status — the call hasn't
        ended, so no slot release / credit deduction should happen yet."""
        redis = AsyncMock()
        svc = _make_call_log_service(redis=redis)
        agent_id, org_id = uuid4(), uuid4()
        svc.agent_repo.get_by_id_and_org.return_value = _fake_agent(id=agent_id, org_id=org_id)
        svc.repo.create.return_value = _fake_call_log(
            agent_id=agent_id, org_id=org_id, status="connected", duration_sec=None
        )

        released = AsyncMock()
        monkeypatch.setattr(
            "app.modules.agents.service.CallCreditService",
            lambda *a, **k: SimpleNamespace(release_call_slot=released),
        )

        body = WriteCallLogRequest(agent_id=agent_id, org_id=org_id, status="connected")
        await svc.write_call_log(body)

        released.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_skips_credit_wiring_entirely(self):
        """CallLogService(db) with no redis (e.g. a caller that forgot to
        inject it) must not crash — it just skips the webhook/credit block,
        same as the pre-fix behaviour for everything except persistence."""
        svc = _make_call_log_service(redis=None)
        agent_id, org_id = uuid4(), uuid4()
        svc.agent_repo.get_by_id_and_org.return_value = _fake_agent(id=agent_id, org_id=org_id)
        svc.repo.create.return_value = _fake_call_log(
            agent_id=agent_id, org_id=org_id, status="completed", duration_sec=30
        )

        body = WriteCallLogRequest(
            agent_id=agent_id, org_id=org_id, status="completed", duration_sec=30
        )
        result = await svc.write_call_log(body)  # must not raise
        assert result.status == "completed"


# ── AgentService.create_agent — ai.agents.max enforcement ─────────────────────

class TestCreateAgentLimit:
    @pytest.mark.asyncio
    async def test_blocked_when_at_agent_limit(self, monkeypatch):
        from app.modules.features.schemas import FeatureCheckResult

        org_id = uuid4()
        redis = AsyncMock()
        svc = AgentService(MagicMock(), redis=redis)
        svc.repo = MagicMock()
        svc.repo.get_by_slug_and_org = AsyncMock(return_value=None)
        svc.repo.list_by_org = AsyncMock(return_value=([], 1))  # already has 1 agent
        svc.repo.create = AsyncMock()
        svc._audit = MagicMock()
        svc._audit.log = AsyncMock()

        fake_feature_svc = MagicMock()
        fake_feature_svc.check = AsyncMock(
            return_value=FeatureCheckResult(feature_key="ai.agents.max", enabled=True, limit=1)
        )
        monkeypatch.setattr(
            "app.modules.agents.service.FeatureService", lambda *a, **k: fake_feature_svc
        )

        creator = SimpleNamespace(id=uuid4())
        body = CreateAgentRequest(name="Second Agent", agent_type="conversational")

        with pytest.raises(ForbiddenException):
            await svc.create_agent(org_id, creator, body)
        svc.repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_when_under_limit(self, monkeypatch):
        from app.modules.features.schemas import FeatureCheckResult

        org_id = uuid4()
        redis = AsyncMock()
        svc = AgentService(MagicMock(), redis=redis)
        svc.repo = MagicMock()
        svc.repo.get_by_slug_and_org = AsyncMock(return_value=None)
        svc.repo.list_by_org = AsyncMock(return_value=([], 1))
        svc.repo.create = AsyncMock(return_value=_fake_agent(org_id=org_id))
        svc._audit = MagicMock()
        svc._audit.log = AsyncMock()

        fake_feature_svc = MagicMock()
        fake_feature_svc.check = AsyncMock(
            return_value=FeatureCheckResult(feature_key="ai.agents.max", enabled=True, limit=10)
        )
        monkeypatch.setattr(
            "app.modules.agents.service.FeatureService", lambda *a, **k: fake_feature_svc
        )

        creator = SimpleNamespace(id=uuid4())
        body = CreateAgentRequest(name="Second Agent", agent_type="conversational")
        await svc.create_agent(org_id, creator, body)  # must not raise
        svc.repo.create.assert_called_once()


# ── _build_agent_config — shared WebRTC/Twilio session payload builder ────────

class TestBuildAgentConfig:
    def test_includes_org_secrets_and_matches_pipeline_schema_fields(self):
        """
        Regression check for the bug where TwilioCallService sent a totally
        different (camelCase, flat) payload shape than webrtc_connect — this
        asserts the keys this function emits match what
        services/pipeline/schemas.py::AgentConfig expects (snake_case,
        nested under "agent_config").
        """
        agent = _fake_agent()
        secrets = {"ORDERS_DB_DSN": "postgresql://real@db/orders"}
        cfg = _build_agent_config(agent, secrets)

        expected_keys = {
            "agent_id", "organization_id", "name", "agent_type", "llm_model",
            "system_prompt", "temperature", "max_tokens", "tools_json",
            "org_secrets", "language", "tts_voice", "tts_speed",
            "vad_threshold", "min_speech_ms", "silence_ms",
            "qdrant_collection", "rag_top_k", "noise_removal_level",
            "allow_interruptions",
        }
        assert expected_keys == set(cfg.keys())
        assert cfg["org_secrets"] == secrets
        assert cfg["agent_id"] == str(agent.id)
        assert cfg["organization_id"] == str(agent.org_id)

    def test_nullable_numeric_fields_fall_back_to_defaults(self):
        """temperature/tts_speed/vad_threshold/etc. may be None on a
        freshly-created ORM instance before defaults are applied — must not
        crash with TypeError when building the payload."""
        agent = _fake_agent(
            temperature=None, tts_speed=None, vad_threshold=None,
            min_speech_ms=None, silence_ms=None, rag_top_k=None,
            noise_removal_level=None,
        )
        cfg = _build_agent_config(agent, {})
        assert cfg["temperature"] == 0.7
        assert cfg["tts_speed"] == 1.0
        assert cfg["vad_threshold"] == 0.5
        assert cfg["min_speech_ms"] == 250
        assert cfg["silence_ms"] == 700
        assert cfg["rag_top_k"] == 3
        assert cfg["noise_removal_level"] == "rnnoise"
