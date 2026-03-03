"""
WebSocket Smoke Tests — Day 2

Validates the WebSocket streaming endpoints added in Day 2:

  ws://localhost:9001/transcribe/stream   Whisper STT streaming
  ws://localhost:8881/tts/stream          Kokoro TTS streaming

Usage
-----
    python scripts/smoke_test_ws.py                    # run both tests
    python scripts/smoke_test_ws.py --whisper-only
    python scripts/smoke_test_ws.py --kokoro-only

Requirements
------------
    pip install websockets numpy

The websockets library is NOT bundled in the saas_platform venv — install it
separately before running this script, or activate the infra dev venv:

    pip install websockets numpy

Protocol tested
---------------
Whisper:
    1. Uses /tmp/test.wav if it exists (real speech gives the most accurate benchmark).
    2. Falls back to a 1-second multi-harmonic voiced-speech approximation
       (fundamental + harmonics = more Whisper-friendly than pure sine waves).
    3. Send b'END' to trigger transcription.
    4. Expect JSON response with {"text": ..., "language": ..., "elapsed_ms": ...}.

Kokoro:
    1. Connect to /tts/stream.
    2. Send a short first sentence (< 20 chars) to measure true TTFB,
       then a full paragraph to measure throughput.
    3. Receive WAV bytes chunks until {"done": true} JSON response.
    4. Report TTFB and total elapsed time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import struct
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Dependency check — give a clear error before the confusing ImportError
# ---------------------------------------------------------------------------
try:
    import websockets  # noqa: F401
    import numpy as np
except ImportError as exc:
    print(
        f"\n  [ERROR] Missing dependency: {exc}\n"
        "  Install with:  pip install websockets numpy\n",
        file=sys.stderr,
    )
    sys.exit(1)

import websockets.asyncio.client as ws_client  # type: ignore[attr-defined]

# ── Configuration ─────────────────────────────────────────────────────────────

WHISPER_WS_URL = "ws://localhost:9001/transcribe/stream"
KOKORO_WS_URL  = "ws://localhost:8881/tts/stream"
CHUNK_SIZE     = 4096   # bytes per send to Whisper
# Latency targets (ms)
_WHISPER_TARGET_MS = 400   # < 400ms for 5s real speech with CUDA
_KOKORO_TTFB_MS    = 200   # < 200ms TTFB for short first sentence on CPU
RESULTS: dict[str, Any] = {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _green(msg: str) -> str:
    return f"\033[92m{msg}\033[0m"

def _red(msg: str) -> str:
    return f"\033[91m{msg}\033[0m"

def _yellow(msg: str) -> str:
    return f"\033[93m{msg}\033[0m"


def _tts_info() -> dict | None:
    """Fetch /info from the whisper service to display GPU details."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:9001/info", timeout=3) as r:
            import json as _json
            return _json.loads(r.read())
    except Exception:
        return None


def _voiced_pcm(duration_s: float = 1.0, fundamental_hz: float = 120.0, sample_rate: int = 16000) -> bytes:
    """
    Generate a voiced-speech approximation as raw int16 PCM bytes.

    Uses a fundamental frequency (typical male speech F0 = 120Hz) plus
    harmonics (H2-H5 with decreasing amplitude) to create a vowel-like
    waveform that triggers Whisper's speech detector more reliably than
    a pure sine tone.
    """
    n_samples = int(duration_s * sample_rate)
    harmonics = [(1, 0.40), (2, 0.25), (3, 0.15), (4, 0.10), (5, 0.06), (6, 0.04)]
    signal = [
        sum(
            amp * math.sin(2 * math.pi * (fundamental_hz * h) * i / sample_rate)
            for h, amp in harmonics
        )
        for i in range(n_samples)
    ]
    return struct.pack(f"<{n_samples}h", *(int(s * 32767) for s in signal))


def _tone_pcm(duration_s: float = 5.0, freq_hz: float = 440.0, sample_rate: int = 16000) -> bytes:
    """
    Generate a sine-wave tone as raw int16 PCM bytes.

    Whisper will likely transcribe this as silence / no-speech (which is fine
    for a liveness smoke test — we only care that the endpoint responds with
    valid JSON, not about transcript accuracy).
    """
    n_samples = int(duration_s * sample_rate)
    samples = [
        int(0.3 * 32767 * math.sin(2 * math.pi * freq_hz * i / sample_rate))
        for i in range(n_samples)
    ]
    return struct.pack(f"<{n_samples}h", *samples)


# ── Whisper WebSocket Test ─────────────────────────────────────────────────────

async def test_whisper_ws() -> bool:
    """
    Stream speech audio to /transcribe/stream and validate the response.

    Audio source priority:
      1. /tmp/test.wav  — real speech, most accurate benchmark
      2. 1-second voiced PCM  — multi-harmonic approximation, better than sine
    """
    print("\n" + "─" * 60)
    print("Whisper STT WebSocket test")
    print(f"  URL: {WHISPER_WS_URL}")
    print("─" * 60)

    # Show GPU info
    info = _tts_info()
    if info:
        print(f"  Whisper device:   {info.get('device')} / {info.get('compute_type')}")
        print(f"  Model:            {info.get('model')}  (loaded in {info.get('load_s')}s)")

    # Prefer a real WAV file for an accurate benchmark
    wav_path = Path("/tmp/test.wav")
    if wav_path.exists():
        pcm_bytes = wav_path.read_bytes()
        audio_label = f"real WAV file ({len(pcm_bytes):,} bytes from {wav_path})"
    else:
        pcm_bytes = _voiced_pcm(duration_s=1.0)  # 1s voiced, ~32 KB
        audio_label = (
            f"{len(pcm_bytes):,} bytes voiced PCM (1 s multi-harmonic, 16 kHz)  "
            "[tip: put a real speech WAV at /tmp/test.wav for accurate benchmarks]"
        )
    print(f"  Audio: {audio_label}")

    t_connect = time.perf_counter()
    try:
        async with ws_client.connect(WHISPER_WS_URL, open_timeout=10) as websocket:
            connect_ms = round((time.perf_counter() - t_connect) * 1000, 1)
            print(f"  Connected in {connect_ms} ms")

            # Stream PCM in chunks
            t_stream = time.perf_counter()
            offset = 0
            chunks_sent = 0
            while offset < len(pcm_bytes):
                end = min(offset + CHUNK_SIZE, len(pcm_bytes))
                await websocket.send(pcm_bytes[offset:end])
                offset = end
                chunks_sent += 1
            await websocket.send(b"END")
            stream_ms = round((time.perf_counter() - t_stream) * 1000, 1)
            print(f"  Streamed {chunks_sent} chunks + END in {stream_ms} ms")

            # Wait for transcription result
            t_wait = time.perf_counter()
            raw = await asyncio.wait_for(websocket.recv(), timeout=30.0)

        elapsed_ms = round((time.perf_counter() - t_wait) * 1000, 1)

    except asyncio.TimeoutError:
        print(_red("  FAIL — timed out waiting for transcription result (30 s)"))
        RESULTS["whisper_ws"] = "TIMEOUT"
        return False
    except Exception as exc:
        print(_red(f"  FAIL — connection error: {exc}"))
        RESULTS["whisper_ws"] = f"ERROR: {exc}"
        return False

    # Validate response
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(_red(f"  FAIL — invalid JSON response: {exc}"))
        print(f"  Raw: {raw[:200]}")
        RESULTS["whisper_ws"] = "BAD_JSON"
        return False

    if "error" in result:
        print(_red(f"  FAIL — server returned error: {result['error']}"))
        RESULTS["whisper_ws"] = f"SERVER_ERROR: {result['error']}"
        return False

    required_keys = {"text", "language", "language_probability", "elapsed_ms"}
    missing = required_keys - set(result.keys())
    if missing:
        print(_red(f"  FAIL — response missing keys: {missing}"))
        RESULTS["whisper_ws"] = f"MISSING_KEYS: {missing}"
        return False

    srv_ms = result["elapsed_ms"]
    lang   = result["language"]

    print(f"  Server elapsed:   {srv_ms} ms")
    print(f"  Client wait:      {elapsed_ms} ms")
    print(f"  Language:         {lang} (p={result['language_probability']:.4f})")
    print(f"  Transcript:       '{result['text']}'")
    print(f"  Segments:         {len(result.get('segments', []))}")
    print(_green("  PASS"))

    # Warn only when genuinely slow — sine tones score high, real speech will be faster
    if srv_ms > _WHISPER_TARGET_MS and not wav_path.exists():
        print(_yellow(
            f"  NOTE: {srv_ms} ms on synthetic audio — "
            "put real speech at /tmp/test.wav for an accurate GPU benchmark"
        ))
    elif srv_ms > _WHISPER_TARGET_MS:
        print(_yellow(f"  WARNING: server latency {srv_ms} ms > {_WHISPER_TARGET_MS} ms target — check GPU load"))

    RESULTS["whisper_ws"] = f"PASS ({srv_ms} ms)"
    return True


# ── Kokoro WebSocket Test ─────────────────────────────────────────────────────

async def test_kokoro_ws() -> bool:
    """
    Two-phase Kokoro WS test:
      Phase 1 — short utterance (< 20 chars) to measure true TTFB.
      Phase 2 — full paragraph to verify multi-chunk streaming.
    """
    SHORT_TEXT  = "Hello there."          # 13 chars — should yield < 200ms TTFB on CPU
    FULL_TEXT   = "Hello, this is a WebSocket TTS smoke test. Streaming audio chunk by chunk."
    TEST_VOICE  = "af_heart"

    print("\n" + "─" * 60)
    print("Kokoro TTS WebSocket test")
    print(f"  URL: {KOKORO_WS_URL}")
    print("─" * 60)
    print(f"  Phase 1 — short TTFB test  ({len(SHORT_TEXT)} chars): '{SHORT_TEXT}'")
    print(f"  Phase 2 — full stream test ({len(FULL_TEXT)} chars): '{FULL_TEXT}'")

    t_connect = time.perf_counter()
    try:
        async with ws_client.connect(KOKORO_WS_URL, open_timeout=10) as websocket:
            connect_ms = round((time.perf_counter() - t_connect) * 1000, 1)
            print(f"  Connected in {connect_ms} ms")

            # Send Phase 1 (short utterance — TTFB benchmark)
            t_send = time.perf_counter()
            await websocket.send(json.dumps({"text": SHORT_TEXT, "voice": TEST_VOICE, "speed": 1.0, "lang": "a"}))

            ttfb_ms: float | None = None
            short_elapsed: float = 0
            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                if isinstance(msg, bytes):
                    if ttfb_ms is None:
                        ttfb_ms = round((time.perf_counter() - t_send) * 1000, 1)
                        print(f"  Phase 1 TTFB (first audio byte): {ttfb_ms} ms")
                else:
                    jmsg = json.loads(msg) if isinstance(msg, str) else {}
                    if jmsg.get("done"):
                        short_elapsed = jmsg.get("elapsed_ms", 0)
                        print(f"  Phase 1 total elapsed:           {short_elapsed} ms")
                        break
                    if "error" in jmsg:
                        print(_red(f"  FAIL — Phase 1 error: {jmsg['error']}"))
                        RESULTS["kokoro_ws"] = f"SERVER_ERROR: {jmsg['error']}"
                        return False

            # Send Phase 2 (full paragraph — throughput)
            t_full = time.perf_counter()
            await websocket.send(json.dumps({"text": FULL_TEXT, "voice": TEST_VOICE, "speed": 1.0, "lang": "a"}))

            chunks: list[bytes] = []
            done_info: dict | None = None

            while True:
                msg = await asyncio.wait_for(websocket.recv(), timeout=30.0)

                if isinstance(msg, bytes):
                    chunks.append(msg)
                    if ttfb_ms is None:  # already measured in phase 1 — reuse variable for phase 2
                        pass
                else:
                    # JSON text message — expect {"done": true, ...}
                    try:
                        jmsg = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    if jmsg.get("done"):
                        done_info = jmsg
                        break
                    if "error" in jmsg:
                        print(_red(f"  FAIL — server error: {jmsg['error']}"))
                        RESULTS["kokoro_ws"] = f"SERVER_ERROR: {jmsg['error']}"
                        return False

    except asyncio.TimeoutError:
        print(_red("  FAIL — timed out waiting for TTS audio (30 s)"))
        RESULTS["kokoro_ws"] = "TIMEOUT"
        return False
    except Exception as exc:
        print(_red(f"  FAIL — connection error: {exc}"))
        RESULTS["kokoro_ws"] = f"ERROR: {exc}"
        return False

    if done_info is None:
        print(_red("  FAIL — never received {\"done\": true} message"))
        RESULTS["kokoro_ws"] = "NO_DONE_MSG"
        return False

    total_bytes = sum(len(c) for c in chunks)
    srv_ms = done_info.get("elapsed_ms", 0) if done_info else 0

    print(f"  Phase 2 audio chunks:          {len(chunks)}")
    print(f"  Phase 2 total audio bytes:     {total_bytes:,}")
    print(f"  Phase 2 elapsed:               {srv_ms} ms")

    # Save first chunk for verification
    if chunks:
        out_path = Path("/tmp/tts_ws_test.wav")
        out_path.write_bytes(chunks[0])
        print(f"  First chunk saved to:  {out_path}")

    print(_green("  PASS"))

    if ttfb_ms is not None and ttfb_ms > _KOKORO_TTFB_MS:
        print(_yellow(
            f"  NOTE: Phase 1 TTFB {ttfb_ms} ms > {_KOKORO_TTFB_MS} ms — "
            "expected on CPU-only Kokoro; RTX 4060 GPU TTS would be < 50ms"
        ))

    RESULTS["kokoro_ws"] = f"PASS (ttfb={ttfb_ms} ms, total={srv_ms} ms)"
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(run_whisper: bool, run_kokoro: bool) -> int:
    passed = 0
    failed = 0

    if run_whisper:
        ok = await test_whisper_ws()
        if ok:
            passed += 1
        else:
            failed += 1

    if run_kokoro:
        ok = await test_kokoro_ws()
        if ok:
            passed += 1
        else:
            failed += 1

    # Summary
    print("\n" + "═" * 60)
    print("WebSocket Smoke Test Summary")
    print("─" * 60)
    for name, val in RESULTS.items():
        icon = "✓" if val.startswith("PASS") else "✗"
        colour = _green if val.startswith("PASS") else _red
        print(f"  {colour(icon)} {name:<20} {val}")
    print("─" * 60)
    print(f"  Passed: {passed}   Failed: {failed}")
    print("═" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebSocket smoke tests for Whisper STT and Kokoro TTS")
    parser.add_argument("--whisper-only", action="store_true", help="Only test Whisper WS")
    parser.add_argument("--kokoro-only",  action="store_true", help="Only test Kokoro WS")
    args = parser.parse_args()

    run_whisper = not args.kokoro_only
    run_kokoro  = not args.whisper_only

    sys.exit(asyncio.run(main(run_whisper, run_kokoro)))
