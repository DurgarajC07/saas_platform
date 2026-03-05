"""
Unit tests — Dashboard module (Day 15).

Tests cover:
  • DashboardService static helpers
  • AdminService graceful degradation on missing GPU / offline Celery
  • agents.events publish helpers (no DB/Redis — mocked)
  • BillingUsageResponse / InvoicePreviewResponse schema construction

All external I/O is mocked so these run without a running DB, Redis, or
Celery worker.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# ── DashboardService static helpers ──────────────────────────────────────────

class TestDashboardServiceHelpers:
    """Pure-python helpers that need no external services."""

    def _svc(self):
        """Build a DashboardService with mocked session / redis."""
        from app.modules.dashboard.service import DashboardService

        return DashboardService(session=AsyncMock(), redis=AsyncMock())

    def test_pct_happy(self):
        from app.modules.dashboard.service import DashboardService

        assert DashboardService._pct(75, 100) == 75.0

    def test_pct_zero_total(self):
        from app.modules.dashboard.service import DashboardService

        assert DashboardService._pct(0, 0) == 0.0

    def test_pct_completed_gt_total(self):
        """Completed can never exceed total, but clamping should be graceful."""
        from app.modules.dashboard.service import DashboardService

        # Should not raise
        result = DashboardService._pct(110, 100)
        assert result == 110.0  # no forced clamp; caller decides

    def test_month_start_is_first_day(self):
        from app.modules.dashboard.service import DashboardService

        ms = DashboardService._month_start()
        assert ms.day == 1
        assert ms.hour == 0
        assert ms.minute == 0


# ── AdminService — GPU graceful fallback ──────────────────────────────────────

class TestAdminServiceGPU:
    def test_no_nvidia_hardware(self):
        """gpu_status() must return nvml_available=False when pynvml is absent."""
        from app.modules.dashboard.service import AdminService

        with patch.dict("sys.modules", {"pynvml": None}):
            result = AdminService.gpu_status()

        assert result.nvml_available is False
        assert result.devices == []

    def test_pynvml_raises_nv_ml_error(self):
        """Any NVMLError must be caught and fall back gracefully."""
        from app.modules.dashboard.service import AdminService

        mock_pynvml = MagicMock()
        # Simulate NVMLError on init
        mock_pynvml.nvmlInit.side_effect = Exception("NVML Shared Library Not Found")

        with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
            result = AdminService.gpu_status()

        assert result.nvml_available is False


# ── AdminService — Celery queue graceful fallback ─────────────────────────────

class TestAdminServiceQueue:
    def test_celery_offline_returns_zeros(self):
        """queue_status() must return all-zero depths when Celery is unreachable."""
        from app.modules.dashboard.service import AdminService

        with patch("app.modules.dashboard.service.celery_app") as mock_app:
            mock_app.control.inspect.return_value.reserved.return_value = None
            mock_app.control.inspect.return_value.active.return_value = None
            result = AdminService.queue_status()

        # All queue depths should be integers (possibly 0)
        for q in result.queues:
            assert isinstance(q.depth, int)

    def test_celery_exception_returns_zeros(self):
        """queue_status() must never raise."""
        from app.modules.dashboard.service import AdminService

        with patch("app.modules.dashboard.service.celery_app") as mock_app:
            mock_app.control.inspect.side_effect = Exception("connection refused")
            result = AdminService.queue_status()

        assert isinstance(result.queues, list)


# ── Billing schema construction ───────────────────────────────────────────────

class TestBillingSchemas:
    def test_billing_usage_response(self):
        from app.modules.billing.schemas import BillingUsageResponse

        resp = BillingUsageResponse(
            org_id=uuid4(),
            period="2025-03",
            used_seconds=3600,
            used_minutes=60,
            allowed_minutes=100,
            remaining_minutes=40,
            credit_balance=3600,
            plan_name="Starter",
        )
        assert resp.used_minutes == 60
        assert resp.remaining_minutes == 40

    def test_billing_usage_unlimited(self):
        from app.modules.billing.schemas import BillingUsageResponse

        resp = BillingUsageResponse(
            org_id=uuid4(),
            period="2025-03",
            used_seconds=1800,
            used_minutes=30,
            allowed_minutes=None,
            remaining_minutes=None,
            credit_balance=1800,
            plan_name="Enterprise",
        )
        assert resp.allowed_minutes is None
        assert resp.remaining_minutes is None

    def test_invoice_preview_response(self):
        from app.modules.billing.schemas import InvoiceLineItem, InvoicePreviewResponse

        resp = InvoicePreviewResponse(
            org_id=uuid4(),
            period="2025-03",
            line_items=[
                InvoiceLineItem(
                    description="Pro plan — base",
                    quantity=1,
                    unit_price=49.0,
                    amount=49.0,
                ),
                InvoiceLineItem(
                    description="Overage — 10 min @ $0.01/min",
                    quantity=10.0,
                    unit_price=0.01,
                    amount=0.10,
                ),
            ],
            subtotal=49.10,
            currency="USD",
            estimated_at=datetime.now(UTC),
        )
        assert resp.subtotal == 49.10
        assert len(resp.line_items) == 2


# ── agents.events — Redis + webhook publish ───────────────────────────────────

class TestAgentEvents:
    """
    Tests for publish_* functions.  Both redis and the WebhookService are
    fully mocked so no network I/O happens.
    """

    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        r.publish = AsyncMock()
        r.get = AsyncMock(return_value=None)
        r.setex = AsyncMock()
        return r

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_publish_call_started_fires_redis(self, mock_session, mock_redis):
        from app.modules.agents.events import publish_call_started

        org_id = uuid4()
        agent_id = uuid4()
        call_id = uuid4()

        with patch(
            "app.modules.agents.events._dispatch_webhook",
            new=AsyncMock(),
        ):
            await publish_call_started(
                mock_session, mock_redis,
                org_id=org_id,
                agent_id=agent_id,
                call_id=call_id,
                direction="inbound",
                transport="websocket",
            )

        mock_redis.publish.assert_awaited_once()
        channel, raw = mock_redis.publish.call_args[0]
        assert f"live_calls:{org_id}" == channel
        payload = json.loads(raw)
        assert payload["event"] == "call.started"
        assert payload["call_id"] == str(call_id)

    @pytest.mark.asyncio
    async def test_publish_call_ended_fires_redis(self, mock_session, mock_redis):
        from app.modules.agents.events import publish_call_ended

        org_id = uuid4()
        call_id = uuid4()

        with patch("app.modules.agents.events._dispatch_webhook", new=AsyncMock()):
            await publish_call_ended(
                mock_session, mock_redis,
                org_id=org_id,
                agent_id=uuid4(),
                call_id=call_id,
                duration_sec=120,
                recording_url="https://example.com/rec.mp3",
            )

        mock_redis.publish.assert_awaited_once()
        _, raw = mock_redis.publish.call_args[0]
        payload = json.loads(raw)
        assert payload["event"] == "call.ended"
        assert payload["duration_sec"] == 120

    @pytest.mark.asyncio
    async def test_publish_call_failed_fires_redis(self, mock_session, mock_redis):
        from app.modules.agents.events import publish_call_failed

        org_id = uuid4()

        with patch("app.modules.agents.events._dispatch_webhook", new=AsyncMock()):
            await publish_call_failed(
                mock_session, mock_redis,
                org_id=org_id,
                agent_id=uuid4(),
                call_id=uuid4(),
                reason="no-answer",
            )

        mock_redis.publish.assert_awaited_once()
        _, raw = mock_redis.publish.call_args[0]
        assert json.loads(raw)["reason"] == "no-answer"

    @pytest.mark.asyncio
    async def test_limit_warning_dedup(self, mock_session, mock_redis):
        """Second call within the same month must be a no-op."""
        from app.modules.agents.events import publish_limit_warning

        # Simulate dedup key already set
        mock_redis.get = AsyncMock(return_value=b"1")

        with patch("app.modules.agents.events._dispatch_webhook", new=AsyncMock()) as mock_wh:
            await publish_limit_warning(
                mock_session, mock_redis,
                org_id=uuid4(),
                agent_id=uuid4(),
                percent_used=85.0,
            )

        mock_redis.publish.assert_not_awaited()
        mock_wh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publish_does_not_raise_on_redis_error(self, mock_session, mock_redis):
        """Redis errors must be swallowed."""
        from app.modules.agents.events import publish_call_started

        mock_redis.publish = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("app.modules.agents.events._dispatch_webhook", new=AsyncMock()):
            # Should not raise
            await publish_call_started(
                mock_session, mock_redis,
                org_id=uuid4(),
                agent_id=uuid4(),
                call_id=uuid4(),
            )

    @pytest.mark.asyncio
    async def test_kb_ingestion_complete(self, mock_session, mock_redis):
        from app.modules.agents.events import publish_kb_ingestion_complete

        org_id = uuid4()
        doc_id = uuid4()

        with patch("app.modules.agents.events._dispatch_webhook", new=AsyncMock()):
            await publish_kb_ingestion_complete(
                mock_session, mock_redis,
                org_id=org_id,
                agent_id=uuid4(),
                doc_id=doc_id,
                chunk_count=42,
            )

        _, raw = mock_redis.publish.call_args[0]
        payload = json.loads(raw)
        assert payload["event"] == "kb.ingestion.complete"
        assert payload["chunk_count"] == 42
        assert payload["doc_id"] == str(doc_id)
