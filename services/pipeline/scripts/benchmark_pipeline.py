#!/usr/bin/env python3
"""
Full pipeline benchmark — Day 8 latency measurement.

Connects to the running Pipeline Service via HTTP + WebSocket, feeds a short
audio clip (real WAV file or synthetic fallback), and measures per-stage
latency collected from server-sent JSON events.

Usage
-----
Run inside the pipeline container::

    python scripts/benchmark_pipeline.py [--wav PATH] [--url BASE_URL] [--runs N]

Arguments
---------
--wav PATH      Path to a mono 16-bit PCM WAV at 16 kHz.  If omitted or not
                found, a 2-second synthetic sine tone is used instead.
--url BASE_URL  Pipeline service base URL (default: http://localhost:7000).
--runs N        Number of benchmark iterations (default: 3).  Averages are
                reported at the end.

Output example
--------------
  Run 1/3
    STT latency        :   312 ms
    LLM TTFT           :   198 ms
    TTS first audio    :   109 ms
    E2E (WS open→audio):   639 ms
    Total session      :  4312 ms

  ─────────── Summary (3 runs) ───────────
    avg STT            :   305 ms
    avg LLM TTFT       :   201 ms
    avg TTS TTFB       :   113 ms
    avg E2E            :   628 ms
    p95 E2E            :   651 ms
  ✓ E2E latency < 900 ms  [PASS]

Critical threshold
------------------
E2E latency MUST be < 900 ms for a 1-sentence utterance on an RTX 4060.
The script exits with code 1 if the average exceeds this limit so it can
be used in CI gating.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import struct
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp

# ── Constants ─────────────────────────────────────────────────────────────────

_SAMPLE_RATE = 16_000          # Hz — Whisper expects 16 kHz mono
_CHUNK_MS    = 20              # ms per audio chunk sent over WS
_CHUNK_BYTES = int(_SAMPLE_RATE * _CHUNK_MS / 1000) * 2   # int16 = 2 bytes/sample
_E2E_LIMIT_MS = 900           # critical threshold from spec

# ── Audio helpers ─────────────────────────────────────────────────────────────


def _generate_sine(frequency_hz: float = 440.0, duration_s: float = 2.0) -> bytes:
    """
    Generate *duration_s* seconds of a sine tone as raw int16 PCM.

    Uses 440 Hz (A4) which passes Whisper VAD as an active audio signal
    even though the transcript will be empty or garbled.  Good for latency
    benchmarking without a real speech recording.
    """
    n_samples = int(_SAMPLE_RATE * duration_s)
    samples: list[int] = []
    for i in range(n_samples):
        t = i / _SAMPLE_RATE
        sample = int(math.sin(2 * math.pi * frequency_hz * t) * 8000)
        samples.append(max(-32768, min(32767, sample)))
    return struct.pack(f"<{n_samples}h", *samples)


def _load_wav(path: str) -> bytes | None:
    """
    Read a WAV file and return raw int16 PCM bytes, or ``None`` on error.

    Validates that the file is 16-bit PCM at 16 kHz mono (the format
    expected by the pipeline). Returns ``None`` if validation fails so
    the caller can fall back to synthetic audio.
    """
    try:
        import wave as wav

        with wav.open(path, "rb") as wf:
            if wf.getsampwidth() != 2:
                print(f"  [warn] {path}: expected 16-bit PCM (samplewidth=2)")
                return None
            if wf.getframerate() != _SAMPLE_RATE:
                print(f"  [warn] {path}: expected {_SAMPLE_RATE} Hz (got {wf.getframerate()})")
                return None
            if wf.getnchannels() != 1:
                print(f"  [warn] {path}: expected mono (got {wf.getnchannels()} channels)")
                return None
            return wf.readframes(wf.getnframes())
    except Exception as exc:
        print(f"  [warn] Could not read WAV {path!r}: {exc}")
        return None


# ── AgentConfig factory ───────────────────────────────────────────────────────


def _benchmark_agent() -> dict[str, Any]:
    """Return an AgentConfig dict suitable for benchmarking."""
    return {
        "agent_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "name": "Benchmark Agent",
        "agent_type": "conversational",
        "llm_model": "qwen2.5:3b",
        "system_prompt": (
            "You are a helpful assistant. Keep your reply to at most 2 short sentences."
        ),
        "tts_voice": "af_heart",
        "tts_speed": 1.0,
        "tts_lang": "a",
        "vad_threshold": 0.5,
        "min_speech_ms": 250,
        "silence_ms": 800,
        "noise_removal_level": "rnnoise",
        "allow_interruptions": True,
        "temperature": 0.3,
        "max_tokens": 80,
        "max_turns": 5,
    }


# ── Single-run benchmark ──────────────────────────────────────────────────────


class RunResult:
    """Timing results for one benchmark run."""

    __slots__ = (
        "stt_ms",
        "llm_ttft_ms",
        "tts_ttfb_ms",
        "e2e_ms",
        "total_ms",
    )

    def __init__(self) -> None:
        self.stt_ms:      float | None = None
        self.llm_ttft_ms: float | None = None
        self.tts_ttfb_ms: float | None = None
        self.e2e_ms:      float | None = None
        self.total_ms:    float | None = None


async def run_single(
    base_url: str,
    audio_pcm: bytes,
    run_idx: int,
    total_runs: int,
) -> RunResult:
    """
    Execute one benchmark run: create session → connect WS → stream audio →
    receive first text/audio events → measure timings.
    """
    result = RunResult()
    print(f"\n  Run {run_idx + 1}/{total_runs}")

    http_url = base_url.rstrip("/")

    async with aiohttp.ClientSession() as http:

        # ── 1. Create session ──────────────────────────────────────────────
        session_payload = {
            "agent_config": _benchmark_agent(),
            "call_id": f"benchmark-{uuid.uuid4()}",
            "metadata": {"benchmark": True},
        }
        async with http.post(
            f"{http_url}/sessions", json=session_payload
        ) as resp:
            if resp.status != 201:
                body = await resp.text()
                print(f"  [error] POST /sessions → {resp.status}: {body[:200]}")
                return result
            session_info = await resp.json()

        session_id  = session_info["session_id"]
        ws_url_rest = session_info["ws_url"]

        # The ws_url from the server is relative to the service host.
        # Replace the scheme/host with the configured base URL if needed.
        ws_url = ws_url_rest.replace("ws://localhost:7000", base_url.replace("http://", "ws://"))
        if ws_url.startswith("ws://localhost:7000"):
            ws_url = ws_url  # keep as-is if running inside the container

        # ── 2. Open WebSocket + stream audio ──────────────────────────────
        import websockets  # type: ignore[import]

        ws_connect_url = ws_url
        t_open = time.perf_counter()

        try:
            async with websockets.connect(ws_connect_url, open_timeout=10) as ws:
                t_ws_open = time.perf_counter()

                # Send audio in 20 ms chunks, then close send direction
                async def _send_audio() -> None:
                    for offset in range(0, len(audio_pcm), _CHUNK_BYTES):
                        chunk = audio_pcm[offset : offset + _CHUNK_BYTES]
                        await ws.send(chunk)
                        await asyncio.sleep(_CHUNK_MS / 1000)

                send_task = asyncio.create_task(_send_audio())

                stt_done    = False
                llm_ttft_done = False
                tts_done    = False
                first_audio_t: float | None = None

                async for msg in ws:
                    now = time.perf_counter()

                    if isinstance(msg, bytes) and not tts_done:
                        # First binary message = first TTS audio chunk
                        first_audio_t = now
                        result.tts_ttfb_ms = round((now - t_ws_open) * 1000, 1)
                        tts_done = True

                    elif isinstance(msg, str):
                        try:
                            ev = json.loads(msg)
                        except json.JSONDecodeError:
                            continue

                        event = ev.get("event", "")

                        if event == "transcript" and not stt_done:
                            result.stt_ms = round((now - t_ws_open) * 1000, 1)
                            stt_done = True

                        elif event == "llm_chunk" and not llm_ttft_done:
                            result.llm_ttft_ms = round((now - t_ws_open) * 1000, 1)
                            llm_ttft_done = True

                        elif event == "end":
                            break

                        elif event == "busy":
                            print("  [skip] Server at capacity — skipping run")
                            return result

                    # Stop waiting once we have all key measurements
                    if tts_done and stt_done and llm_ttft_done:
                        break

                await send_task

        except Exception as exc:
            print(f"  [error] WS error: {exc}")

        finally:
            # ── 3. End session ────────────────────────────────────────────
            try:
                async with http.delete(f"{http_url}/sessions/{session_id}") as r:
                    pass  # best-effort
            except Exception:
                pass

        t_end = time.perf_counter()
        result.total_ms = round((t_end - t_open) * 1000, 1)
        if t_ws_open and tts_done:
            result.e2e_ms = result.tts_ttfb_ms  # WS open → first audio

    _print_run(result)
    return result


def _print_run(r: RunResult) -> None:
    def _fmt(v: float | None) -> str:
        return f"{v:>6.0f} ms" if v is not None else "     N/A"

    print(f"    STT latency        : {_fmt(r.stt_ms)}")
    print(f"    LLM TTFT           : {_fmt(r.llm_ttft_ms)}")
    print(f"    TTS first audio    : {_fmt(r.tts_ttfb_ms)}")
    print(f"    E2E (WS open→audio): {_fmt(r.e2e_ms)}")
    print(f"    Total session      : {_fmt(r.total_ms)}")


# ── Aggregation + summary ─────────────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, int(len(s) * pct / 100) - 1)
    return s[idx]


def _print_summary(results: list[RunResult]) -> int:
    sst   = [r.stt_ms    for r in results if r.stt_ms    is not None]
    llm   = [r.llm_ttft_ms for r in results if r.llm_ttft_ms is not None]
    tts   = [r.tts_ttfb_ms for r in results if r.tts_ttfb_ms is not None]
    e2e   = [r.e2e_ms    for r in results if r.e2e_ms    is not None]

    def _avg(vals: list[float]) -> str:
        return f"{sum(vals)/len(vals):>6.0f} ms" if vals else "     N/A"

    p95 = _percentile(e2e, 95) if e2e else None

    n = len(results)
    print(f"\n  {'─' * 11} Summary ({n} run{'s' if n != 1 else ''}) {'─' * 11}")
    print(f"    avg STT            : {_avg(sst)}")
    print(f"    avg LLM TTFT       : {_avg(llm)}")
    print(f"    avg TTS TTFB       : {_avg(tts)}")
    print(f"    avg E2E            : {_avg(e2e)}")
    if p95 is not None:
        print(f"    p95 E2E            : {p95:>6.0f} ms")

    avg_e2e = sum(e2e) / len(e2e) if e2e else None
    if avg_e2e is not None:
        ok = avg_e2e < _E2E_LIMIT_MS
        status = "PASS" if ok else "FAIL"
        icon   = "✓" if ok else "✗"
        print(
            f"\n  {icon} E2E latency {'<' if ok else '>='} {_E2E_LIMIT_MS} ms"
            f"  [{status}]  (avg: {avg_e2e:.0f} ms)"
        )
        return 0 if ok else 1

    print("\n  ? Could not determine E2E latency (no successful runs?)")
    return 1


# ── CLI entrypoint ────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pipeline benchmark — Day 8")
    p.add_argument(
        "--wav", default="scripts/test_data/hello_how_are_you.wav",
        help="Path to 16-bit PCM WAV at 16 kHz mono (default: test_data/hello_how_are_you.wav)",
    )
    p.add_argument(
        "--url", default=os.getenv("PIPELINE_URL", "http://localhost:7000"),
        help="Pipeline service base URL (default: http://localhost:7000)",
    )
    p.add_argument(
        "--runs", type=int, default=3,
        help="Number of benchmark iterations (default: 3)",
    )
    return p.parse_args()


async def _main() -> int:
    args    = _parse_args()
    wav_pcm = _load_wav(args.wav)
    if wav_pcm is None:
        print(f"  Using synthetic 2-second sine tone (440 Hz) as test audio")
        wav_pcm = _generate_sine(duration_s=2.0)
    else:
        print(f"  Loaded WAV: {args.wav!r}"
              f" ({len(wav_pcm) // (_SAMPLE_RATE * 2):.1f} s)")

    print(f"\n{'='*50}")
    print(f"  Pipeline Benchmark  — target: E2E < {_E2E_LIMIT_MS} ms")
    print(f"  Service : {args.url}")
    print(f"  Runs    : {args.runs}")
    print(f"{'='*50}")

    results: list[RunResult] = []
    for i in range(args.runs):
        r = await run_single(args.url, wav_pcm, i, args.runs)
        results.append(r)
        if i < args.runs - 1:
            await asyncio.sleep(1.0)  # brief pause between runs

    return _print_summary(results)


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
