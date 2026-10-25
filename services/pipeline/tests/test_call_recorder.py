"""
Unit tests for CallRecorder — periodic multipart-flush crash-safety pass.

All MinIO/S3 interaction is mocked via ``aioboto3.Session`` (no real
Docker/MinIO endpoint is available in this environment, or required).

Deliverables verified
----------------------
  ✓  RECORDING_ENABLED=0 — no background flush task is started at all
  ✓  periodic flush — create_multipart_upload + upload_part called once the
     buffered audio crosses the configured minimum part size
  ✓  finish() — completes the multipart upload (header part + data parts)
     and returns the S3 key
  ✓  finish() — short call that never triggered a periodic flush falls back
     to the single-shot put_object path and still returns the correct key
  ✓  finish() — flush task is cancelled cleanly, no dangling/unawaited task
  ✓  finish() — idempotent (second call is a no-op, returns None)
  ✓  finish() — returns None and cleans up temp files when disabled / no audio
  ✓  recover_sidecar_upload() — completes an upload from the sidecar alone
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import call_recorder as cr


# ── S3 mock helpers ─────────────────────────────────────────────────────────

def _make_mock_s3(upload_id: str = "upload-1") -> MagicMock:
    s3 = MagicMock()
    s3.head_bucket = AsyncMock(return_value={})
    s3.create_bucket = AsyncMock(return_value={})
    s3.create_multipart_upload = AsyncMock(return_value={"UploadId": upload_id})
    s3.upload_part = AsyncMock(
        side_effect=lambda **kw: {"ETag": f"etag-{kw['PartNumber']}"}
    )
    s3.complete_multipart_upload = AsyncMock(return_value={})
    s3.abort_multipart_upload = AsyncMock(return_value={})
    s3.put_object = AsyncMock(return_value={})
    return s3


def _patch_aioboto3(monkeypatch, s3: MagicMock) -> MagicMock:
    """Patch call_recorder.aioboto3.Session so every `.client(...)` call
    yields the same mock s3 object as an async context manager."""

    @asynccontextmanager
    async def _client_cm(*args, **kwargs):
        yield s3

    session_instance = MagicMock()
    session_instance.client = MagicMock(side_effect=lambda *a, **k: _client_cm())
    session_class = MagicMock(return_value=session_instance)
    monkeypatch.setattr(cr.aioboto3, "Session", session_class)
    return session_class


def _pcm(n_samples: int, value: int = 100) -> bytes:
    return struct.pack(f"<{n_samples}h", *([value] * n_samples))


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fast_flush_and_small_parts(monkeypatch):
    """Keep tests fast: short flush interval, tiny part-size threshold."""
    monkeypatch.setattr(cr, "_FLUSH_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(cr, "_MIN_PART_BYTES", 16)  # bytes, not MiB, for tests
    monkeypatch.setattr(cr, "_ENABLED", True)
    yield


# ── RECORDING_ENABLED=0 ─────────────────────────────────────────────────────

class TestDisabled:
    async def test_no_flush_task_started_when_disabled(self, monkeypatch):
        monkeypatch.setattr(cr, "_ENABLED", False)
        rec = cr.CallRecorder("s1", "c1", "org1")
        await rec.start()
        assert rec._flush_task is None

        rec.write_inbound(_pcm(10))
        result = await rec.finish()
        assert result is None
        assert not os.path.exists(rec._inbound_path)
        assert not os.path.exists(rec._outbound_path)


# ── Periodic flush ──────────────────────────────────────────────────────────

class TestPeriodicFlush:
    async def test_flush_triggers_create_and_upload_part(self, monkeypatch):
        s3 = _make_mock_s3()
        _patch_aioboto3(monkeypatch, s3)

        rec = cr.CallRecorder("s2", "c2", "org1")
        await rec.start()
        assert rec._flush_task is not None

        # Enough bytes to cross the (patched, tiny) 16-byte minimum part size.
        rec.write_inbound(_pcm(20, 111))
        rec.write_outbound(_pcm(20, 222))

        # Give the background flush loop a few ticks.
        for _ in range(10):
            await asyncio.sleep(0.05)
            if s3.upload_part.await_count:
                break

        assert s3.create_multipart_upload.await_count == 1
        assert s3.upload_part.await_count >= 1
        first_call_kwargs = s3.upload_part.await_args_list[0].kwargs
        assert first_call_kwargs["PartNumber"] == cr._FIRST_DATA_PART_NUMBER
        assert first_call_kwargs["UploadId"] == "upload-1"

        key = await rec.finish()
        assert key == rec._key
        assert s3.complete_multipart_upload.await_count == 1
        # header (part 1) + at least one data part were completed
        completed_parts = s3.complete_multipart_upload.await_args.kwargs["MultipartUpload"]["Parts"]
        part_numbers = sorted(p["PartNumber"] for p in completed_parts)
        assert part_numbers[0] == cr._HEADER_PART_NUMBER

    async def test_flush_task_cancelled_cleanly_on_finish(self, monkeypatch):
        s3 = _make_mock_s3()
        _patch_aioboto3(monkeypatch, s3)

        rec = cr.CallRecorder("s3", "c3", "org1")
        await rec.start()
        task = rec._flush_task
        rec.write_inbound(_pcm(5))

        await rec.finish()

        assert rec._flush_task is None
        assert task.cancelled() or task.done()
        # Draining the event loop once more must not raise / warn.
        await asyncio.sleep(0)


# ── finish() contract ───────────────────────────────────────────────────────

class TestFinishContract:
    async def test_short_call_falls_back_to_put_object(self, monkeypatch):
        """Call ends before any periodic flush fires — single-shot path."""
        s3 = _make_mock_s3()
        _patch_aioboto3(monkeypatch, s3)
        # Make the flush interval long so it never fires during the test.
        monkeypatch.setattr(cr, "_FLUSH_INTERVAL_SECONDS", 999)

        rec = cr.CallRecorder("s4", "c4", "org1")
        await rec.start()
        rec.write_inbound(_pcm(8, 50))
        rec.write_outbound(_pcm(8, 60))

        key = await rec.finish()
        assert key == rec._key
        assert s3.put_object.await_count == 1
        assert s3.create_multipart_upload.await_count == 0
        body = s3.put_object.await_args.kwargs["Body"]
        assert body.startswith(b"RIFF")

    async def test_idempotent_second_finish_is_noop(self, monkeypatch):
        s3 = _make_mock_s3()
        _patch_aioboto3(monkeypatch, s3)
        monkeypatch.setattr(cr, "_FLUSH_INTERVAL_SECONDS", 999)

        rec = cr.CallRecorder("s5", "c5", "org1")
        await rec.start()
        rec.write_inbound(_pcm(4))
        first = await rec.finish()
        second = await rec.finish()

        assert first == rec._key
        assert second is None
        assert s3.put_object.await_count == 1  # not called twice

    async def test_no_audio_returns_none_and_cleans_up(self, monkeypatch):
        s3 = _make_mock_s3()
        _patch_aioboto3(monkeypatch, s3)

        rec = cr.CallRecorder("s6", "c6", "org1")
        await rec.start()
        result = await rec.finish()

        assert result is None
        assert s3.put_object.await_count == 0
        assert not os.path.exists(rec._inbound_path)
        assert not os.path.exists(rec._outbound_path)


# ── Sidecar crash recovery ──────────────────────────────────────────────────

class TestSidecarRecovery:
    async def test_sidecar_written_and_recoverable(self, monkeypatch):
        s3 = _make_mock_s3()
        _patch_aioboto3(monkeypatch, s3)

        rec = cr.CallRecorder("s7", "c7", "org1")
        await rec.start()
        rec.write_inbound(_pcm(20, 1))
        rec.write_outbound(_pcm(20, 2))

        for _ in range(10):
            await asyncio.sleep(0.05)
            if s3.upload_part.await_count:
                break
        assert s3.upload_part.await_count >= 1

        # Sidecar must exist with the in-progress upload recorded, and the
        # recorder must not yet have completed the upload.
        assert os.path.exists(rec._sidecar_path)
        with open(rec._sidecar_path) as f:
            payload = json.load(f)
        assert payload["upload_id"] == "upload-1"
        assert payload["parts"]
        sidecar_path = rec._sidecar_path

        # Simulate a crash: cancel the flush task directly without calling
        # finish(), so the multipart upload is left incomplete.
        rec._flush_task.cancel()
        try:
            await rec._flush_task
        except asyncio.CancelledError:
            pass

        key = await cr.recover_sidecar_upload(sidecar_path)
        assert key == rec._key
        assert s3.complete_multipart_upload.await_count == 1
        assert not os.path.exists(sidecar_path)

        # Clean up the real temp files ourselves since we bypassed finish().
        for p in (rec._inbound_path, rec._outbound_path):
            try:
                os.remove(p)
            except OSError:
                pass

    async def test_recover_missing_sidecar_returns_none(self, tmp_path):
        missing = tmp_path / "does_not_exist.mpu.json"
        result = await cr.recover_sidecar_upload(str(missing))
        assert result is None
