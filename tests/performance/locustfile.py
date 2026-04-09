"""
VoiceSaaS Platform — Locust Load Test
======================================
Acceptance criteria (Day 16.5):
  • 3 concurrent simulated calls
  • P95 end-to-end API latency < 900 ms
  • 0 % error (crash) rate across the scenario

Run locally (requires a live stack):
    locust -f tests/performance/locustfile.py \
           --headless -u 3 -r 1 \
           --run-time 60s \
           --host http://localhost:8000 \
           --html tests/performance/report.html \
           --csv  tests/performance/results

Environment variables (override defaults):
    LOCUST_EMAIL    admin@demo.local
    LOCUST_PASSWORD demo1234
    LOCUST_ORG_SLUG demo-org
    LOCUST_AGENT_ID <UUID>   (optional; will use first listed agent otherwise)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from locust import HttpUser, SequentialTaskSet, between, events, task
from locust.env import Environment

# ── Tunables ──────────────────────────────────────────────────────────────────
_EMAIL = os.getenv("LOCUST_EMAIL", "admin@demo.local")
_PASS = os.getenv("LOCUST_PASSWORD", "demo1234")
_ORG_SLUG = os.getenv("LOCUST_ORG_SLUG", "demo-org")
_AGENT_ID = os.getenv("LOCUST_AGENT_ID", "")

# ── P95 threshold (ms) ────────────────────────────────────────────────────────
P95_THRESHOLD_MS = 900


# ── Custom event hook: fail the run if P95 exceeds threshold ──────────────────
@events.quitting.add_listener
def assert_p95(environment: Environment, **_kw: Any) -> None:
    stats = environment.runner.stats
    total = stats.total
    if total.num_requests == 0:
        return
    p95 = total.get_response_time_percentile(0.95)
    fail_ratio = total.fail_ratio
    print(f"\n{'='*60}")
    print(f"  Total requests : {total.num_requests}")
    print(f"  Error rate     : {fail_ratio*100:.2f}%")
    print(f"  P50 latency    : {total.get_response_time_percentile(0.50):.0f} ms")
    print(f"  P95 latency    : {p95:.0f} ms  (threshold: {P95_THRESHOLD_MS} ms)")
    print(f"  P99 latency    : {total.get_response_time_percentile(0.99):.0f} ms")
    print(f"{'='*60}\n")
    if fail_ratio > 0:
        print(f"FAIL: error rate {fail_ratio*100:.1f}% > 0%")
        environment.process_exit_code = 1
    if p95 > P95_THRESHOLD_MS:
        print(f"FAIL: P95 {p95:.0f} ms exceeds {P95_THRESHOLD_MS} ms threshold")
        environment.process_exit_code = 1
    else:
        print("PASS: All acceptance criteria met.")


# ── Shared state (populated during on_start) ──────────────────────────────────

class _State:
    token: str = ""
    org_id: str = ""
    agent_id: str = _AGENT_ID


# ── Task sets ─────────────────────────────────────────────────────────────────

class AuthFlow(SequentialTaskSet):
    """
    Sequential login → discover org → pick an agent.
    Runs once per simulated user on startup.
    """

    @task
    def login(self) -> None:
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"email": _EMAIL, "password": _PASS},
            name="POST /auth/login",
        )
        if resp.status_code == 200:
            data = resp.json()
            _State.token = data.get("access_token", "")
            self.user.client.headers["Authorization"] = f"Bearer {_State.token}"

    @task
    def get_org(self) -> None:
        resp = self.client.get(
            f"/api/v1/organizations/{_ORG_SLUG}",
            name="GET /organizations/{slug}",
        )
        if resp.status_code == 200:
            _State.org_id = resp.json().get("id", "")
            self.user.client.headers["X-Org-ID"] = _State.org_id

    @task
    def pick_agent(self) -> None:
        if _State.agent_id:
            return
        resp = self.client.get("/api/v1/agents", name="GET /agents")
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                _State.agent_id = items[0]["id"]

    # leave the auth flow task set
    @task
    def exit_flow(self) -> None:
        self.interrupt()


class CallScenario(SequentialTaskSet):
    """
    Simulates one complete call lifecycle per virtual user:
      1. Health-check
      2. Fetch agent
      3. POST webrtc/connect   ← primary latency measurement
      4. POST /calls            (log the call)
      5. GET  dashboard overview
    """

    wait_time = between(0.2, 0.5)

    @task
    def health(self) -> None:
        self.client.get("/health", name="GET /health")

    @task
    def get_agent(self) -> None:
        if not _State.agent_id:
            return
        self.client.get(
            f"/api/v1/agents/{_State.agent_id}",
            name="GET /agents/{agent_id}",
        )

    @task
    def webrtc_connect(self) -> None:
        """
        Primary latency probe: POST the WebRTC connect endpoint.
        P95 of this single call must stay under 900 ms.
        """
        if not _State.agent_id:
            return
        payload = {
            "sdp": (
                "v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
                "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
                "a=rtpmap:111 opus/48000/2\r\n"
            ),
            "type": "offer",
        }
        start = time.perf_counter()
        self.client.post(
            f"/api/v1/agents/{_State.agent_id}/webrtc/connect",
            json=payload,
            name="POST /agents/{id}/webrtc/connect",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        # Emit a custom metric for reporting
        events.request.fire(
            request_type="E2E",
            name="webrtc.connect.e2e",
            response_time=elapsed_ms,
            response_length=0,
        )

    @task
    def write_call_log(self) -> None:
        if not (_State.agent_id and _State.org_id):
            return
        self.client.post(
            "/api/v1/calls",
            json={
                "agent_id": _State.agent_id,
                "org_id": _State.org_id,
                "session_id": str(uuid.uuid4()),
                "direction": "inbound",
                "transport": "webrtc",
                "status": "completed",
                "duration_sec": 12,
            },
            name="POST /calls",
        )

    @task
    def dashboard_overview(self) -> None:
        self.client.get(
            "/api/v1/dashboard/overview",
            name="GET /dashboard/overview",
        )

    @task
    def loop(self) -> None:
        self.interrupt()


class VoiceSaaSUser(HttpUser):
    """
    Represents one concurrent call in the load test.
    - 3 users (-u 3) = 3 simultaneous calls
    - Ramp-up rate: 1 user/s (-r 1)
    - Wait between task iterations: 0.1–0.3 s
    """

    tasks = [AuthFlow, CallScenario]
    wait_time = between(0.1, 0.3)
    # Persist connection across requests (keep-alive)
    connection_timeout = 15
    network_timeout = 15

    def on_start(self) -> None:
        """Authenticate once, then start call scenario loop."""
        # Run auth once
        auth = AuthFlow(self)
        auth.login()
        auth.get_org()
        auth.pick_agent()
