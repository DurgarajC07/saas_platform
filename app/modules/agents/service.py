"""
Agents module service layer.

AgentService
  • create_agent          — validate slug uniqueness, set defaults, persist
  • list_agents           — paginated org agent list
  • get_agent             — single agent with org ownership check
  • update_agent          — partial PATCH with conflict check on slug change
  • delete_agent          — soft-delete (active calls finish first in pipeline)
  • update_prompt         — convenience endpoint: update system_prompt only
  • update_tools          — replace tools_json array
  • assign_phone_number   — attach an E.164 number to an agent
  • list_phone_numbers    — list agent's phone numbers
  • test_call             — generate a one-time WebSocket URL for test

CallLogService
  • write_call_log        — persist a call record from the pipeline service
  • get_call              — retrieve single call (org-scoped)
  • list_calls            — paginated call history for an agent
  • get_analytics         — aggregate latency + volume stats
  • get_recording_url     — presigned placeholder (MinIO integration inline)
"""

from __future__ import annotations

import math
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from twilio.request_validator import RequestValidator as _TwilioRequestValidator
    from twilio.rest import Client as _TwilioClient
    _TWILIO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TWILIO_AVAILABLE = False

from app.config import get_settings
from app.core.exceptions import ConflictException, NotFoundException
from app.modules.audit.service import AuditService
from app.modules.agents.models import Agent, AgentPhoneNumber, CallLog
from app.modules.agents.repository import (
    AgentPhoneNumberRepository,
    AgentRepository,
    CallLogRepository,
)
from app.modules.agents.schemas import (
    AgentAnalyticsResponse,
    AgentListResponse,
    AgentPhoneNumberResponse,
    AgentResponse,
    AssignPhoneNumberRequest,
    CallLogListResponse,
    CallLogResponse,
    CreateAgentRequest,
    LatencyStats,
    OutboundCallRequest,
    OutboundCallResponse,
    RecordingUrlResponse,
    TestCallResponse,
    UpdateAgentRequest,
    UpdatePromptRequest,
    UpdateToolsRequest,
    WebRTCConnectResponse,
    WebRTCOfferRequest,
    WriteCallLogRequest,
)
from app.modules.auth.models import User
from app.shared.base_schemas import PaginationMeta

logger = structlog.get_logger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Convert an agent name to a slug: lowercase, alphanum + hyphens."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "agent"


def _latency_stats(
    avg: float | None,
    p50: float | None,
    p95: float | None,
    min_: int | None,
    max_: int | None,
) -> LatencyStats:
    return LatencyStats(
        avg_ms=round(avg, 1) if avg is not None else None,
        p50_ms=round(p50, 1) if p50 is not None else None,
        p95_ms=round(p95, 1) if p95 is not None else None,
        min_ms=float(min_) if min_ is not None else None,
        max_ms=float(max_) if max_ is not None else None,
    )


# ═══════════════════════════════════════════════════════════════════════════
# AgentService
# ═══════════════════════════════════════════════════════════════════════════


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AgentRepository(session)
        self.phone_repo = AgentPhoneNumberRepository(session)
        self._audit = AuditService(session)

    # ── Create ─────────────────────────────────────────────────────────────

    async def create_agent(
        self,
        org_id: UUID,
        creator: User,
        data: CreateAgentRequest,
    ) -> AgentResponse:
        slug = data.slug or _slugify(data.name)

        # Ensure slug is unique within the org
        existing = await self.repo.get_by_slug_and_org(slug, org_id)
        if existing:
            raise ConflictException(
                f"An agent with slug '{slug}' already exists in this organisation"
            )

        agent = await self.repo.create(
            org_id=org_id,
            created_by=creator.id,
            name=data.name,
            slug=slug,
            agent_type=data.agent_type,
            status=data.status,
            llm_model=data.llm_model,
            system_prompt=data.system_prompt,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
            language=data.language,
            tts_voice=data.tts_voice,
            tts_speed=data.tts_speed,
            vad_threshold=data.vad_threshold,
            min_speech_ms=data.min_speech_ms,
            silence_ms=data.silence_ms,
            allow_interruptions=data.allow_interruptions,
            noise_removal_level=data.noise_removal_level,
            qdrant_collection=data.qdrant_collection,
            rag_top_k=data.rag_top_k,
            tools_json=data.tools_json,
            welcome_message=data.welcome_message,
            max_call_duration_sec=data.max_call_duration_sec,
            record_calls=data.record_calls,
            metadata_=data.metadata,
        )

        logger.info(
            "agent.created",
            agent_id=str(agent.id),
            org_id=str(org_id),
            slug=slug,
        )
        await self._audit.log(
            action="agent.created",
            resource_type="agent",
            resource_id=str(agent.id),
            org_id=org_id,
            actor_user_id=creator.id,
            new_values={"name": data.name, "slug": slug, "agent_type": str(data.agent_type)},
            description=f"Created agent '{data.name}' (slug={slug})",
        )
        return AgentResponse.model_validate(agent)

    # ── Read ───────────────────────────────────────────────────────────────

    async def list_agents(
        self,
        org_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        agent_type: str | None = None,
    ) -> AgentListResponse:
        limit = page_size
        offset = (page - 1) * page_size
        rows, total = await self.repo.list_by_org(
            org_id,
            status=status,
            agent_type=agent_type,
            limit=limit,
            offset=offset,
        )
        total_pages = math.ceil(total / page_size) if page_size else 1
        return AgentListResponse(
            agents=[AgentResponse.model_validate(r) for r in rows],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )

    async def get_agent(self, agent_id: UUID, org_id: UUID) -> AgentResponse:
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        return AgentResponse.model_validate(agent)

    # ── Update ─────────────────────────────────────────────────────────────

    async def update_agent(
        self,
        agent_id: UUID,
        org_id: UUID,
        data: UpdateAgentRequest,
        actor: User | None = None,
    ) -> AgentResponse:
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        patch: dict = {}
        for field in data.model_fields_set:
            value = getattr(data, field)
            if field == "metadata":
                patch["metadata_"] = value
            else:
                patch[field] = value

        # Slug conflict check
        if "slug" in patch:
            conflict = await self.repo.get_by_slug_and_org(patch["slug"], org_id)
            if conflict and conflict.id != agent_id:
                raise ConflictException(
                    f"An agent with slug '{patch['slug']}' already exists"
                )

        if not patch:
            return AgentResponse.model_validate(agent)

        updated = await self.repo.update(agent_id, **patch)
        logger.info("agent.updated", agent_id=str(agent_id), fields=list(patch.keys()))
        await self._audit.log(
            action="agent.updated",
            resource_type="agent",
            resource_id=str(agent_id),
            org_id=org_id,
            actor_user_id=actor.id if actor else None,
            new_values={"fields_changed": list(patch.keys())},
            description=f"Updated agent fields: {', '.join(patch.keys())}",
        )
        return AgentResponse.model_validate(updated)

    # ── Delete ─────────────────────────────────────────────────────────────

    async def delete_agent(
        self,
        agent_id: UUID,
        org_id: UUID,
        actor: User | None = None,
    ) -> None:
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        await self.repo.soft_delete(agent_id)
        logger.info("agent.deleted", agent_id=str(agent_id))
        await self._audit.log(
            action="agent.deleted",
            resource_type="agent",
            resource_id=str(agent_id),
            org_id=org_id,
            actor_user_id=actor.id if actor else None,
            old_values={"name": agent.name, "slug": agent.slug},
            description=f"Soft-deleted agent '{agent.name}' (id={agent_id})",
        )

    # ── Prompt / Tools shortcuts ───────────────────────────────────────────

    async def update_prompt(
        self,
        agent_id: UUID,
        org_id: UUID,
        data: UpdatePromptRequest,
    ) -> AgentResponse:
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        updated = await self.repo.update(agent_id, system_prompt=data.system_prompt)
        logger.info("agent.prompt_updated", agent_id=str(agent_id))
        return AgentResponse.model_validate(updated)

    async def update_tools(
        self,
        agent_id: UUID,
        org_id: UUID,
        data: UpdateToolsRequest,
        actor: User | None = None,
    ) -> AgentResponse:
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        updated = await self.repo.update(agent_id, tools_json=data.tools_json)
        logger.info(
            "agent.tools_updated",
            agent_id=str(agent_id),
            tool_count=len(data.tools_json),
        )
        await self._audit.log(
            action="agent.tools_updated",
            resource_type="agent",
            resource_id=str(agent_id),
            org_id=org_id,
            actor_user_id=actor.id if actor else None,
            new_values={"tool_count": len(data.tools_json)},
            description=f"Replaced tool definitions ({len(data.tools_json)} tools)",
        )
        return AgentResponse.model_validate(updated)

    # ── Phone numbers ──────────────────────────────────────────────────────

    async def assign_phone_number(
        self,
        agent_id: UUID,
        org_id: UUID,
        data: AssignPhoneNumberRequest,
    ) -> AgentPhoneNumberResponse:
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        existing = await self.phone_repo.get_by_number(data.phone_number)
        if existing:
            raise ConflictException(
                f"Phone number {data.phone_number} is already assigned"
            )

        pn = await self.phone_repo.create(
            agent_id=agent_id,
            phone_number=data.phone_number,
            provider=data.provider,
            is_active=data.is_active,
            created_at=datetime.now(UTC),
        )
        logger.info(
            "agent.phone_number_assigned",
            agent_id=str(agent_id),
            phone=data.phone_number,
        )
        return AgentPhoneNumberResponse.model_validate(pn)

    async def list_phone_numbers(
        self, agent_id: UUID, org_id: UUID
    ) -> list[AgentPhoneNumberResponse]:
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        rows = await self.phone_repo.list_by_agent(agent_id)
        return [AgentPhoneNumberResponse.model_validate(r) for r in rows]

    # ── Test call ──────────────────────────────────────────────────────────

    async def test_call(self, agent_id: UUID, org_id: UUID) -> TestCallResponse:
        """
        Generate a one-time, short-lived WebSocket URL the client can use for
        a test call.  The pipeline service consumes the token at connection time.

        In production this would issue a signed JWT; for now we produce a
        deterministic URL using a secrets token so the spec is met.
        """
        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        settings = get_settings()
        token = secrets.token_urlsafe(24)
        session_id = str(uuid4())

        # Construct pipeline WS URL from settings, falling back to localhost.
        pipeline_base = getattr(settings, "PIPELINE_WS_BASE_URL", "ws://localhost:8001")
        ws_url = f"{pipeline_base}/ws/{session_id}?agent_id={agent_id}&token={token}"

        logger.info("agent.test_call_issued", agent_id=str(agent_id), session=session_id)
        return TestCallResponse(ws_url=ws_url, session_id=session_id)

    # ── WebRTC connect ──────────────────────────────────────────────────────

    async def webrtc_connect(
        self,
        agent_id: UUID,
        org_id: UUID,
        offer: WebRTCOfferRequest,
    ) -> WebRTCConnectResponse:
        """
        Create a pipeline session then exchange SDP offer/answer for WebRTC.

        Steps
        -----
        1. Resolve the agent (org-scoped).
        2. POST ``/sessions`` to the pipeline service — allocates a session
           and returns a ``session_id`` together with the ``webrtc_url``.
        3. POST the SDP offer to ``webrtc_url`` — pipeline performs the
           aiortc ICE-gathering / DTLS handshake and returns the SDP answer.
        4. Return ``WebRTCConnectResponse`` so the browser can call
           ``RTCPeerConnection.setRemoteDescription(answer)``.
        """
        import httpx

        agent = await self.repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        settings = get_settings()
        pipeline_url: str = getattr(
            settings, "PIPELINE_SERVICE_URL", "http://localhost:7000"
        )

        agent_config = {
            "agent_id": str(agent.id),
            "organization_id": str(agent.org_id),
            "name": agent.name,
            "agent_type": agent.agent_type,
            "llm_model": agent.llm_model,
            "system_prompt": agent.system_prompt or "",
            "temperature": float(agent.temperature) if agent.temperature is not None else 0.7,
            "max_tokens": agent.max_tokens or 512,
            "tts_voice": agent.tts_voice,
            "tts_speed": float(agent.tts_speed) if agent.tts_speed is not None else 1.0,
            "vad_threshold": float(agent.vad_threshold) if agent.vad_threshold is not None else 0.5,
            "min_speech_ms": agent.min_speech_ms or 250,
            "silence_ms": agent.silence_ms or 700,
            "allow_interruptions": bool(agent.allow_interruptions),
            "qdrant_collection": agent.qdrant_collection,
            "rag_top_k": agent.rag_top_k or 3,
            "tools_json": agent.tools_json,
            "noise_removal_level": agent.noise_removal_level or "rnnoise",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r_session = await client.post(
                    f"{pipeline_url}/sessions",
                    json={
                        "agent_config": agent_config,
                        "call_id": None,
                        "metadata": {"transport": "webrtc"},
                    },
                )
                r_session.raise_for_status()
                session_data = r_session.json()
                session_id: str = session_data["session_id"]
                webrtc_url: str = session_data.get(
                    "webrtc_url",
                    f"{pipeline_url}/sessions/{session_id}/webrtc/offer",
                )

                r_offer = await client.post(
                    webrtc_url,
                    json={"sdp": offer.sdp, "type": offer.type},
                )
                r_offer.raise_for_status()
                answer = r_offer.json()
        except httpx.ConnectError as exc:
            raise ConflictException(
                f"Pipeline service unavailable at {pipeline_url}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail = f"Pipeline error {status}: {exc.response.text[:200]}"
            raise ConflictException(detail) from exc
        except httpx.TimeoutException as exc:
            raise ConflictException("Pipeline service timed out") from exc

        ice_servers: list[dict] = answer.get(
            "ice_servers",
            getattr(settings, "ice_server_list", [{"urls": "stun:stun.l.google.com:19302"}]),
        )

        logger.info(
            "agent.webrtc_connect",
            agent_id=str(agent_id),
            session_id=session_id,
        )
        return WebRTCConnectResponse(
            sdp=answer["sdp"],
            type=answer["type"],
            session_id=session_id,
            ice_servers=ice_servers,
        )


# ═══════════════════════════════════════════════════════════════════════════
# CallLogService
# ═══════════════════════════════════════════════════════════════════════════


class CallLogService:
    def __init__(self, session: AsyncSession, redis=None) -> None:
        self.session = session
        self.redis = redis
        self.repo = CallLogRepository(session)
        self.agent_repo = AgentRepository(session)
        self._audit = AuditService(session)

    # ── Write (called by pipeline after session ends) ──────────────────────

    async def write_call_log(self, data: WriteCallLogRequest) -> CallLogResponse:
        log = await self.repo.create(
            agent_id=data.agent_id,
            org_id=data.org_id,
            session_id=data.session_id,
            caller_id=data.caller_id,
            direction=data.direction,
            transport=data.transport,
            status=data.status,
            started_at=data.started_at,
            ended_at=data.ended_at,
            duration_sec=data.duration_sec,
            transcript=data.transcript,
            recording_url=data.recording_url,
            cost_credits=data.cost_credits,
            stt_ms=data.stt_ms,
            llm_ttft_ms=data.llm_ttft_ms,
            tts_ttfb_ms=data.tts_ttfb_ms,
            metadata_=data.metadata,
            created_at=datetime.now(UTC),
        )
        logger.info(
            "call_log.written",
            call_id=str(log.id),
            agent_id=str(data.agent_id),
            status=data.status,
            duration_sec=data.duration_sec,
        )
        await self._audit.log(
            action="agent.call.completed",
            resource_type="call",
            resource_id=str(log.id),
            org_id=data.org_id,
            actor_user_id=None,
            actor_type="system",
            new_values={
                "agent_id": str(data.agent_id),
                "status": data.status,
                "duration_sec": data.duration_sec,
                "direction": str(data.direction),
                "transport": str(data.transport),
            },
            description=(
                f"Call {data.direction} via {data.transport} — "
                f"{data.status}, {data.duration_sec or 0}s"
            ),
        )
        # ── Publish webhook events & SSE notifications ──────────────────────
        if self.redis is not None:
            from app.modules.agents.events import (
                publish_call_ended,
                publish_call_failed,
                publish_call_started,
            )
            status_str = str(data.status).lower() if data.status else ""
            if status_str == "connected":
                await publish_call_started(
                    self.session, self.redis,
                    org_id=data.org_id,
                    agent_id=data.agent_id,
                    call_id=log.id,
                    direction=str(data.direction),
                    transport=str(data.transport),
                )
            elif status_str == "completed":
                await publish_call_ended(
                    self.session, self.redis,
                    org_id=data.org_id,
                    agent_id=data.agent_id,
                    call_id=log.id,
                    duration_sec=data.duration_sec,
                    recording_url=data.recording_url,
                )
            elif status_str in ("failed", "no-answer"):
                await publish_call_failed(
                    self.session, self.redis,
                    org_id=data.org_id,
                    agent_id=data.agent_id,
                    call_id=log.id,
                    reason=status_str,
                )
        return CallLogResponse.model_validate(log)

    # ── Read ───────────────────────────────────────────────────────────────

    async def get_call(self, call_id: UUID, org_id: UUID) -> CallLogResponse:
        log = await self.repo.get_by_id_and_org(call_id, org_id)
        if not log:
            raise NotFoundException(f"Call {call_id} not found")
        return CallLogResponse.model_validate(log)

    async def list_calls(
        self,
        agent_id: UUID,
        org_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> CallLogListResponse:
        # Verify agent belongs to org
        agent = await self.agent_repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        limit = page_size
        offset = (page - 1) * page_size
        rows, total = await self.repo.list_by_agent(
            agent_id, org_id, status=status, limit=limit, offset=offset
        )
        total_pages = math.ceil(total / page_size) if page_size else 1
        return CallLogListResponse(
            calls=[CallLogResponse.model_validate(r) for r in rows],
            pagination=PaginationMeta(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_previous=page > 1,
            ),
        )

    # ── Analytics ──────────────────────────────────────────────────────────

    async def get_analytics(
        self,
        agent_id: UUID,
        org_id: UUID,
        period_days: int = 30,
    ) -> AgentAnalyticsResponse:
        agent = await self.agent_repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")

        since = datetime.now(UTC) - timedelta(days=period_days)
        stats = await self.repo.get_analytics(agent_id, org_id, since)

        total = stats["total"] or 0
        completed = stats["completed"] or 0
        failed = stats["failed"] or 0
        success_rate = round(completed / total * 100, 1) if total > 0 else None

        return AgentAnalyticsResponse(
            agent_id=agent_id,
            period_days=period_days,
            total_calls=total,
            completed_calls=completed,
            failed_calls=failed,
            success_rate_pct=success_rate,
            avg_duration_sec=round(stats["avg_duration"], 1)
            if stats.get("avg_duration") is not None
            else None,
            total_duration_sec=int(stats["total_duration"] or 0),
            stt_latency=_latency_stats(
                stats.get("avg_stt"),
                stats.get("p50_stt"),
                stats.get("p95_stt"),
                stats.get("min_stt"),
                stats.get("max_stt"),
            ),
            llm_latency=_latency_stats(
                stats.get("avg_llm"),
                stats.get("p50_llm"),
                stats.get("p95_llm"),
                stats.get("min_llm"),
                stats.get("max_llm"),
            ),
            tts_latency=_latency_stats(
                stats.get("avg_tts"),
                stats.get("p50_tts"),
                stats.get("p95_tts"),
                stats.get("min_tts"),
                stats.get("max_tts"),
            ),
            inbound_calls=stats["inbound"] or 0,
            outbound_calls=stats["outbound"] or 0,
        )

    # ── Recording URL ──────────────────────────────────────────────────────

    async def get_recording_url(
        self, call_id: UUID, org_id: UUID
    ) -> RecordingUrlResponse:
        """
        Return a presigned URL for the call recording stored in MinIO/S3.

        Full MinIO SDK presign integration would live here. For now we return
        the stored URL with a 1-hour expiry so the contract is met.
        """
        log = await self.repo.get_by_id_and_org(call_id, org_id)
        if not log:
            raise NotFoundException(f"Call {call_id} not found")
        if not log.recording_url:
            raise NotFoundException(f"No recording available for call {call_id}")

        expires_at = datetime.now(UTC) + timedelta(hours=1)
        # TODO: generate MinIO presigned URL using minio-py when integrated
        return RecordingUrlResponse(url=log.recording_url, expires_at=expires_at)


# ── Twilio PSTN service ───────────────────────────────────────────────────────

class TwilioCallService:
    """
    Handles Twilio PSTN inbound / outbound call orchestration.

    Responsibilities:
    * Validate Twilio request signatures (inbound webhooks).
    * Look up the agent assigned to a phone number.
    * Create a pipeline session via the internal pipeline HTTP API.
    * Generate TwiML ``<Connect><Stream>`` responses.
    * Initiate outbound calls via the Twilio REST API.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self._phone_repo = AgentPhoneNumberRepository(session)
        self._agent_repo = AgentRepository(session)
        self._audit = AuditService(session)
        self.log = logger.bind(service="TwilioCallService")

    # ── signature validation ──────────────────────────────────────────────

    def validate_signature(
        self,
        url: str,
        params: dict,
        signature: str,
    ) -> bool:
        """Return True when the X-Twilio-Signature header is valid."""
        if not _TWILIO_AVAILABLE:
            raise RuntimeError("twilio package not installed")
        validator = _TwilioRequestValidator(self.settings.TWILIO_AUTH_TOKEN)
        return validator.validate(url, params, signature)

    # ── TwiML helpers ─────────────────────────────────────────────────────

    def _twiml_stream(self, session_id: str) -> str:
        """
        Return TwiML that connects Twilio to the pipeline Media Streams WS.

        Example output::

            <?xml version="1.0" encoding="UTF-8"?>
            <Response>
              <Connect>
                <Stream url="wss://pipeline.example.com/sessions/{id}/twilio_stream"/>
              </Connect>
            </Response>
        """
        ws_url = (
            self.settings.PIPELINE_WS_PUBLIC_URL.rstrip("/")
            + f"/sessions/{session_id}/twilio_stream"
        )
        root = ET.Element("Response")
        connect = ET.SubElement(root, "Connect")
        ET.SubElement(connect, "Stream", url=ws_url)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )

    def _twiml_connect_callback(self, session_id: str) -> str:
        """
        TwiML URL returned to Twilio for outbound calls.

        Twilio calls this URL when the callee answers; it responds with
        the ``<Connect><Stream>`` TwiML that wires the call into the pipeline.
        """
        base = (
            f"{self.settings.PUBLIC_PROTOCOL}://{self.settings.PUBLIC_HOST}"
        )
        return f"{base}/api/v1/webhooks/twilio/connect/{session_id}"

    # ── inbound call handling ─────────────────────────────────────────────

    async def handle_inbound(
        self,
        phone_number: str,
        call_sid: str,
        from_number: str,
        org_id: UUID,
    ) -> str:
        """
        Process an inbound Twilio call webhook and return TwiML XML.

        Steps:
        1. Look up the ``AgentPhoneNumber`` record for this Twilio number.
        2. Retrieve the associated ``Agent``.
        3. POST a new pipeline session using the agent config.
        4. Return ``<Connect><Stream>`` TwiML pointing at the pipeline WS.
        """
        phone_rec = await self._phone_repo.get_by_number(phone_number)
        if not phone_rec:
            self.log.warning("inbound_call.unknown_number", number=phone_number)
            # Return a polite goodbye so callers aren't left in silence
            root = ET.Element("Response")
            ET.SubElement(root, "Say").text = "This number is not configured."
            ET.SubElement(root, "Hangup")
            return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
                root, encoding="unicode"
            )

        agent = await self._agent_repo.get_by_id_and_org(phone_rec.agent_id, org_id)
        if not agent or not agent.is_active:
            root = ET.Element("Response")
            ET.SubElement(root, "Hangup")
            return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
                root, encoding="unicode"
            )

        session_id = await self._create_pipeline_session(agent, call_sid, from_number)

        await self._audit.log(
            action="twilio.inbound_call",
            resource_type="agent",
            resource_id=str(agent.id),
            org_id=org_id,
            metadata={"call_sid": call_sid, "from": from_number, "session_id": session_id},
        )

        self.log.info(
            "inbound_call.session_created",
            session_id=session_id,
            agent_id=str(agent.id),
        )
        return self._twiml_stream(session_id)

    # ── outbound call ─────────────────────────────────────────────────────

    async def start_outbound_call(
        self,
        agent_id: UUID,
        org_id: UUID,
        data: OutboundCallRequest,
        actor_id: UUID,
    ) -> OutboundCallResponse:
        """
        Initiate an outbound PSTN call via the Twilio REST API.

        Steps:
        1. Validate agent ownership + active status.
        2. Resolve caller-ID (override or first assigned number).
        3. POST a pipeline session.
        4. Build the TwiML callback URL (``/webhooks/twilio/connect/{session_id}``).
        5. Call ``twilio.rest.Client.calls.create()``.
        """
        if not _TWILIO_AVAILABLE:
            raise RuntimeError("twilio package not installed")

        agent = await self._agent_repo.get_by_id_and_org(agent_id, org_id)
        if not agent:
            raise NotFoundException(f"Agent {agent_id} not found")
        if not agent.is_active:
            raise ConflictException("Agent is not active")

        # Resolve caller-ID
        from_number = data.from_number
        if not from_number:
            numbers = await self._phone_repo.list_by_agent(agent_id)
            if not numbers:
                raise ConflictException("Agent has no assigned phone numbers")
            from_number = numbers[0].phone_number

        # Create pipeline session before dialling so the WS endpoint exists
        # before Twilio connects to it.
        session_id = await self._create_pipeline_session(
            agent,
            call_sid="pending",
            from_number=data.to_number,
            metadata={"direction": "outbound", **data.metadata},
        )

        connect_url = self._twiml_connect_callback(session_id)

        client = _TwilioClient(
            self.settings.TWILIO_ACCOUNT_SID,
            self.settings.TWILIO_AUTH_TOKEN,
        )
        call = client.calls.create(
            to=data.to_number,
            from_=from_number,
            url=connect_url,
        )

        await self._audit.log(
            action="twilio.outbound_call",
            resource_type="agent",
            resource_id=str(agent.id),
            org_id=org_id,
            actor_id=actor_id,
            metadata={"call_sid": call.sid, "to": data.to_number, "session_id": session_id},
        )

        self.log.info(
            "outbound_call.initiated",
            call_sid=call.sid,
            session_id=session_id,
            to=data.to_number,
        )
        return OutboundCallResponse(
            call_sid=call.sid,
            session_id=session_id,
            from_number=from_number,
            status=call.status,
        )

    # ── internal helpers ──────────────────────────────────────────────────

    async def _create_pipeline_session(
        self,
        agent: Agent,
        call_sid: str,
        from_number: str,
        metadata: dict | None = None,
    ) -> str:
        """POST /sessions to the pipeline service and return the session_id."""
        payload: dict = {
            "agentId": str(agent.id),
            "systemPrompt": agent.system_prompt or "",
            "voiceId": agent.voice_id or "alloy",
            "language": agent.language or "en",
            "transport": "twilio",
            "metadata": {
                "callSid": call_sid,
                "callerNumber": from_number,
                **(metadata or {}),
            },
        }
        if agent.tools_json:
            payload["tools"] = agent.tools_json

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.settings.PIPELINE_SERVICE_URL.rstrip("/") + "/sessions",
                json=payload,
            )
            resp.raise_for_status()

        return resp.json()["session_id"]
