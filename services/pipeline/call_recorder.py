"""
Call recorder for the Pipeline Service.

``CallRecorder`` captures inbound and outbound int16 PCM audio during a
pipeline session, mixes them to a single stereo WAV file (left=inbound,
right=outbound), and uploads the result to MinIO / S3 when the session ends.

Storage layout
--------------
  Bucket : ``call-recordings``  (auto-created if missing)
  Key    : ``{organization_id}/{YYYY-MM-DD}/{call_id}/{session_id}.wav``

Crash-safety design
--------------------
Audio is written incrementally to local temp files as it arrives (bounded
memory), and — on top of that — a background task periodically uploads the
audio accumulated since the last flush to MinIO as an S3 **multipart
upload** part, so a mid-call crash only loses the last ``flush_interval``
seconds of audio instead of the entire call, PROVIDED the recovery helper
below is actually run after the crash (nothing in this process does that
automatically — see "What this does NOT give you" below).

How the WAV-header problem is solved
    A playable WAV needs a 44-byte header that encodes the *total* data
    size up front, but multipart parts must be uploaded before the total
    size is known.  S3 multipart parts are concatenated by **part number**,
    not by upload order, so this reserves **part number 1** for the WAV
    header and uploads it *last*, from ``finish()``, once the true total
    PCM length is known. Parts 2..N, uploaded periodically during the call,
    are raw interleaved stereo PCM with no header at all. The final object
    is only a valid WAV once ``complete_multipart_upload`` stitches part 1
    (header) in front of parts 2..N — exactly the "upload raw PCM during
    the call, mux the header in the final pass" approach.

Part sizing
    S3 requires every part except the last to be >= 5 MiB. Flushed PCM is
    accumulated in an in-memory ``_part_buffer`` across flush intervals and
    only actually ``upload_part``'d once it crosses ``RECORDING_MIN_PART_BYTES``
    (default 5 MiB). The true final part (whatever remains buffered when
    ``finish()`` runs) is uploaded regardless of size, since S3 allows the
    last part to be smaller.

Channel mixing during periodic flushes
    Each flush interleaves only the NEW inbound/outbound bytes written
    since the previous flush (byte-offset tracked per channel), zero-padding
    whichever channel got fewer bytes in that interval — the same tolerance
    ``_interleave`` already applies to the whole call in the single-shot
    path. This is simpler than deferring all interleaving to ``finish()``
    (which would mean buffering raw per-channel PCM for the whole call again,
    defeating the point), at the cost of possible minor stereo drift at
    interval boundaries if one channel is bursty. Acceptable trade-off: the
    existing single-shot padding already accepts the same kind of
    imprecision at a coarser granularity.

Crash-recovery guarantee — precisely
    * Every successful ``upload_part`` call appends to a JSON "sidecar"
      file on local disk (``<inbound temp path>.mpu.json``) recording the
      multipart ``UploadId``, bucket/key, and the list of completed parts
      (part number, ETag, and byte length of each part).
    * If the process is killed/crashes mid-call, that sidecar survives on
      disk (as long as the disk itself survives — this is a single-process
      local-disk mechanism, not a distributed one).
    * Nothing in this module runs automatically on process startup to
      consume that sidecar. ``recover_sidecar_upload()`` is provided as a
      building block a startup/ops script COULD call to complete the
      multipart upload using exactly the parts that made it to MinIO before
      the crash, synthesizing a correct WAV header for that (truncated)
      total from the recorded part lengths. Until something calls it, a
      crash still leaves an **incomplete** multipart upload in MinIO —
      which is not downloadable as a playable file via the plain S3 API,
      and should be cleaned up by an S3/MinIO lifecycle rule that aborts
      incomplete multipart uploads after N days.
    * Even when recovered, audio written after the last successful flush
      (up to ``RECORDING_FLUSH_INTERVAL_SECONDS``, default 30s) is lost —
      it only ever existed in the OS temp file / in-memory part buffer,
      both of which disappear with the process.
    * If MinIO is unreachable for the whole call, periodic flushes keep
      failing and their data is kept buffered in memory for retry on the
      next interval — under a *sustained* outage this buffer grows for the
      rest of the call (the original unbounded-memory problem reappears in
      miniature, scoped to the outage window). This is a known, accepted
      limitation rather than something this change attempts to solve with
      backoff/circuit-breaking, which would be over-engineering for a
      single pipeline process.

Usage
-----
::

    recorder = CallRecorder(session_id, call_id, organization_id)
    await recorder.start()
    recorder.write_inbound(pcm_bytes)   # called by processors
    recorder.write_outbound(pcm_bytes)  # called by processors
    await recorder.finish()             # uploads WAV, closes, and removes temp files

Environment variables
---------------------
``MINIO_ENDPOINT`` : ``http://minio:9100``
``MINIO_ACCESS_KEY``
``MINIO_SECRET_KEY``
``MINIO_BUCKET``   : ``call-recordings``
``RECORDING_ENABLED`` : ``1`` (set to ``0`` to disable upload entirely, including
    the periodic flush task — no background task is started when disabled)
``RECORDING_FLUSH_INTERVAL_SECONDS`` : ``30`` (how often the background task
    flushes newly-written audio to MinIO as a multipart part)
``RECORDING_MIN_PART_BYTES`` : ``5242880`` (5 MiB — S3's own per-part minimum;
    only overridden in tests, never lower this in production against a real
    S3/MinIO endpoint or intermediate ``upload_part`` calls will fail)
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import struct
import tempfile
import wave
from datetime import datetime, timezone
from typing import Any

import aioboto3
import structlog

log: structlog.BoundLogger = structlog.get_logger(__name__)

_SAMPLE_RATE = 16_000
_CHANNELS = 2          # stereo: left=inbound, right=outbound
_SAMPLE_WIDTH = 2      # int16 → 2 bytes
_BUCKET = os.getenv("MINIO_BUCKET", "call-recordings")
_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9100")
_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
_ENABLED = os.getenv("RECORDING_ENABLED", "1") == "1"
_FLUSH_INTERVAL_SECONDS = float(os.getenv("RECORDING_FLUSH_INTERVAL_SECONDS", "30"))
_MIN_PART_BYTES = int(os.getenv("RECORDING_MIN_PART_BYTES", str(5 * 1024 * 1024)))

_HEADER_PART_NUMBER = 1          # reserved — always the WAV header, uploaded last
_FIRST_DATA_PART_NUMBER = 2      # periodic flush parts start here


def _interleave(left: bytes, right: bytes) -> bytes:
    """
    Interleave two mono int16 PCM buffers into one stereo stream.

    If one buffer is shorter, it is zero-padded to match the other.
    """
    # Pad to equal length (in samples)
    n_left = len(left) // 2
    n_right = len(right) // 2
    n = max(n_left, n_right)
    left += bytes(2 * (n - n_left))
    right += bytes(2 * (n - n_right))

    left_samples = struct.unpack_from(f"<{n}h", left)
    right_samples = struct.unpack_from(f"<{n}h", right)

    interleaved = bytearray(4 * n)
    for i, (l, r) in enumerate(zip(left_samples, right_samples)):
        struct.pack_into("<hh", interleaved, i * 4, l, r)
    return bytes(interleaved)


def _build_wav(stereo_pcm: bytes) -> bytes:
    """Wrap raw stereo int16 PCM in a WAV container and return the bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(stereo_pcm)
    return buf.getvalue()


def _wav_header(data_len: int) -> bytes:
    """
    Build a standalone 44-byte canonical PCM WAV header for ``data_len``
    bytes of stereo int16 PCM data that will follow it.

    This is the same 44-byte layout ``wave.open(...).writeframes()`` produces
    for simple PCM (RIFF/WAVE + fmt chunk + data chunk header), but built by
    hand because in the multipart-upload path the data itself is never held
    in memory all at once — only its final total length is known, at the
    point this header is uploaded as part 1.
    """
    byte_rate = _SAMPLE_RATE * _CHANNELS * _SAMPLE_WIDTH
    block_align = _CHANNELS * _SAMPLE_WIDTH
    return (
        b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVE"
        + b"fmt " + struct.pack(
            "<IHHIIHH", 16, 1, _CHANNELS, _SAMPLE_RATE, byte_rate,
            block_align, _SAMPLE_WIDTH * 8,
        )
        + b"data" + struct.pack("<I", data_len)
    )


def _read_new_bytes(path: str, offset: int) -> tuple[bytes, int]:
    """
    Read whatever has been appended to *path* since *offset*.

    Returns ``(new_bytes, new_offset)``. A trailing odd byte (half of an
    int16 sample, possible if a writer handed us an odd-length chunk) is
    held back — it is not consumed, so it's picked up whole next time.
    """
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    if len(data) % 2:
        data = data[:-1]
    return data, offset + len(data)


class CallRecorder:
    """
    Buffers audio for one session and uploads a stereo WAV to MinIO.

    In addition to the final upload in ``finish()``, a background task
    (started in ``start()``) periodically flushes newly-recorded audio to
    MinIO via S3 multipart upload — see the module docstring's
    "Crash-recovery guarantee" section for exactly what protection this
    does and does not provide.

    Parameters
    ----------
    session_id:
        UUID string for this pipeline session.
    call_id:
        Caller-supplied call identifier (used in the S3 key).
    organization_id:
        Tenant / org id (used as the first path segment in the S3 key).
    """

    def __init__(
        self,
        session_id: str,
        call_id: str,
        organization_id: str,
    ) -> None:
        self.session_id = session_id
        self.call_id = call_id
        self.organization_id = organization_id

        # Audio is spooled to temp files instead of growing in-memory lists
        # for the whole call.
        self._inbound_fh = tempfile.NamedTemporaryFile(
            prefix=f"callrec_{session_id}_in_", suffix=".pcm", delete=False
        )
        self._outbound_fh = tempfile.NamedTemporaryFile(
            prefix=f"callrec_{session_id}_out_", suffix=".pcm", delete=False
        )
        self._inbound_path = self._inbound_fh.name
        self._outbound_path = self._outbound_fh.name
        self._sidecar_path = self._inbound_path + ".mpu.json"
        self._has_audio = False
        self._started = False
        self._finished = False

        # Fixed for the life of the call, computed once so periodic flushes
        # and the final completion always agree on the destination key.
        self._key = self._s3_key()

        # Periodic-flush state.
        self._flush_task: asyncio.Task | None = None
        self._inbound_offset = 0
        self._outbound_offset = 0
        self._part_buffer = bytearray()
        self._part_number = _FIRST_DATA_PART_NUMBER
        self._completed_parts: list[dict[str, Any]] = []
        self._upload_id: str | None = None
        self._bucket_ready = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Mark recorder as active and start the periodic flush task."""
        self._started = True
        if _ENABLED:
            self._flush_task = asyncio.create_task(self._flush_loop())
        log.debug("call_recorder_started", session_id=self.session_id)

    async def finish(self) -> str | None:
        """
        Stop the flush task, finalize the upload, and return the S3 key.

        Returns ``None`` if recording is disabled or the session had no
        audio. The temp spool files are always removed before returning,
        whether the upload succeeds or fails. Idempotent — a second call
        is a no-op.
        """
        if self._finished:
            return None
        self._finished = True

        await self._stop_flush_task()

        try:
            # Catch up anything written since the last periodic flush while
            # the file handles are still open (flush() on a closed file
            # raises), then close them.
            if self._upload_id is not None:
                self._accumulate_new_audio()
            self._inbound_fh.close()
            self._outbound_fh.close()

            if not _ENABLED:
                log.debug("call_recorder_disabled", session_id=self.session_id)
                return None

            if not self._has_audio:
                log.debug("call_recorder_no_audio", session_id=self.session_id)
                return None

            key = self._key
            try:
                if self._upload_id is None:
                    # No periodic flush ever triggered (short call) — simple
                    # single-shot path, same as before this change.
                    await self._upload_whole_file(key)
                else:
                    await self._finalize_multipart(key)
                log.info("call_recorder_uploaded", session_id=self.session_id, key=key)
                return key
            except Exception as exc:
                log.error(
                    "call_recorder_upload_failed",
                    session_id=self.session_id,
                    key=key,
                    error=str(exc),
                    exc_info=True,
                )
                await self._best_effort_abort()
                return None
        finally:
            self._cleanup_temp_files()

    # ------------------------------------------------------------------
    # Audio ingestion (synchronous — called from frame processors)
    # ------------------------------------------------------------------

    def write_inbound(self, pcm: bytes) -> None:
        """Append raw int16 PCM bytes from the client (inbound audio)."""
        if self._started and not self._finished:
            self._inbound_fh.write(pcm)
            self._has_audio = True

    def write_outbound(self, pcm: bytes) -> None:
        """Append raw int16 PCM bytes sent to the client (TTS output)."""
        if self._started and not self._finished:
            self._outbound_fh.write(pcm)
            self._has_audio = True

    # ------------------------------------------------------------------
    # Periodic flush (background task — never called from the hot path)
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_FLUSH_INTERVAL_SECONDS)
                await self._flush_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error(
                "call_recorder_flush_loop_crashed",
                session_id=self.session_id,
                exc_info=True,
            )

    async def _stop_flush_task(self) -> None:
        if self._flush_task is None:
            return
        self._flush_task.cancel()
        try:
            await self._flush_task
        except asyncio.CancelledError:
            pass
        except Exception:
            log.error(
                "call_recorder_flush_task_error",
                session_id=self.session_id,
                exc_info=True,
            )
        self._flush_task = None

    async def _flush_once(self) -> None:
        """Interleave newly-written audio and upload a part once >= min size."""
        self._accumulate_new_audio()
        if len(self._part_buffer) >= _MIN_PART_BYTES:
            await self._upload_buffered_part()

    def _accumulate_new_audio(self) -> None:
        # write_inbound/write_outbound write through buffered file objects;
        # flush (not close) them here — from the background task, never
        # from the hot-path write_* calls — so the bytes just written are
        # actually visible to the separate `open()` + read below.
        self._inbound_fh.flush()
        self._outbound_fh.flush()
        in_new, self._inbound_offset = _read_new_bytes(self._inbound_path, self._inbound_offset)
        out_new, self._outbound_offset = _read_new_bytes(self._outbound_path, self._outbound_offset)
        if not in_new and not out_new:
            return
        chunk = _interleave(in_new, out_new)
        self._part_buffer.extend(chunk)

    async def _upload_buffered_part(self) -> None:
        """Upload whatever is currently buffered as one multipart part."""
        if not self._part_buffer:
            return
        data = bytes(self._part_buffer)
        part_number = self._part_number
        try:
            async with self._client() as s3:
                await self._ensure_bucket(s3)
                await self._ensure_multipart_started(s3)
                resp = await s3.upload_part(
                    Bucket=_BUCKET,
                    Key=self._key,
                    PartNumber=part_number,
                    UploadId=self._upload_id,
                    Body=data,
                )
            self._part_buffer.clear()
            self._part_number += 1
            self._completed_parts.append(
                {"PartNumber": part_number, "ETag": resp["ETag"], "Length": len(data)}
            )
            self._persist_sidecar()
        except Exception as exc:
            # Leave the buffer intact so the data is retried on the next
            # flush instead of being lost — see the module docstring's note
            # on sustained-outage behavior for the resulting trade-off.
            log.error(
                "call_recorder_part_upload_failed",
                session_id=self.session_id,
                part_number=part_number,
                error=str(exc),
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Final upload paths
    # ------------------------------------------------------------------

    async def _upload_whole_file(self, key: str) -> None:
        with open(self._inbound_path, "rb") as f:
            inbound_pcm = f.read()
        with open(self._outbound_path, "rb") as f:
            outbound_pcm = f.read()
        stereo = _interleave(inbound_pcm, outbound_pcm)
        wav_bytes = _build_wav(stereo)
        async with self._client() as s3:
            await self._ensure_bucket(s3)
            await s3.put_object(
                Bucket=_BUCKET, Key=key, Body=wav_bytes, ContentType="audio/wav",
            )

    async def _finalize_multipart(self, key: str) -> None:
        # Any audio written since the last periodic flush was already
        # caught up (while the spool files were still open) in finish();
        # upload whatever is buffered as the final part — allowed to be
        # smaller than the 5 MiB minimum since it's the last part.
        await self._upload_buffered_part()

        total_pcm_bytes = sum(p["Length"] for p in self._completed_parts)
        header = _wav_header(total_pcm_bytes)

        async with self._client() as s3:
            resp = await s3.upload_part(
                Bucket=_BUCKET,
                Key=key,
                PartNumber=_HEADER_PART_NUMBER,
                UploadId=self._upload_id,
                Body=header,
            )
            self._completed_parts.append(
                {"PartNumber": _HEADER_PART_NUMBER, "ETag": resp["ETag"], "Length": len(header)}
            )
            parts = sorted(
                (
                    {"PartNumber": p["PartNumber"], "ETag": p["ETag"]}
                    for p in self._completed_parts
                ),
                key=lambda p: p["PartNumber"],
            )
            await s3.complete_multipart_upload(
                Bucket=_BUCKET,
                Key=key,
                UploadId=self._upload_id,
                MultipartUpload={"Parts": parts},
            )
        self._remove_sidecar()

    async def _best_effort_abort(self) -> None:
        """If a multipart upload was in progress, try to abort it — never raises."""
        if self._upload_id is None:
            return
        try:
            async with self._client() as s3:
                await s3.abort_multipart_upload(
                    Bucket=_BUCKET, Key=self._key, UploadId=self._upload_id,
                )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _cleanup_temp_files(self) -> None:
        """Best-effort removal of the spool + sidecar files — never raises."""
        for path in (self._inbound_path, self._outbound_path):
            try:
                os.remove(path)
            except OSError:
                pass
        self._remove_sidecar()

    def _remove_sidecar(self) -> None:
        try:
            os.remove(self._sidecar_path)
        except OSError:
            pass

    def _persist_sidecar(self) -> None:
        """
        Best-effort crash-survivable record of the in-progress multipart
        upload. Not read by anything automatically — see
        ``recover_sidecar_upload()`` and the module docstring.
        """
        try:
            payload = {
                "bucket": _BUCKET,
                "key": self._key,
                "upload_id": self._upload_id,
                "parts": self._completed_parts,
            }
            tmp_path = self._sidecar_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_path, self._sidecar_path)
        except OSError:
            pass

    def _s3_key(self) -> str:
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return (
            f"{self.organization_id}/{date_str}"
            f"/{self.call_id}/{self.session_id}.wav"
        )

    def _client(self):
        session = aioboto3.Session()
        return session.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
        )

    async def _ensure_bucket(self, s3: Any) -> None:
        if self._bucket_ready:
            return
        try:
            await s3.head_bucket(Bucket=_BUCKET)
        except Exception:
            await s3.create_bucket(Bucket=_BUCKET)
        self._bucket_ready = True

    async def _ensure_multipart_started(self, s3: Any) -> None:
        if self._upload_id is not None:
            return
        resp = await s3.create_multipart_upload(
            Bucket=_BUCKET, Key=self._key, ContentType="audio/wav",
        )
        self._upload_id = resp["UploadId"]
        self._persist_sidecar()


# ----------------------------------------------------------------------
# Crash recovery (not invoked automatically by anything in this module —
# see "Crash-recovery guarantee" in the module docstring)
# ----------------------------------------------------------------------

async def recover_sidecar_upload(sidecar_path: str) -> str | None:
    """
    Complete a multipart upload left behind by a crashed ``CallRecorder``,
    using only the sidecar JSON file it was writing on disk.

    Synthesizes a WAV header from the recorded part lengths (the true total
    is simply the sum of all recorded data-part lengths, since no more data
    is coming once the process has crashed), uploads it as part 1, and
    completes the multipart upload. The recovered file is valid and playable
    but truncated at the last successfully-flushed part — anything written
    after that is unrecoverable, as described in the module docstring.

    Returns the S3 key on success, or ``None`` if the sidecar is missing,
    unreadable, or has no completed parts to recover.
    """
    try:
        with open(sidecar_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    bucket = payload.get("bucket")
    key = payload.get("key")
    upload_id = payload.get("upload_id")
    parts = payload.get("parts") or []
    if not bucket or not key or not upload_id or not parts:
        return None

    total_pcm_bytes = sum(p["Length"] for p in parts)
    header = _wav_header(total_pcm_bytes)

    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
    ) as s3:
        resp = await s3.upload_part(
            Bucket=bucket, Key=key, PartNumber=_HEADER_PART_NUMBER,
            UploadId=upload_id, Body=header,
        )
        all_parts = sorted(
            [{"PartNumber": _HEADER_PART_NUMBER, "ETag": resp["ETag"]}]
            + [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in parts],
            key=lambda p: p["PartNumber"],
        )
        await s3.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": all_parts},
        )
    try:
        os.remove(sidecar_path)
    except OSError:
        pass
    return key
