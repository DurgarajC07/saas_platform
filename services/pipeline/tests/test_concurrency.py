"""
Unit tests for Day 8 deliverables — concurrency gate and pipeline metrics.

Coverage
--------
TestPipelineMetrics          — accumulation, rolling window, p95, snapshot shape
TestBusyResponse             — _send_busy_response sends correct JSON + WS close
TestSessionManagerConcurrency — MAX_CONCURRENT_CALLS constant and gate logic
TestMetricsEndpoint          — GET /metrics HTTP response shape
TestMetricsSingleton         — get_metrics / init_metrics lifecycle

No real Whisper / Kokoro / Ollama services are required.  All network calls
are mocked.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow direct imports from services/pipeline/
sys.path.insert(0, str(Path(__file__).parent.parent))

import metrics as metrics_module
from metrics import (
    MetricsSnapshot,
    PipelineMetrics,
    _gpu_utilization,
    get_metrics,
    init_metrics,
)


# ── TestPipelineMetrics ───────────────────────────────────────────────────────


class TestPipelineMetrics:
    """PipelineMetrics accumulates samples and returns correct averages / p95."""

    def setup_method(self) -> None:
        """Each test gets a fresh, isolated PipelineMetrics instance."""
        self.m = PipelineMetrics(max_concurrent_calls=3)

    def test_empty_snapshot_has_none_averages(self) -> None:
        snap = self.m.snapshot()
        assert snap.avg_vad_ms is None
        assert snap.avg_stt_ms is None
        assert snap.avg_llm_ttft_ms is None
        assert snap.avg_tts_ttfb_ms is None
        assert snap.avg_e2e_ms is None
        assert snap.p95_e2e_ms is None

    def test_single_vad_sample_becomes_average(self) -> None:
        self.m.record_vad_ms(2.5)
        assert self.m.snapshot().avg_vad_ms == 2.5

    def test_stt_average_over_multiple_samples(self) -> None:
        for ms in [100.0, 200.0, 300.0]:
            self.m.record_stt_ms(ms)
        assert self.m.snapshot().avg_stt_ms == 200.0

    def test_llm_ttft_single_sample(self) -> None:
        self.m.record_llm_ttft_ms(150.0)
        assert self.m.snapshot().avg_llm_ttft_ms == 150.0

    def test_tts_ttfb_average(self) -> None:
        self.m.record_tts_ttfb_ms(80.0)
        self.m.record_tts_ttfb_ms(120.0)
        assert self.m.snapshot().avg_tts_ttfb_ms == 100.0

    def test_e2e_average_and_counter(self) -> None:
        self.m.record_e2e_ms(500.0)
        self.m.record_e2e_ms(700.0)
        snap = self.m.snapshot()
        assert snap.avg_e2e_ms == 600.0
        assert snap.total_calls_served == 2

    def test_p95_single_element(self) -> None:
        self.m.record_e2e_ms(400.0)
        snap = self.m.snapshot()
        assert snap.p95_e2e_ms == 400.0

    def test_p95_over_twenty_samples(self) -> None:
        # 20 values 100, 200, ..., 2000 ms — p95 should be near the high end
        for i in range(1, 21):
            self.m.record_e2e_ms(float(i * 100))
        snap = self.m.snapshot()
        assert snap.p95_e2e_ms is not None
        assert snap.p95_e2e_ms >= 1800.0  # top 5% of sorted 100-2000

    def test_rolling_window_caps_at_50(self) -> None:
        # Record 60 STT samples — only last 50 should count
        for i in range(60):
            self.m.record_stt_ms(float(i + 1))
        # Oldest 10 (1-10) are evicted; window is 11-60
        snap = self.m.snapshot()
        expected_avg = sum(range(11, 61)) / 50
        assert snap.avg_stt_ms == round(expected_avg, 1)

    def test_set_active_sessions(self) -> None:
        self.m.set_active_sessions(2)
        assert self.m.snapshot().sessions_active == 2

    def test_max_concurrent_calls_in_snapshot(self) -> None:
        snap = self.m.snapshot()
        assert snap.max_concurrent_calls == 3

    def test_uptime_increases(self) -> None:
        snap1 = self.m.snapshot()
        time.sleep(0.01)
        snap2 = self.m.snapshot()
        assert snap2.uptime_s >= snap1.uptime_s

    def test_to_dict_returns_dict(self) -> None:
        d = self.m.snapshot().to_dict()
        assert isinstance(d, dict)
        assert "avg_stt_ms" in d
        assert "sessions_active" in d
        assert "gpu_utilization_pct" in d

    def test_gpu_utilization_returns_int_or_none(self) -> None:
        result = _gpu_utilization()
        assert result is None or isinstance(result, int)


# ── TestMetricsSingleton ──────────────────────────────────────────────────────


class TestMetricsSingleton:
    """init_metrics / get_metrics lifecycle."""

    def setup_method(self) -> None:
        # Reset the module-level singleton before each test
        metrics_module._metrics = None

    def teardown_method(self) -> None:
        metrics_module._metrics = None

    def test_get_metrics_returns_none_before_init(self) -> None:
        assert get_metrics() is None

    def test_init_metrics_creates_singleton(self) -> None:
        m = init_metrics(max_concurrent_calls=3)
        assert isinstance(m, PipelineMetrics)
        assert get_metrics() is m

    def test_init_metrics_reinitialises_singleton(self) -> None:
        m1 = init_metrics(max_concurrent_calls=3)
        m2 = init_metrics(max_concurrent_calls=5)
        assert m1 is not m2
        assert get_metrics() is m2
        assert get_metrics().snapshot().max_concurrent_calls == 5

    def test_processors_safe_when_metrics_uninitialised(self) -> None:
        """get_metrics() returns None — processors must not raise."""
        assert get_metrics() is None
        # Simulate what a processor does:
        _m = get_metrics()
        if _m is not None:
            _m.record_stt_ms(100.0)
        # No exception = pass


# ── TestBusyResponse ──────────────────────────────────────────────────────────


class TestBusyResponse:
    """_send_busy_response must send the correct event and close the WebSocket."""

    async def test_sends_busy_json_event(self) -> None:
        from session_manager import _send_busy_response

        ws = MagicMock()
        ws.send_text = AsyncMock()
        ws.close = AsyncMock()

        await _send_busy_response(ws)

        ws.send_text.assert_called_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["event"] == "busy"
        assert "detail" in payload
        assert len(payload["detail"]) > 0

    async def test_closes_with_policy_violation_code(self) -> None:
        from session_manager import _send_busy_response

        ws = MagicMock()
        ws.send_text = AsyncMock()
        ws.close = AsyncMock()

        await _send_busy_response(ws)

        ws.close.assert_called_once_with(code=1008)

    async def test_does_not_raise_when_send_fails(self) -> None:
        """If the client already disconnected, send_text will raise — must swallow."""
        from session_manager import _send_busy_response

        ws = MagicMock()
        ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))
        ws.close = AsyncMock()

        await _send_busy_response(ws)  # must not propagate the exception

    async def test_does_not_raise_when_close_fails(self) -> None:
        from session_manager import _send_busy_response

        ws = MagicMock()
        ws.send_text = AsyncMock()
        ws.close = AsyncMock(side_effect=RuntimeError("already closed"))

        await _send_busy_response(ws)  # must not propagate


# ── TestSessionManagerConcurrency ────────────────────────────────────────────


class TestSessionManagerConcurrency:
    """SessionManager.MAX_CONCURRENT_CALLS is enforced in run_ws()."""

    def test_max_concurrent_calls_class_attribute_is_3(self) -> None:
        from session_manager import SessionManager
        assert SessionManager.MAX_CONCURRENT_CALLS == 3

    def test_max_concurrent_calls_is_int(self) -> None:
        from session_manager import SessionManager
        assert isinstance(SessionManager.MAX_CONCURRENT_CALLS, int)

    async def test_run_ws_calls_busy_response_when_at_capacity(self) -> None:
        """
        When active_running >= MAX_CONCURRENT_CALLS, run_ws must call
        _send_busy_response and return without building a pipeline.
        """
        from session_manager import SessionManager, _SessionState
        from schemas import SessionInfo

        sm = SessionManager()
        sm.MAX_CONCURRENT_CALLS = 1

        # Inject one fake "active" session into the registry
        fake_info = SessionInfo(
            session_id="fake-session",
            agent_id="a1",
            call_id="c1",
            status="active",
            ws_url="ws://x",
            created_at="2026-03-03T00:00:00Z",
        )
        fake_config = MagicMock()
        fake_state = _SessionState(info=fake_info, config=fake_config)
        fake_state.info.status = "active"
        sm._sessions["fake-session"] = fake_state

        # The new session that should be rejected
        new_info = SessionInfo(
            session_id="new-session",
            agent_id="a2",
            call_id="c2",
            status="idle",
            ws_url="ws://y",
            created_at="2026-03-03T00:00:00Z",
        )
        new_config = MagicMock()
        new_state = _SessionState(info=new_info, config=new_config)
        sm._sessions["new-session"] = new_state

        ws = MagicMock()
        ws.send_text = AsyncMock()
        ws.close = AsyncMock()

        with patch("session_manager._send_busy_response", new_callable=AsyncMock) as mock_busy:
            await sm.run_ws("new-session", ws)

        mock_busy.assert_called_once_with(ws)

    async def test_run_ws_proceeds_when_below_capacity(self) -> None:
        """When there are no active sessions, run_ws should proceed past gate."""
        from session_manager import SessionManager, _SessionState
        from schemas import SessionInfo

        sm = SessionManager()

        info = SessionInfo(
            session_id="s1",
            agent_id="a1",
            call_id="c1",
            status="idle",
            ws_url="ws://x",
            created_at="2026-03-03T00:00:00Z",
        )
        config = MagicMock()
        state = _SessionState(info=info, config=config)
        sm._sessions["s1"] = state

        ws = MagicMock()
        ws.send_text = AsyncMock()
        ws.close = AsyncMock()

        # We expect it to proceed past the gate (and then fail building pipeline
        # because config is a MagicMock). Patch _send_busy_response to confirm
        # it is NOT called.
        with patch("session_manager._send_busy_response", new_callable=AsyncMock) as mock_busy:
            with patch("session_manager.make_ws_transport", side_effect=RuntimeError("stop")):
                try:
                    await sm.run_ws("s1", ws)
                except RuntimeError:
                    pass

        mock_busy.assert_not_called()

    def test_session_info_status_field_accepts_active(self) -> None:
        """Sanity check: SessionInfo.status can hold 'active'."""
        from schemas import SessionInfo
        info = SessionInfo(
            session_id="s",
            agent_id="a",
            call_id="c",
            status="active",
            ws_url="ws://x",
            created_at="2026-03-03",
        )
        assert info.status == "active"


# ── TestMetricsEndpoint ───────────────────────────────────────────────────────


class TestMetricsEndpoint:
    """GET /metrics returns a valid MetricsSnapshot dict."""

    def setup_method(self) -> None:
        metrics_module._metrics = None

    def teardown_method(self) -> None:
        metrics_module._metrics = None

    def test_metrics_endpoint_returns_200(self) -> None:
        from fastapi.testclient import TestClient
        from server import app

        init_metrics(max_concurrent_calls=3)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_endpoint_has_required_keys(self) -> None:
        from fastapi.testclient import TestClient
        from server import app

        init_metrics(max_concurrent_calls=3)
        client = TestClient(app, raise_server_exceptions=False)
        data = client.get("/metrics").json()

        required_keys = {
            "sessions_active",
            "max_concurrent_calls",
            "avg_vad_ms",
            "avg_stt_ms",
            "avg_llm_ttft_ms",
            "avg_tts_ttfb_ms",
            "avg_e2e_ms",
            "p95_e2e_ms",
            "total_calls_served",
            "uptime_s",
        }
        missing = required_keys - data.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_metrics_endpoint_max_concurrent_matches(self) -> None:
        from fastapi.testclient import TestClient
        from server import app

        init_metrics(max_concurrent_calls=3)
        client = TestClient(app, raise_server_exceptions=False)
        data = client.get("/metrics").json()
        assert data["max_concurrent_calls"] == 3

    def test_metrics_endpoint_503_before_init(self) -> None:
        """Before init_metrics(), the endpoint must return 503."""
        from fastapi.testclient import TestClient
        from server import app

        # metrics singleton is None after teardown_method
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/metrics")
        # 503 because get_metrics() returns None
        assert resp.status_code == 503

    def test_health_endpoint_still_works(self) -> None:
        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
