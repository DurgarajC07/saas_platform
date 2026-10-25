"""
End-to-end tests for TwilioCallService.handle_inbound / start_outbound_call.

These are the highest-value tests flagged as missing by the audit: a test
that actually *drives* these two methods (not just their collaborators in
isolation) would have caught, immediately and automatically:

  * the `agent.is_active` / `agent.voice_id` AttributeErrors (neither field
    exists on the Agent model — real fields are `status` / `tts_voice`),
  * the `_create_pipeline_session` payload-shape mismatch (it was sending a
    flat camelCase body the pipeline's POST /sessions never accepted, so
    every real Twilio call failed one step after passing the AttributeError
    checks),
  * the `AuditService.log()` kwarg mismatches (`metadata=`/`actor_id=`
    instead of `new_values=`/`actor_user_id=`).

All DB/HTTP/Twilio I/O is mocked; this exercises TwilioCallService's own
orchestration logic end to end.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.modules.agents.schemas import OutboundCallRequest
from app.modules.agents.service import TwilioCallService


def _fake_agent(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=uuid4(),
        org_id=uuid4(),
        name="Aria",
        status="active",
        agent_type="conversational",
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
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_phone_record(agent_id, phone_number="+15551234567") -> SimpleNamespace:
    return SimpleNamespace(agent_id=agent_id, phone_number=phone_number)


class _FakeAsyncHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeAsyncHTTPClient:
    """Stands in for httpx.AsyncClient — records the exact payload POSTed."""

    last_posted_json: dict | None = None  # class-level, read by assertions

    def __init__(self, *a, **k) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kwargs):
        _FakeAsyncHTTPClient.last_posted_json = json
        return _FakeAsyncHTTPResponse({"session_id": "sess-123"})


def _make_twilio_service(redis=None, httpx_client_cls=None, org_secrets=None):
    svc = TwilioCallService(MagicMock(), redis=redis)
    svc._phone_repo = MagicMock()
    svc._agent_repo = MagicMock()
    svc._audit = MagicMock()
    svc._audit.log = AsyncMock()
    svc.settings = SimpleNamespace(
        PIPELINE_WS_PUBLIC_URL="ws://pipeline:7000",
        PIPELINE_SERVICE_URL="http://pipeline:7000",
        PUBLIC_PROTOCOL="https",
        PUBLIC_HOST="example.com",
        TWILIO_ACCOUNT_SID="ACxxxx",
        TWILIO_AUTH_TOKEN="authtoken",
    )
    return svc


@pytest.fixture(autouse=True)
def _patch_http_and_secrets(monkeypatch):
    """Applied to every test in this file: stub the pipeline HTTP call and
    the org-secrets lookup so _create_pipeline_session runs for real
    (building the actual agent_config payload) without touching a network
    or a real DB-backed OrganizationRepository."""
    _FakeAsyncHTTPClient.last_posted_json = None
    monkeypatch.setattr("app.modules.agents.service.httpx.AsyncClient", _FakeAsyncHTTPClient)

    class _FakeOrgSecretsService:
        def __init__(self, *a, **k):
            pass

        async def get_decrypted(self, org_id):
            return {}

    monkeypatch.setattr("app.modules.agents.service.OrgSecretsService", _FakeOrgSecretsService)
    yield


# ── handle_inbound ──────────────────────────────────────────────────────────────

class TestHandleInbound:
    @pytest.mark.asyncio
    async def test_unknown_number_hangs_up_politely(self):
        svc = _make_twilio_service()
        svc._phone_repo.get_by_number = AsyncMock(return_value=None)

        twiml = await svc.handle_inbound(
            phone_number="+15559999999", call_sid="CA1", from_number="+15550000001"
        )
        assert "<Hangup" in twiml
        assert "not configured" in twiml

    @pytest.mark.asyncio
    async def test_active_agent_creates_session_and_returns_stream_twiml(self):
        """
        The real regression test: an active agent (status == "active", NOT
        a nonexistent is_active attribute) must successfully reach
        _create_pipeline_session and get a <Connect><Stream> TwiML back.
        Before the fix this raised AttributeError on `agent.is_active`.
        """
        agent_id, org_id = uuid4(), uuid4()
        agent = _fake_agent(id=agent_id, org_id=org_id, status="active")

        svc = _make_twilio_service()
        svc._phone_repo.get_by_number = AsyncMock(
            return_value=_fake_phone_record(agent_id)
        )
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)  # org_id derivation
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=agent)

        twiml = await svc.handle_inbound(
            phone_number="+15551234567", call_sid="CA1", from_number="+15550000001"
        )

        assert "<Connect>" in twiml
        assert "<Stream" in twiml
        assert "sess-123" in twiml

        # The payload actually sent to the pipeline must be the nested
        # agent_config shape, not the old flat camelCase body.
        posted = _FakeAsyncHTTPClient.last_posted_json
        assert "agent_config" in posted
        assert posted["agent_config"]["agent_id"] == str(agent_id)
        assert posted["agent_config"]["tts_voice"] == "af_heart"
        assert "voiceId" not in posted  # old broken shape must be gone

        # Audit log must use the real AuditService.log() signature
        # (new_values=, not metadata=) or this would have raised TypeError.
        svc._audit.log.assert_called_once()
        _, kwargs = svc._audit.log.call_args
        assert kwargs["new_values"]["call_sid"] == "CA1"
        assert "metadata" not in kwargs

    @pytest.mark.asyncio
    async def test_paused_agent_hangs_up(self):
        """status == "paused" (not "active") must be rejected, same as a
        missing agent — this is the exact check that used to reference the
        nonexistent `agent.is_active` field."""
        agent_id, org_id = uuid4(), uuid4()
        agent = _fake_agent(id=agent_id, org_id=org_id, status="paused")

        svc = _make_twilio_service()
        svc._phone_repo.get_by_number = AsyncMock(return_value=_fake_phone_record(agent_id))
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=agent)

        twiml = await svc.handle_inbound(
            phone_number="+15551234567", call_sid="CA1", from_number="+15550000001"
        )
        assert "<Hangup" in twiml
        assert "<Connect>" not in twiml

    @pytest.mark.asyncio
    async def test_over_quota_org_gets_capacity_message_not_a_crash(self):
        agent_id, org_id = uuid4(), uuid4()
        agent = _fake_agent(id=agent_id, org_id=org_id, status="active")

        redis = AsyncMock()
        svc = _make_twilio_service(redis=redis)
        svc._phone_repo.get_by_number = AsyncMock(return_value=_fake_phone_record(agent_id))
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=agent)

        class _OverQuotaCredits:
            def __init__(self, *a, **k):
                pass

            async def get_usage(self, _org_id):
                return SimpleNamespace(used_minutes=60, allowed_minutes=60)

            async def acquire_call_slot(self, _org_id):
                pass

        import app.modules.agents.service as svc_mod
        orig = svc_mod.CallCreditService
        svc_mod.CallCreditService = _OverQuotaCredits
        try:
            twiml = await svc.handle_inbound(
                phone_number="+15551234567", call_sid="CA1", from_number="+15550000001"
            )
        finally:
            svc_mod.CallCreditService = orig

        assert "<Hangup" in twiml
        assert "capacity" in twiml


# ── start_outbound_call ─────────────────────────────────────────────────────────

class _FakeTwilioCall:
    sid = "CA_outbound_1"
    status = "queued"


class _FakeTwilioClient:
    def __init__(self, *a, **k) -> None:
        self.calls = SimpleNamespace(create=lambda **kw: _FakeTwilioCall())


class TestStartOutboundCall:
    @pytest.mark.asyncio
    async def test_active_agent_initiates_call(self, monkeypatch):
        """
        Regression test: this used to raise AttributeError on
        `agent.is_active`, and if that were patched naively (e.g. to always
        True) it would then fail on `agent.voice_id` inside
        _create_pipeline_session. This exercises the whole path for real.
        """
        monkeypatch.setattr("app.modules.agents.service._TwilioClient", _FakeTwilioClient)

        agent_id, org_id = uuid4(), uuid4()
        agent = _fake_agent(id=agent_id, org_id=org_id, status="active")

        svc = _make_twilio_service()
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=agent)
        svc._phone_repo.list_by_agent = AsyncMock(
            return_value=[_fake_phone_record(agent_id, "+15557654321")]
        )

        body = OutboundCallRequest(to_number="+15559998888", metadata={})
        result = await svc.start_outbound_call(
            agent_id=agent_id, org_id=org_id, data=body, actor_id=uuid4()
        )

        assert result.call_sid == "CA_outbound_1"
        assert result.session_id == "sess-123"
        assert result.from_number == "+15557654321"

        posted = _FakeAsyncHTTPClient.last_posted_json
        assert posted["agent_config"]["agent_id"] == str(agent_id)

        svc._audit.log.assert_called_once()
        _, kwargs = svc._audit.log.call_args
        assert kwargs["actor_user_id"] is not None
        assert "actor_id" not in kwargs
        assert kwargs["new_values"]["to"] == "+15559998888"

    @pytest.mark.asyncio
    async def test_inactive_agent_rejected(self, monkeypatch):
        monkeypatch.setattr("app.modules.agents.service._TwilioClient", _FakeTwilioClient)
        agent_id, org_id = uuid4(), uuid4()
        agent = _fake_agent(id=agent_id, org_id=org_id, status="draft")

        svc = _make_twilio_service()
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=agent)

        body = OutboundCallRequest(to_number="+15559998888", metadata={})
        with pytest.raises(ConflictException):
            await svc.start_outbound_call(
                agent_id=agent_id, org_id=org_id, data=body, actor_id=uuid4()
            )

    @pytest.mark.asyncio
    async def test_agent_not_found(self, monkeypatch):
        monkeypatch.setattr("app.modules.agents.service._TwilioClient", _FakeTwilioClient)
        svc = _make_twilio_service()
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=None)

        body = OutboundCallRequest(to_number="+15559998888", metadata={})
        with pytest.raises(NotFoundException):
            await svc.start_outbound_call(
                agent_id=uuid4(), org_id=uuid4(), data=body, actor_id=uuid4()
            )

    @pytest.mark.asyncio
    async def test_no_phone_number_assigned_rejected(self, monkeypatch):
        monkeypatch.setattr("app.modules.agents.service._TwilioClient", _FakeTwilioClient)
        agent_id, org_id = uuid4(), uuid4()
        agent = _fake_agent(id=agent_id, org_id=org_id, status="active")

        svc = _make_twilio_service()
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=agent)
        svc._phone_repo.list_by_agent = AsyncMock(return_value=[])

        body = OutboundCallRequest(to_number="+15559998888", metadata={})
        with pytest.raises(ConflictException):
            await svc.start_outbound_call(
                agent_id=agent_id, org_id=org_id, data=body, actor_id=uuid4()
            )

    @pytest.mark.asyncio
    async def test_over_quota_blocked_before_dialling(self, monkeypatch):
        """Must raise BEFORE ever calling the Twilio REST API — otherwise
        an over-quota org still gets billed for a real outbound call."""
        monkeypatch.setattr("app.modules.agents.service._TwilioClient", _FakeTwilioClient)
        agent_id, org_id = uuid4(), uuid4()
        agent = _fake_agent(id=agent_id, org_id=org_id, status="active")

        redis = AsyncMock()
        svc = _make_twilio_service(redis=redis)
        svc._agent_repo.get_by_id_and_org = AsyncMock(return_value=agent)
        svc._phone_repo.list_by_agent = AsyncMock(
            return_value=[_fake_phone_record(agent_id)]
        )

        class _OverQuotaCredits:
            def __init__(self, *a, **k):
                pass

            async def get_usage(self, _org_id):
                return SimpleNamespace(used_minutes=100, allowed_minutes=60)

        monkeypatch.setattr(
            "app.modules.agents.service.CallCreditService", _OverQuotaCredits
        )

        dial_called = False

        def _tracking_create(**kw):
            nonlocal dial_called
            dial_called = True
            return _FakeTwilioCall()

        class _TrackingTwilioClient:
            def __init__(self, *a, **k):
                self.calls = SimpleNamespace(create=_tracking_create)

        monkeypatch.setattr(
            "app.modules.agents.service._TwilioClient", _TrackingTwilioClient
        )

        body = OutboundCallRequest(to_number="+15559998888", metadata={})
        with pytest.raises(ForbiddenException):
            await svc.start_outbound_call(
                agent_id=agent_id, org_id=org_id, data=body, actor_id=uuid4()
            )
        assert dial_called is False
