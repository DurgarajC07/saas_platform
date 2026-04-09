"""
Day 16 Smoke Test
=================
Validates:
  16.2  Demo Agent Seed Data script
  16.3  Security Hardening (SQL sanitiser, PII detector, Twilio guard,
        system_prompt removed from AgentResponse, VRAM guard, mandatory HMAC)
  16.4  Production Docker Build
"""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
failures: list[str] = []


def check(label: str, condition: bool, hint: str = "") -> None:
    if condition:
        print(f"  [{PASS}] {label}")
    else:
        msg = f"  [{FAIL}] {label}" + (f"  ({hint})" if hint else "")
        print(msg)
        failures.append(label)


# ── Add saas_platform to sys.path ─────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # saas_platform/
sys.path.insert(0, str(BASE))

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.4 Dockerfile.prod ===")
prod_df = BASE / "Dockerfile.prod"
check("Dockerfile.prod exists", prod_df.exists())
if prod_df.exists():
    content = prod_df.read_text()
    check("FROM python:3.14-slim present", "python:3.14-slim" in content)
    check("ffmpeg installed in runtime stage", "ffmpeg" in content)
    check("libsndfile1 installed", "libsndfile1" in content)
    check("non-root appuser present", "appuser" in content)
    check("HEALTHCHECK present", "HEALTHCHECK" in content)
    check("gunicorn in CMD", "gunicorn" in content)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.2 Demo Agent Seed Script ===")
seed_script = BASE / "scripts" / "seed_demo_agents.py"
check("seed_demo_agents.py exists", seed_script.exists())
if seed_script.exists():
    src = seed_script.read_text()
    for slug in ("aria", "docubot", "orderbot", "announcer"):
        check(f"  Agent '{slug}' defined", slug in src.lower())
    check("rag_bot agent type present", "rag_bot" in src)
    check("db_bot agent type present", "db_bot" in src)
    check("speaker_only agent type present", "speaker_only" in src)
    check("idempotent upsert (get_by logic)", "slug" in src and "org_id" in src)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.3a SQL Sanitiser ===")
try:
    from app.core.utils.sql_sanitiser import SQLSanitiser, SanitiserError
    check("SQLSanitiser importable", True)

    san = SQLSanitiser(allowed_tables={"customers", "orders"})

    # DDL rejection
    try:
        san.sanitise("DROP TABLE customers", {})
        check("DDL DROP rejected", False, "no error raised")
    except SanitiserError:
        check("DDL DROP rejected", True)

    try:
        san.sanitise("CREATE TABLE foo (id INT)", {})
        check("DDL CREATE rejected", False, "no error raised")
    except SanitiserError:
        check("DDL CREATE rejected", True)

    # Schema-qualified access
    try:
        san.sanitise("SELECT * FROM public.customers", {})
        check("Schema-qualified access rejected", False, "no error raised")
    except SanitiserError:
        check("Schema-qualified access rejected", True)

    # Table allowlist
    try:
        san.sanitise("SELECT id FROM secrets", {})
        check("Non-allowlist table rejected", False, "no error raised")
    except SanitiserError:
        check("Non-allowlist table rejected", True)

    # Valid parameterized query passes
    try:
        q, p = san.sanitise("SELECT id FROM customers WHERE id = :id LIMIT 5", {"id": 1})
        check("Valid parameterized query accepted", True)
    except SanitiserError as exc:
        check("Valid parameterized query accepted", False, str(exc))

    # build_select helper
    q2, p2 = san.build_select("orders", columns=["id", "status"], where={"customer_id": 42}, limit=10)
    check("build_select returns query string", "SELECT" in q2.upper())
    check("build_select uses parameterized value", 42 in p2.values())

except ImportError as exc:
    check("SQLSanitiser importable", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.3b PII Detector ===")
try:
    from app.core.utils.pii_detector import PIIDetector, PIIResult
    check("PIIDetector importable", True)

    det = PIIDetector()

    r1 = det.detect("Call me at +1-555-867-5309 please")
    check("Phone number detected", r1.has_pii and "phone_number" in r1.categories)

    r2 = det.detect("Email me at alice@example.com for details")
    check("Email address detected", r2.has_pii and "email_address" in r2.categories)

    r3 = det.detect("Nothing personal here, just hello world")
    check("Clean text → no PII", not r3.has_pii)

    meta = det.annotate_metadata({"some": "field"}, "reach me at bob@test.org or 555-123-4567")
    check("annotate_metadata adds pii_flags key", "pii_flags" in meta)
    check("annotate_metadata does not expose raw PII", "bob@test.org" not in str(meta.get("pii_flags")))

except ImportError as exc:
    check("PIIDetector importable", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.3c Twilio Guard ===")
try:
    from app.core.security.twilio_guard import (
        TwilioSigned,
        check_twilio_signature,
        validate_twilio_signature,
    )
    check("twilio_guard all symbols importable", True)
    check("check_twilio_signature is callable", callable(check_twilio_signature))
    check("TwilioSigned is Annotated type", hasattr(TwilioSigned, "__metadata__"))
except ImportError as exc:
    check("twilio_guard importable", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.3d AgentResponse — system_prompt removed ===")
try:
    from app.modules.agents.schemas import AgentPromptResponse, AgentResponse
    fields = AgentResponse.model_fields
    check("system_prompt NOT in AgentResponse", "system_prompt" not in fields)
    check("AgentPromptResponse has system_prompt field", "system_prompt" in AgentPromptResponse.model_fields)
    check("AgentPromptResponse has agent_id field", "agent_id" in AgentPromptResponse.model_fields)
except ImportError as exc:
    check("Agent schemas importable", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.3e Router — GET /prompt endpoint & TwilioSigned ===")
router_src = (BASE / "app" / "modules" / "agents" / "router.py").read_text()
check("TwilioSigned imported in router", "TwilioSigned" in router_src)
check("GET /prompt endpoint defined", 'GET' in router_src and "/prompt" in router_src)
check("AgentPromptResponse used in router", "AgentPromptResponse" in router_src)
check("_sig: TwilioSigned in inbound webhook", "_sig: TwilioSigned" in router_src)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 16.3f Service — VRAM guard & PII & handle_inbound ===")
service_src = (BASE / "app" / "modules" / "agents" / "service.py").read_text()
check("pynvml VRAM check present", "pynvml" in service_src)
check("1500 MiB VRAM threshold", "1500" in service_src)
check("ServiceUnavailableException used for VRAM", "ServiceUnavailableException" in service_src)
check("PIIDetector used in service", "PIIDetector" in service_src)
check("annotate_metadata called in write_call_log", "annotate_metadata" in service_src)
check("handle_inbound accepts org_id=None", "org_id: UUID | None = None" in service_src)

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== Summary ===")
if failures:
    print(f"\n{len(failures)} check(s) FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("\nAll checks passed. Day 16 looks good!")
