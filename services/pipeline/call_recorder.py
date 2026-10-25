"""
Call recorder for the Pipeline Service.

``CallRecorder`` captures inbound and outbound int16 PCM audio during a
pipeline session, mixes them to a single stereo WAV file (left=inbound,
right=outbound), and uploads the result to MinIO / S3 when the session ends.

Storage layout
--------------
  Bucket : ``call-recordings``  (auto-created if missing)
  Key    : ``{organization_id}/{YYYY-MM-DD}/{call_id}/{session_id}.wav``

Crash-safety note
-----------------
Audio is written incrementally to local temp files as it arrives (bounded
memory — a long call no longer grows two Python lists for the whole call
duration), rather than buffered entirely in memory until ``finish()``.  This
survives memory pressure from very long calls.  It does **not** survive a
hard process kill / crash mid-call: the temp files live under the OS temp
directory and are only muxed into a WAV and uploaded to MinIO in
``finish()``, so a kill before that point still loses the recording (there
is no periodic MinIO sync — the pipeline service has no existing
Celery/background-flush mechanism to hook into for that). Full crash safety
would require periodic multipart-upload flushes to MinIO, which is a larger
change left as a follow-up.

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
``RECORDING_ENABLED`` : ``1`` (set to ``0`` to disable upload entirely)
"""
from __future__ import annotations

import io
import os
import struct
import tempfile
import wave
from datetime import datetime, timezone

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


class CallRecorder:
    """
    Buffers audio for one session and uploads a stereo WAV to MinIO on finish.

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
        # for the whole call — see "Crash-safety note" above for exactly
        # what this does and doesn't protect against.
        self._inbound_fh = tempfile.NamedTemporaryFile(
            prefix=f"callrec_{session_id}_in_", suffix=".pcm", delete=False
        )
        self._outbound_fh = tempfile.NamedTemporaryFile(
            prefix=f"callrec_{session_id}_out_", suffix=".pcm", delete=False
        )
        self._inbound_path = self._inbound_fh.name
        self._outbound_path = self._outbound_fh.name
        self._has_audio = False
        self._started = False
        self._finished = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Mark recorder as active.  Temp files are already open from __init__."""
        self._started = True
        log.debug("call_recorder_started", session_id=self.session_id)

    async def finish(self) -> str | None:
        """
        Mix channels, encode WAV, upload to MinIO, and return the S3 key.

        Returns ``None`` if recording is disabled or session had no audio.
        The temp spool files are always removed before returning, whether
        the upload succeeds or fails.
        """
        if self._finished:
            return None
        self._finished = True

        try:
            self._inbound_fh.close()
            self._outbound_fh.close()

            if not _ENABLED:
                log.debug("call_recorder_disabled", session_id=self.session_id)
                return None

            if not self._has_audio:
                log.debug("call_recorder_no_audio", session_id=self.session_id)
                return None

            # Muxing still requires the full call's audio in memory — that's
            # unavoidable to build a single WAV container — but it is now
            # only held briefly here, not for the whole call duration.
            with open(self._inbound_path, "rb") as f:
                inbound_pcm = f.read()
            with open(self._outbound_path, "rb") as f:
                outbound_pcm = f.read()

            stereo = _interleave(inbound_pcm, outbound_pcm)
            wav_bytes = _build_wav(stereo)

            key = self._s3_key()
            try:
                await self._upload(key, wav_bytes)
                log.info(
                    "call_recorder_uploaded",
                    session_id=self.session_id,
                    key=key,
                    size_kb=len(wav_bytes) // 1024,
                )
                return key
            except Exception as exc:
                log.error(
                    "call_recorder_upload_failed",
                    session_id=self.session_id,
                    key=key,
                    error=str(exc),
                    exc_info=True,
                )
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
    # Internals
    # ------------------------------------------------------------------

    def _cleanup_temp_files(self) -> None:
        """Best-effort removal of the spool files — never raises."""
        for path in (self._inbound_path, self._outbound_path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _s3_key(self) -> str:
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return (
            f"{self.organization_id}/{date_str}"
            f"/{self.call_id}/{self.session_id}.wav"
        )

    async def _upload(self, key: str, data: bytes) -> None:
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
        ) as s3:
            # Create bucket silently if it doesn't exist
            try:
                await s3.head_bucket(Bucket=_BUCKET)
            except Exception:
                await s3.create_bucket(Bucket=_BUCKET)

            await s3.put_object(
                Bucket=_BUCKET,
                Key=key,
                Body=data,
                ContentType="audio/wav",
            )
