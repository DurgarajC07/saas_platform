#!/usr/bin/env python3
"""
Day 14 smoke test — Twilio PSTN Transport + IVR DTMF Routing.

Validates Day 14 deliverables.  Pipeline-service checks are done via
source-file analysis (no pipecat import needed in the saas_platform venv);
saas_platform checks use real imports.

  1.  Config — new Twilio / public-host fields present on Settings
  2.  Pipeline transport — twilio.py source structure (classes, methods)
  3.  Pipeline transport — codec helpers defined in source
  4.  DTMFRouter — dtmf.py source structure (classes, methods)
  5.  Pipeline builder — build_for_twilio method in source
  6.  Session manager  — run_twilio_stream method in source
  7.  Pipeline server  — /sessions/{id}/twilio_stream endpoint registered
  8.  SaaS schemas     — OutboundCallRequest / OutboundCallResponse importable
  9.  SaaS service     — TwilioCallService importable and has required methods
 10.  SaaS router      — outbound + webhook endpoints present in router
 11.  TwiML generation — _twiml_stream produces valid XML with <Stream> element
 12.  FreeSWITCH migration path — twilio.py documents migration strategy
 13.  requirements.txt — twilio and audioop-lts entries present
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

SAAS_ROOT     = Path(__file__).parent.parent
PIPELINE_ROOT = SAAS_ROOT / "services" / "pipeline"
sys.path.insert(0, str(SAAS_ROOT))

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
ok = errors = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok, errors
    sym = PASS if cond else FAIL
    print(f"  {sym}  {label}" + (f"  ({detail})" if detail else ""))
    if cond:
        ok += 1
    else:
        errors += 1


def section(title: str) -> None:
    print(f"\n── {title} {'─' * max(2, 60 - len(title))}")


def read_source(rel: str) -> str:
    return (PIPELINE_ROOT / rel).read_text(errors="ignore")


# ── 1  Config fields ──────────────────────────────────────────────────────────
section("1. Config — new Twilio / public-host fields")
try:
    from app.config import Settings
    s = Settings(
        SECRET_KEY="test-secret-key-32-chars-long-ok!",
        DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
    )
    for field in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                  "PUBLIC_HOST", "PUBLIC_PROTOCOL", "PIPELINE_WS_PUBLIC_URL"):
        check(f"{field} present", hasattr(s, field))
except Exception as exc:
    check("Settings import", False, str(exc))

# ── 2  Transport source structure ─────────────────────────────────────────────
section("2. Pipeline transport — twilio.py source structure")
try:
    src = read_source("transports/twilio.py")
    for name in ("class DTMFFrame", "class TransferCallFrame", "class ClearAudioFrame",
                 "class TwilioTransport", "class TwilioInputProcessor",
                 "def make_twilio_transport", "def run_reader", "def _parse_message",
                 "def input", "def output"):
        check(f"defines '{name}'", name in src)
except Exception as exc:
    check("transports/twilio.py read", False, str(exc))

# ── 3  Codec helpers ──────────────────────────────────────────────────────────
section("3. Codec helpers in twilio.py")
try:
    src = read_source("transports/twilio.py")
    check("_mulaw_to_pcm16k defined", "def _mulaw_to_pcm16k" in src)
    check("_pcm16k_to_mulaw_b64 defined", "def _pcm16k_to_mulaw_b64" in src)
    check("audioop_lts fallback import present", "audioop_lts" in src)
    check("ulaw2lin / lin2ulaw used", "ulaw2lin" in src and "lin2ulaw" in src)
except Exception as exc:
    check("codec helpers", False, str(exc))

# ── 4  DTMFRouter source ──────────────────────────────────────────────────────
section("4. DTMFRouter — processors/dtmf.py source")
try:
    src = read_source("processors/dtmf.py")
    for name in ("class DTMFRouter", "class RepeatMenuFrame", "def process_frame"):
        check(f"defines '{name}'", name in src)
    for action in ("transfer", "hangup", "repeat", "operator", "none"):
        check(f"handles action={action!r}", action in src)
    check("acts only on finished=True", "finished" in src)
except Exception as exc:
    check("processors/dtmf.py read", False, str(exc))

# ── 5  PipelineBuilder.build_for_twilio ───────────────────────────────────────
section("5. Pipeline builder — build_for_twilio")
try:
    src = read_source("pipeline_builder.py")
    check("build_for_twilio defined", "def build_for_twilio" in src)
    after = src.split("build_for_twilio", 1)[1] if "build_for_twilio" in src else ""
    check("delegates to build()", "build(" in after)
    check("splices DTMFRouter", "DTMFRouter" in src)
except Exception as exc:
    check("pipeline_builder.py read", False, str(exc))

# ── 6  SessionManager.run_twilio_stream ───────────────────────────────────────
section("6. SessionManager — run_twilio_stream")
try:
    src = read_source("session_manager.py")
    check("run_twilio_stream defined", "async def run_twilio_stream" in src)
    check("uses make_twilio_transport", "make_twilio_transport" in src)
    check("uses build_for_twilio", "build_for_twilio" in src)
    check("uses PipelineTask", "PipelineTask" in src)
except Exception as exc:
    check("session_manager.py read", False, str(exc))

# ── 7  Pipeline server WS endpoint ───────────────────────────────────────────
section("7. Pipeline server — twilio_stream WS endpoint")
try:
    src = read_source("server.py")
    check("/twilio_stream path present", "/twilio_stream" in src)
    check("@app.websocket for twilio_stream",
          "@app.websocket" in src and "twilio_stream" in src)
    check("run_twilio_stream called", "run_twilio_stream" in src)
except Exception as exc:
    check("server.py read", False, str(exc))

# ── 8  SaaS schemas ───────────────────────────────────────────────────────────
section("8. SaaS schemas — OutboundCallRequest / OutboundCallResponse")
try:
    from app.modules.agents.schemas import OutboundCallRequest, OutboundCallResponse
    check("OutboundCallRequest importable", True)
    check("OutboundCallResponse importable", True)
    req = OutboundCallRequest(to_number="+15551234567")
    check("to_number stored", req.to_number == "+15551234567")
    check("from_number defaults to None", req.from_number is None)
    check("metadata defaults to {}", req.metadata == {})
    resp = OutboundCallResponse(call_sid="CAabc", session_id="s1", from_number="+1")
    check("status defaults to 'queued'", resp.status == "queued")
except Exception as exc:
    check("SaaS schemas import", False, str(exc))

# ── 9  TwilioCallService ──────────────────────────────────────────────────────
section("9. TwilioCallService — importable + methods")
try:
    from app.modules.agents.service import TwilioCallService
    check("TwilioCallService importable", True)
    for method in ("validate_signature", "handle_inbound", "start_outbound_call",
                   "_twiml_stream", "_twiml_connect_callback", "_create_pipeline_session"):
        check(f"{method} defined", callable(getattr(TwilioCallService, method, None)))
except Exception as exc:
    check("TwilioCallService import", False, str(exc))

# ── 10  SaaS router ───────────────────────────────────────────────────────────
section("10. SaaS router — Twilio endpoint paths")
try:
    rtext = (SAAS_ROOT / "app" / "modules" / "agents" / "router.py").read_text()
    check("inbound webhook path", "/webhooks/twilio/inbound/{phone_number}" in rtext)
    check("connect callback path", "/webhooks/twilio/connect/{session_id}" in rtext)
    check("outbound call path", "/calls/outbound" in rtext)
    check("TwilioCallService imported", "TwilioCallService" in rtext)
    check("ai.pstn.enabled feature guard", "ai.pstn.enabled" in rtext)
except Exception as exc:
    check("router.py read", False, str(exc))

# ── 11  TwiML generation ──────────────────────────────────────────────────────
section("11. TwiML generation — _twiml_stream produces valid XML")
try:
    from app.modules.agents.service import TwilioCallService

    mock_settings = MagicMock()
    mock_settings.PIPELINE_WS_PUBLIC_URL = "wss://pipeline.example.com"
    mock_settings.PUBLIC_PROTOCOL = "https"
    mock_settings.PUBLIC_HOST = "api.example.com"

    with patch("app.modules.agents.service.get_settings", return_value=mock_settings):
        svc = TwilioCallService.__new__(TwilioCallService)
        svc.settings = mock_settings
        twiml_xml = svc._twiml_stream("sess-abc-123")

    check("returns string", isinstance(twiml_xml, str))
    xml_body = twiml_xml.split("\n", 1)[-1].strip()
    root = ET.fromstring(xml_body)
    check("root tag is <Response>", root.tag == "Response")
    connect = root.find("Connect")
    check("<Connect> child present", connect is not None)
    stream = connect.find("Stream") if connect is not None else None
    check("<Stream> inside <Connect>", stream is not None)
    if stream is not None:
        url = stream.get("url", "")
        check("url starts with wss://", url.startswith("wss://"))
        check("url contains session_id", "sess-abc-123" in url)
        check("url ends with /twilio_stream", url.endswith("/twilio_stream"))
except Exception as exc:
    check("TwiML generation", False, str(exc))

# ── 12  FreeSWITCH migration ──────────────────────────────────────────────────
section("12. FreeSWITCH migration path documented")
try:
    src = read_source("transports/twilio.py")
    check("FreeSWITCH mentioned in twilio.py", "freeswitch" in src.lower())
    check("_parse_message override migration strategy described",
          "_parse_message" in src and "FreeSWITCH" in src)
except Exception as exc:
    check("FreeSWITCH migration check", False, str(exc))

# ── 13  requirements.txt ──────────────────────────────────────────────────────
section("13. requirements.txt — new entries")
try:
    saas_req     = (SAAS_ROOT / "requirements.txt").read_text()
    pipeline_req = (PIPELINE_ROOT / "requirements.txt").read_text()
    check("twilio>= in saas requirements.txt", "twilio>=" in saas_req)
    check("audioop-lts in pipeline requirements.txt", "audioop-lts" in pipeline_req)
except Exception as exc:
    check("requirements.txt read", False, str(exc))

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'═' * 62}")
print(f"  Day 14 smoke test: {ok} passed, {errors} failed")
print(f"{'═' * 62}\n")
sys.exit(0 if errors == 0 else 1)
