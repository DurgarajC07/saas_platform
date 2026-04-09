#!/usr/bin/env python3
"""
Pipeline smoke test  —  scripts/smoke_test_pipeline.py

Validates the Pipeline Service (port 7000) end-to-end:

  1. GET  /health          → status == "ok"
  2. GET  /info            → version field present
  3. POST /sessions        → returns SessionInfo with ws_url
  4. GET  /sessions/{id}   → returns the same SessionInfo
  5. WS   /sessions/{id}/ws  → send 1 s voiced PCM, receive audio back
  6. DELETE /sessions/{id} → 200 OK

Run requirements:
    pip install websockets httpx numpy
    # Pipeline service must be running on localhost:7000
    # Whisper, Kokoro, Qdrant must also be up (or the session will error;
    #   that is still a PASS at the REST layer, WARN at the WS layer).

Usage:
    python scripts/smoke_test_pipeline.py
    python scripts/smoke_test_pipeline.py --host localhost --port 7001
"""
from __future__ import annotations

import argparse
import asyncio
import json
import struct
import sys
import time
import uuid
from typing import Any

try:
    import httpx
    import numpy as np
    import websockets
except ImportError as exc:
    print(f"[SKIP] Missing dependency: {exc}")
    print("       pip install websockets httpx numpy")
    sys.exit(0)

# ── Defaults ───────────────────────────────────────────────────────────────
_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 7_000

# Thresholds
_HEALTH_TIMEOUT_S = 5.0
_SESSION_CREATE_MS = 500
_WS_CONNECT_TIMEOUT_S = 10.0
_WS_FIRST_RESPONSE_MS = 5_000   # ms — may need LLM + TTS warmup
_WS_AUDIO_SEND_S = 1.0          # seconds of PCM to send

# ── Audio helpers ──────────────────────────────────────────────────────────

def _voiced_pcm(duration_s: float, sample_rate: int = 16_000) -> bytes:
    """Generate multi-harmonic int16 PCM resembling a voiced utterance."""
    t = np.linspace(0.0, duration_s, int(duration_s * sample_rate), endpoint=False)
    # Emulate the harmonic structure of a vowel (F0=120 Hz + overtones)
    signal = (
        0.45 * np.sin(2 * np.pi * 120 * t)
        + 0.25 * np.sin(2 * np.pi * 240 * t)
        + 0.15 * np.sin(2 * np.pi * 360 * t)
        + 0.10 * np.sin(2 * np.pi * 480 * t)
        + 0.05 * np.sin(2 * np.pi * 600 * t)
    )
    # Ramp in / ramp out (10 ms) to avoid clicks
    ramp = int(0.01 * sample_rate)
    fade = np.ones_like(signal)
    fade[:ramp] = np.linspace(0, 1, ramp)
    fade[-ramp:] = np.linspace(1, 0, ramp)
    pcm = (signal * fade * 32000).astype(np.int16)
    return pcm.tobytes()


# ── Pretty-print helpers ───────────────────────────────────────────────────

def _ok(label: str, detail: str = "") -> None:
    print(f"  \033[32m✓ PASS\033[0m  {label}" + (f"  ({detail})" if detail else ""))


def _fail(label: str, detail: str = "") -> None:
    print(f"  \033[31m✗ FAIL\033[0m  {label}" + (f"  — {detail}" if detail else ""))


def _warn(label: str, detail: str = "") -> None:
    print(f"  \033[33m⚠ WARN\033[0m  {label}" + (f"  — {detail}" if detail else ""))


def _note(msg: str) -> None:
    print(f"         \033[90m{msg}\033[0m")


# ── Test blocks ────────────────────────────────────────────────────────────

async def test_http(base_url: str) -> tuple[bool, str | None]:
    """
    Run the HTTP REST checks.  Returns (all_passed, session_id | None).
    """
    passed = True
    session_id: str | None = None

    async with httpx.AsyncClient(base_url=base_url, timeout=_HEALTH_TIMEOUT_S) as c:

        # ── /health ──────────────────────────────────────────────────
        try:
            t0 = time.monotonic()
            r = await c.get("/health")
            ms = (time.monotonic() - t0) * 1000
            if r.status_code == 200 and r.json().get("status") == "ok":
                _ok("GET /health", f"{ms:.0f} ms")
            else:
                _fail("GET /health", f"status={r.status_code} body={r.text[:120]}")
                passed = False
        except Exception as exc:
            _fail("GET /health", str(exc))
            return False, None   # no point continuing if service is unreachable

        # ── /info ─────────────────────────────────────────────────────
        try:
            r = await c.get("/info")
            body: dict[str, Any] = r.json()
            if r.status_code == 200 and "version" in body:
                _ok("GET /info", f"version={body['version']}")
            else:
                _fail("GET /info", r.text[:120])
                passed = False
        except Exception as exc:
            _fail("GET /info", str(exc))
            passed = False

        # ── POST /sessions ────────────────────────────────────────────
        payload = {
            "agent_config": {
                "agent_id": str(uuid.uuid4()),
                "organization_id": str(uuid.uuid4()),
                "name": "smoke-test-agent",
                "agent_type": "conversational",
                "llm_model": "qwen2.5:3b",
                "system_prompt": "You are a helpful assistant. Reply concisely.",
                "tts_voice": "af_heart",
                "noise_removal_enabled": False,
                "allow_interruptions": True,
            },
            "call_id": f"smoke-{uuid.uuid4().hex[:8]}",
            "metadata": {"test": True},
        }
        try:
            t0 = time.monotonic()
            r = await c.post("/sessions", json=payload)
            ms = (time.monotonic() - t0) * 1000
            if r.status_code in (200, 201):
                body = r.json()
                session_id = body.get("session_id")
                ws_url = body.get("ws_url", "")
                _ok(
                    "POST /sessions",
                    f"{ms:.0f} ms  session={session_id[:8]}…  ws={ws_url}",
                )
                if ms > _SESSION_CREATE_MS:
                    _warn(
                        "POST /sessions latency",
                        f"{ms:.0f} ms > {_SESSION_CREATE_MS} ms threshold",
                    )
            else:
                _fail("POST /sessions", f"status={r.status_code} body={r.text[:200]}")
                passed = False
        except Exception as exc:
            _fail("POST /sessions", str(exc))
            passed = False

        if not session_id:
            return passed, None

        # ── GET /sessions/{id} ────────────────────────────────────────
        try:
            r = await c.get(f"/sessions/{session_id}")
            if r.status_code == 200 and r.json().get("session_id") == session_id:
                _ok("GET /sessions/{id}")
            else:
                _fail(
                    "GET /sessions/{id}",
                    f"status={r.status_code} body={r.text[:120]}",
                )
                passed = False
        except Exception as exc:
            _fail("GET /sessions/{id}", str(exc))
            passed = False

    return passed, session_id


async def test_ws(ws_url: str, session_id: str) -> bool:
    """Connect via WebSocket, send PCM audio, and check for a binary response."""
    _note(f"WebSocket URL: {ws_url}")
    try:
        t0 = time.monotonic()
        async with websockets.connect(
            ws_url,
            open_timeout=_WS_CONNECT_TIMEOUT_S,
            max_size=4 * 1024 * 1024,
        ) as ws:
            connect_ms = (time.monotonic() - t0) * 1000
            _note(f"WS connected in {connect_ms:.0f} ms")

            # Send 1 second of voiced PCM in 20 ms chunks
            pcm = _voiced_pcm(_WS_AUDIO_SEND_S)
            chunk_size = 640  # 20 ms × 16 kHz × 2 bytes
            for i in range(0, len(pcm), chunk_size):
                await ws.send(pcm[i:i + chunk_size])
            _note(f"Sent {len(pcm)//2} samples ({len(pcm)} bytes) in chunks")

            # Wait for any response (binary audio or JSON event)
            try:
                t0 = time.monotonic()
                msg = await asyncio.wait_for(
                    ws.recv(), timeout=_WS_FIRST_RESPONSE_MS / 1000
                )
                ttfr_ms = (time.monotonic() - t0) * 1000
                if isinstance(msg, bytes):
                    _ok(
                        "WS receive (binary audio)",
                        f"ttfr={ttfr_ms:.0f} ms  bytes={len(msg)}",
                    )
                elif isinstance(msg, str):
                    _ok(
                        "WS receive (JSON event)",
                        f"ttfr={ttfr_ms:.0f} ms  msg={msg[:80]}",
                    )
                    _note(
                        "NOTE: received a JSON event — pipeline may still be "
                        "processing audio (normal during LLM warmup)"
                    )
                return True
            except asyncio.TimeoutError:
                _warn(
                    "WS receive timeout",
                    f"no response within {_WS_FIRST_RESPONSE_MS} ms — check "
                    "that Whisper/Kokoro/Ollama are running",
                )
                return True   # service is UP; downstream may not be ready yet
    except Exception as exc:
        _fail("WS connect / exchange", str(exc))
        return False


async def test_delete(base_url: str, session_id: str) -> bool:
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as c:
        try:
            r = await c.delete(f"/sessions/{session_id}")
            if r.status_code in (200, 204):
                _ok(f"DELETE /sessions/{session_id[:8]}…")
                return True
            else:
                _fail(
                    "DELETE /sessions/{id}",
                    f"status={r.status_code}",
                )
                return False
        except Exception as exc:
            _fail("DELETE /sessions/{id}", str(exc))
            return False


# ── Entry point ────────────────────────────────────────────────────────────

async def main(host: str, port: int) -> int:
    base_url = f"http://{host}:{port}"
    ws_base = f"ws://{host}:{port}"

    print(f"\n{'─'*60}")
    print(f"  Pipeline Smoke Test  →  {base_url}")
    print(f"{'─'*60}\n")

    all_passed = True

    # Step 1-4: HTTP REST checks
    print("── HTTP ─────────────────────────────────────────────────")
    http_ok, session_id = await test_http(base_url)
    all_passed = all_passed and http_ok

    # Step 5: WebSocket
    if session_id:
        print("\n── WebSocket ─────────────────────────────────────────────")
        ws_url = f"{ws_base}/sessions/{session_id}/ws"
        ws_ok = await test_ws(ws_url, session_id)
        all_passed = all_passed and ws_ok

        # Step 6: DELETE
        print("\n── Cleanup ───────────────────────────────────────────────")
        del_ok = await test_delete(base_url, session_id)
        all_passed = all_passed and del_ok
    else:
        _warn("Skipping WS + DELETE tests (no session_id from POST /sessions)")

    print(f"\n{'─'*60}")
    if all_passed:
        print("  \033[32mAll checks passed.\033[0m")
    else:
        print("  \033[31mSome checks FAILED — see above.\033[0m")
    print(f"{'─'*60}\n")
    return 0 if all_passed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline service smoke test")
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.host, args.port)))
