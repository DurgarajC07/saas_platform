#!/usr/bin/env python3
"""
Day 9 smoke test — Agents, Phone Numbers, Call Logs, Analytics.

Checks:
  1   POST /api/v1/auth/login           — login as superuser
  2   POST /api/v1/agents               — create agent → 201
  3   GET  /api/v1/agents               — list agents → 200, count ≥ 1
  4   GET  /api/v1/agents/{id}          — get agent detail → 200
  5   PATCH /api/v1/agents/{id}         — update llm_model, temperature → 200
  6   PUT  /api/v1/agents/{id}/prompt   — update system_prompt → 200
  7   PUT  /api/v1/agents/{id}/tools    — update tools_json → 200
  8   POST /api/v1/agents/{id}/test-call — issue WS URL → 200
  9   POST /api/v1/agents/{id}/phone-numbers — assign number → 201
  10  GET  /api/v1/agents/{id}/phone-numbers — list numbers → 200
  11  POST /api/v1/calls                — write call log → 201
  12  GET  /api/v1/calls/{id}           — get call detail → 200
  13  GET  /api/v1/agents/{id}/calls    — list agent calls → 200
  14  GET  /api/v1/agents/{id}/analytics — analytics → 200, expected fields
  15  POST /api/v1/agents (dup slug)    — conflict → 409
  16  DELETE /api/v1/agents/{id}        — soft delete → 204
  17  GET  /api/v1/agents/{id}          — 404 after delete
  18  Access control: missing org header → 403

Usage:
  # Start the app first:  uvicorn app.main:app --reload --port 8000
  python scripts/smoke_test_agents.py [superuser_email] [superuser_password]
"""

from __future__ import annotations

import sys
import uuid
import requests

BASE = "http://127.0.0.1:8000"
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


def login(email: str, password: str) -> str | None:
    r = requests.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        return r.json().get("accessToken")
    print(f"     login failed: {r.status_code} {r.text[:200]}")
    return None


def headers(token: str, org_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": org_id}


# ── Read CLI args ─────────────────────────────────────────────────────────────

ADMIN_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "admin@example.com"
ADMIN_PASS  = sys.argv[2] if len(sys.argv) > 2 else "Admin1234!"

print(f"\n=== Day 9 Smoke Test — Agents ===\n")
print(f"  Base URL : {BASE}")
print(f"  Admin    : {ADMIN_EMAIL}\n")

# ── 1. Login ──────────────────────────────────────────────────────────────────
token = login(ADMIN_EMAIL, ADMIN_PASS)
check("1. POST /auth/login — 200", token is not None)
if not token:
    print("\n  Cannot continue without a valid token. Exiting.")
    sys.exit(1)

# Fetch org_id from /me
me = requests.get(f"{BASE}/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
check("   GET /auth/me — 200", me.status_code == 200)

# Create a fresh org for this test run (each run is isolated)
org_slug = f"smoke-agents-{uuid.uuid4().hex[:8]}"
r_org = requests.post(
    f"{BASE}/api/v1/organizations",
    json={"name": f"Smoke Agents {org_slug}", "slug": org_slug},
    headers={"Authorization": f"Bearer {token}"},
)
check("   POST /organizations — 201", r_org.status_code == 201, f"status={r_org.status_code}")
if r_org.status_code != 201:
    print(f"     body: {r_org.text[:300]}")
    sys.exit(1)

org_id: str = r_org.json()["id"]
check("   org_id obtained", bool(org_id), f"org_id={org_id}")

H = headers(token, org_id)

# ── 2. Create agent ───────────────────────────────────────────────────────────
unique_suffix = str(uuid.uuid4())[:8]
agent_slug = f"test-agent-{unique_suffix}"

r = requests.post(
    f"{BASE}/api/v1/agents",
    json={
        "name": f"Test Agent {unique_suffix}",
        "slug": agent_slug,
        "agentType": "conversational",
        "status": "draft",
        "llmModel": "qwen2.5:3b",
        "systemPrompt": "You are a helpful assistant.",
        "temperature": 0.7,
        "maxTokens": 512,
        "ttsVoice": "af_heart",
        "ttsSpeed": 1.0,
        "vadThreshold": 0.5,
        "minSpeechMs": 250,
        "silenceMs": 800,
        "allowInterruptions": True,
        "noiseRemovalLevel": "none",
        "ragTopK": 3,
        "welcomeMessage": "Hello! How can I help you today?",
        "maxCallDurationSec": 300,
        "recordCalls": True,
    },
    headers=H,
)
check("2. POST /agents — 201", r.status_code == 201, f"status={r.status_code}")
if r.status_code != 201:
    print(f"     body: {r.text[:400]}")
    sys.exit(1)

agent = r.json()
agent_id = agent["id"]
check("   response has id, slug, orgId", all(k in agent for k in ("id", "slug", "orgId")))
check("   slug matches", agent.get("slug") == agent_slug)
check("   status is draft", agent.get("status") == "draft")

# ── 3. List agents ────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/agents", headers=H)
check("3. GET /agents — 200", r.status_code == 200)
if r.status_code == 200:
    body = r.json()
    check("   pagination present", "pagination" in body)
    check("   agents list not empty", len(body.get("agents", [])) >= 1)

# ── 4. Get agent detail ───────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/agents/{agent_id}", headers=H)
check("4. GET /agents/{id} — 200", r.status_code == 200)
if r.status_code == 200:
    detail = r.json()
    check("   id matches", detail.get("id") == agent_id)
    check("   systemPrompt present", "systemPrompt" in detail)

# ── 5. Update agent (PATCH) ───────────────────────────────────────────────────
r = requests.patch(
    f"{BASE}/api/v1/agents/{agent_id}",
    json={"llmModel": "qwen2.5:7b", "temperature": 0.9, "status": "active"},
    headers=H,
)
check("5. PATCH /agents/{id} — 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    updated = r.json()
    check("   llmModel updated", updated.get("llmModel") == "qwen2.5:7b")
    check("   temperature updated", abs(updated.get("temperature", 0) - 0.9) < 0.01)
    check("   status active", updated.get("status") == "active")

# ── 6. Update prompt ──────────────────────────────────────────────────────────
new_prompt = "You are an expert AI voice assistant for customer support."
r = requests.put(
    f"{BASE}/api/v1/agents/{agent_id}/prompt",
    json={"systemPrompt": new_prompt},
    headers=H,
)
check("6. PUT /agents/{id}/prompt — 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    check("   systemPrompt updated", r.json().get("systemPrompt") == new_prompt)

# ── 7. Update tools ───────────────────────────────────────────────────────────
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather",
            "parameters": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        },
    }
]
r = requests.put(
    f"{BASE}/api/v1/agents/{agent_id}/tools",
    json={"toolsJson": tools},
    headers=H,
)
check("7. PUT /agents/{id}/tools — 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    check("   toolsJson stored", r.json().get("toolsJson") is not None)

# ── 8. Test call ──────────────────────────────────────────────────────────────
r = requests.post(f"{BASE}/api/v1/agents/{agent_id}/test-call", headers=H)
check("8. POST /agents/{id}/test-call — 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    tc = r.json()
    check("   wsUrl present", "wsUrl" in tc)
    check("   sessionId present", "sessionId" in tc)
    check("   wsUrl contains agent_id", agent_id in tc.get("wsUrl", ""))

# ── 9. Assign phone number ────────────────────────────────────────────────────
_phone_digits = "".join(c for c in unique_suffix if c.isdigit())[:4].zfill(4)
phone = f"+1415555{_phone_digits}"
r = requests.post(
    f"{BASE}/api/v1/agents/{agent_id}/phone-numbers",
    json={"phoneNumber": phone, "provider": "twilio"},
    headers=H,
)
check("9. POST /agents/{id}/phone-numbers — 201", r.status_code == 201, f"status={r.status_code}")
if r.status_code == 201:
    pn = r.json()
    check("   phoneNumber matches", pn.get("phoneNumber") == phone)
    check("   provider is twilio", pn.get("provider") == "twilio")

# ── 10. List phone numbers ────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/agents/{agent_id}/phone-numbers", headers=H)
check("10. GET /agents/{id}/phone-numbers — 200", r.status_code == 200)
if r.status_code == 200:
    check("   at least 1 number", len(r.json()) >= 1)

# ── 11. Write call log ────────────────────────────────────────────────────────
import datetime as dt
r = requests.post(
    f"{BASE}/api/v1/calls",
    json={
        "agentId": agent_id,
        "orgId": org_id,
        "callerId": "+14155550000",
        "direction": "inbound",
        "transport": "websocket",
        "status": "completed",
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "durationSec": 42,
        "transcript": "User: Hello\nAgent: Hi there! How can I help?",
        "sttMs": 220,
        "llmTtftMs": 310,
        "ttsTtfbMs": 180,
    },
    headers=H,
)
check("11. POST /calls — 201", r.status_code == 201, f"status={r.status_code}")
if r.status_code != 201:
    print(f"     body: {r.text[:400]}")
call_id: str | None = r.json().get("id") if r.status_code == 201 else None
if r.status_code == 201:
    call = r.json()
    check("    agentId matches", call.get("agentId") == agent_id)
    check("    status completed", call.get("status") == "completed")
    check("    durationSec=42", call.get("durationSec") == 42)

# ── 12. Get call detail ───────────────────────────────────────────────────────
if call_id:
    r = requests.get(f"{BASE}/api/v1/calls/{call_id}", headers=H)
    check("12. GET /calls/{id} — 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        check("    transcript present", bool(r.json().get("transcript")))
else:
    check("12. GET /calls/{id} — skipped (no call_id)", False, "POST /calls failed")

# ── 13. List agent calls ──────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/agents/{agent_id}/calls", headers=H)
check("13. GET /agents/{id}/calls — 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    body = r.json()
    check("    calls list present", "calls" in body)
    check("    at least 1 call", len(body.get("calls", [])) >= 1)

# ── 14. Analytics ─────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/agents/{agent_id}/analytics?days=30", headers=H)
check("14. GET /agents/{id}/analytics — 200", r.status_code == 200, f"status={r.status_code}")
if r.status_code == 200:
    a = r.json()
    required = ("agentId", "totalCalls", "completedCalls", "sttLatency", "llmLatency", "ttsLatency")
    check("    required fields present", all(k in a for k in required))
    check("    totalCalls ≥ 1", a.get("totalCalls", 0) >= 1)

# ── 15. Duplicate slug → 409 ──────────────────────────────────────────────────
r = requests.post(
    f"{BASE}/api/v1/agents",
    json={"name": "Duplicate", "slug": agent_slug},
    headers=H,
)
check("15. POST /agents (dup slug) — 409", r.status_code == 409, f"status={r.status_code}")

# ── 16. Delete agent ──────────────────────────────────────────────────────────
r = requests.delete(f"{BASE}/api/v1/agents/{agent_id}", headers=H)
check("16. DELETE /agents/{id} — 204", r.status_code == 204, f"status={r.status_code}")

# ── 17. 404 after delete ──────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/agents/{agent_id}", headers=H)
check("17. GET /agents/{id} after delete — 404", r.status_code == 404, f"status={r.status_code}")

# ── 18. Missing org header → 403 ─────────────────────────────────────────────
r = requests.get(
    f"{BASE}/api/v1/agents",
    headers={"Authorization": f"Bearer {token}"},
)
check("18. GET /agents without X-Org-Id — 403", r.status_code == 403, f"status={r.status_code}")

# ── Summary ───────────────────────────────────────────────────────────────────
total = ok + errors
print(f"\n{'─' * 50}")
print(f"  Result: {ok}/{total} passed", end="")
if errors:
    print(f"  ← {errors} FAILED")
else:
    print("  ← ALL PASS ✓")
print()

sys.exit(0 if errors == 0 else 1)
