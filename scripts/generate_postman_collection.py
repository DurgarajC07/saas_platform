"""
Generate VoiceSaaS Postman collection v2.1
Run: python scripts/generate_postman_collection.py
Writes: postman_collection.json
"""
from __future__ import annotations
import json, uuid

BASE = "{{base_url}}"
AUTH = {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]}

def req(method, path, name=None, body=None, desc="", no_auth=False, query=None):
    raw_url = f"{BASE}{path}"
    url_obj = {"raw": raw_url, "host": ["{{base_url}}"],
               "path": [p for p in path.lstrip("/").split("/") if p]}
    if query:
        url_obj["query"] = [{"key": k, "value": v, "disabled": False} for k, v in query.items()]
    r = {"name": name or f"{method} {path}",
         "request": {
             "method": method,
             "header": [{"key": "X-Org-ID", "value": "{{org_id}}"}],
             "url": url_obj,
             "description": desc,
         }}
    if not no_auth:
        r["request"]["auth"] = AUTH
    if body:
        r["request"]["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2),
                                 "options": {"raw": {"language": "json"}}}
    return r

def folder(name, items):
    return {"name": name, "item": items}

items = [

  folder("Auth", [
    req("POST", "/api/v1/auth/register", "Register",
        {"email": "user@example.com", "password": "Str0ngPass!", "full_name": "Demo User"}, no_auth=True),
    req("GET",  "/api/v1/auth/verify-email", "Verify Email",
        no_auth=True, query={"token": "{{verify_token}}"}),
    req("POST", "/api/v1/auth/login", "Login",
        {"email": "admin@demo.local", "password": "demo1234"}, no_auth=True),
    req("POST", "/api/v1/auth/refresh", "Refresh Token",
        {"refresh_token": "{{refresh_token}}"}, no_auth=True),
    req("POST", "/api/v1/auth/logout", "Logout"),
    req("POST", "/api/v1/auth/forgot-password", "Forgot Password",
        {"email": "user@example.com"}, no_auth=True),
    req("POST", "/api/v1/auth/reset-password", "Reset Password",
        {"token": "{{reset_token}}", "new_password": "NewPass123!"}, no_auth=True),
    req("GET",  "/api/v1/auth/me", "Get Current User"),
    req("POST", "/api/v1/auth/password/change", "Change Password",
        {"old_password": "OldPass123!", "new_password": "NewPass456!"}),
    req("GET",  "/api/v1/auth/sessions", "List Sessions"),
    req("DELETE","/api/v1/auth/sessions/{{session_id}}", "Revoke Session"),
    req("DELETE","/api/v1/auth/sessions", "Revoke All Sessions"),
    req("POST", "/api/v1/auth/2fa/setup", "Setup 2FA"),
    req("POST", "/api/v1/auth/2fa/confirm", "Confirm 2FA", {"code": "123456"}),
    req("POST", "/api/v1/auth/2fa/verify",  "Verify 2FA",  {"code": "123456"}),
    req("DELETE","/api/v1/auth/2fa/disable","Disable 2FA"),
    req("POST", "/api/v1/auth/2fa/backup",  "Use Backup Code", {"backup_code": "ABCD-EFGH"}),
  ]),

  folder("Tenancy", [
    req("POST", "/api/v1/organizations", "Create Org",
        {"name": "Acme Corp", "slug": "acme", "plan_id": "{{plan_id}}"}),
    req("GET",  "/api/v1/organizations/{{org_slug}}", "Get Org"),
    req("PATCH","/api/v1/organizations/{{org_id}}", "Update Org",
        {"name": "Acme Corp Updated"}),
    req("DELETE","/api/v1/organizations/{{org_id}}", "Delete Org"),
    req("GET",  "/api/v1/organizations/{{org_id}}/members", "List Members"),
    req("DELETE","/api/v1/organizations/{{org_id}}/members/{{user_id}}", "Remove Member"),
    req("PATCH","/api/v1/organizations/{{org_id}}/members/{{user_id}}/role", "Update Member Role",
        {"role": "admin"}),
    req("POST", "/api/v1/organizations/{{org_id}}/invitations", "Send Invitation",
        {"email": "colleague@example.com", "role": "member"}),
    req("GET",  "/api/v1/organizations/{{org_id}}/invitations", "List Invitations"),
    req("DELETE","/api/v1/organizations/{{org_id}}/invitations/{{invitation_id}}", "Cancel Invitation"),
    req("POST", "/api/v1/invitations/accept", "Accept Invitation", {"token": "{{invite_token}}"}),
    req("POST", "/api/v1/organizations/{{org_id}}/domains", "Add Domain",
        {"domain": "acme.com"}),
    req("GET",  "/api/v1/organizations/{{org_id}}/domains", "List Domains"),
    req("DELETE","/api/v1/organizations/{{org_id}}/domains/{{domain_id}}", "Remove Domain"),
    req("POST", "/api/v1/organizations/{{org_id}}/domains/{{domain_id}}/verify", "Verify Domain"),
  ]),

  folder("Billing", [
    req("GET",  "/api/v1/billing/plans", "List Plans", no_auth=True),
    req("GET",  "/api/v1/billing/plans/{{plan_id}}", "Get Plan"),
    req("POST", "/api/v1/billing/plans", "Create Plan (Admin)",
        {"name": "Pro", "price_usd": 49.00, "call_minutes": 1000}),
    req("PATCH","/api/v1/billing/plans/{{plan_id}}", "Update Plan (Admin)",
        {"price_usd": 59.00}),
    req("DELETE","/api/v1/billing/plans/{{plan_id}}", "Delete Plan (Admin)"),
    req("GET",  "/api/v1/billing/subscription", "Get Subscription"),
    req("POST", "/api/v1/billing/subscribe", "Subscribe",
        {"plan_id": "{{plan_id}}", "payment_method_id": "pm_test_xxx"}),
    req("POST", "/api/v1/billing/cancel", "Cancel Subscription"),
    req("GET",  "/api/v1/billing/invoices", "List Invoices"),
    req("GET",  "/api/v1/billing/invoices/{{invoice_id}}", "Get Invoice"),
    req("GET",  "/api/v1/billing/payment-methods", "List Payment Methods"),
    req("POST", "/api/v1/billing/payment-methods", "Add Payment Method",
        {"payment_method_id": "pm_test_xxx"}),
    req("PUT",  "/api/v1/billing/payment-methods/{{pm_id}}/default", "Set Default PM"),
    req("GET",  "/api/v1/billing/usage", "Get Usage"),
    req("GET",  "/api/v1/billing/invoice-preview", "Preview Invoice"),
  ]),

  folder("RBAC", [
    req("GET",  "/api/v1/rbac/roles", "List Roles"),
    req("POST", "/api/v1/rbac/roles", "Create Role", {"name": "support", "permissions": []}),
    req("PATCH","/api/v1/rbac/roles/{{role_id}}", "Update Role", {"name": "senior-support"}),
    req("DELETE","/api/v1/rbac/roles/{{role_id}}", "Delete Role"),
    req("GET",  "/api/v1/rbac/roles/{{role_id}}/permissions", "Get Role Permissions"),
    req("PUT",  "/api/v1/rbac/roles/{{role_id}}/permissions", "Set Role Permissions",
        {"permissions": ["agents.agent.read", "calls.call.read"]}),
    req("GET",  "/api/v1/rbac/permissions", "List All Permissions"),
    req("GET",  "/api/v1/rbac/members/{{member_id}}/roles", "Get Member Roles"),
    req("PUT",  "/api/v1/rbac/members/{{member_id}}/roles/{{role_id}}", "Assign Role"),
    req("DELETE","/api/v1/rbac/members/{{member_id}}/roles/{{role_id}}", "Remove Role"),
  ]),

  folder("Features & Feature Gates", [
    req("GET",  "/api/v1/features", "List Available Features"),
    req("GET",  "/api/v1/features/check", "Check Feature Access",
        query={"key": "ai.agents.create"}),
    req("POST", "/api/v1/admin/features", "Create Feature (Admin)",
        {"key": "ai.custom", "name": "Custom AI", "description": "Custom feature"}),
    req("POST", "/api/v1/admin/plans/{{plan_id}}/features", "Assign Feature to Plan",
        {"feature_key": "ai.agents.create", "enabled": True}),
    req("POST", "/api/v1/admin/organizations/{{org_id}}/feature-overrides",
        "Override Feature for Org", {"feature_key": "ai.webrtc.enabled", "enabled": True}),
    req("DELETE", "/api/v1/admin/organizations/{{org_id}}/feature-overrides/{{override_id}}",
        "Remove Feature Override"),
  ]),

  folder("Agents", [
    req("POST", "/api/v1/agents", "Create Agent",
        {"name": "Aria", "agent_type": "conversational", "tts_voice": "af_heart",
         "system_prompt": "You are a helpful assistant.", "welcome_message": "Hi!",
         "language": "en"}),
    req("GET",  "/api/v1/agents", "List Agents"),
    req("GET",  "/api/v1/agents/{{agent_id}}", "Get Agent"),
    req("PATCH","/api/v1/agents/{{agent_id}}", "Update Agent", {"name": "Aria v2"}),
    req("DELETE","/api/v1/agents/{{agent_id}}", "Delete Agent"),
    req("GET",  "/api/v1/agents/{{agent_id}}/prompt", "Get System Prompt (Secure)"),
    req("PUT",  "/api/v1/agents/{{agent_id}}/prompt", "Update System Prompt",
        {"system_prompt": "You are a helpful sales assistant."}),
    req("POST", "/api/v1/agents/{{agent_id}}/phone-numbers", "Assign Phone Number",
        {"phone_number": "+15005550006"}),
    req("GET",  "/api/v1/agents/{{agent_id}}/phone-numbers", "List Phone Numbers"),
    req("POST", "/api/v1/agents/{{agent_id}}/knowledge-base", "Upload Knowledge Doc",
        {"title": "FAQ", "content": "Q: What is pricing? A: See pricing page."},
        desc="Uploads a document chunk to the agent's Qdrant collection."),
    req("GET",  "/api/v1/agents/{{agent_id}}/knowledge-base", "List Knowledge Docs"),
    req("DELETE","/api/v1/agents/{{agent_id}}/knowledge-base/{{doc_id}}", "Delete Doc"),
    req("DELETE","/api/v1/agents/{{agent_id}}/knowledge-base", "Clear Knowledge Base"),
    req("PUT",  "/api/v1/agents/{{agent_id}}/tools", "Update Tool Config",
        {"tools_json": [{"type": "function", "name": "lookup_order"}]}),
    req("POST", "/api/v1/agents/{{agent_id}}/test-call", "Test Call",
        {"message": "Hello, can you help me?"}),
    req("POST", "/api/v1/agents/{{agent_id}}/webrtc/connect", "WebRTC Connect (SDP Offer)",
        {"sdp": "v=0\r\n...", "type": "offer"}),
    req("GET",  "/api/v1/agents/usage/minutes", "Agent Minutes Usage"),
    req("GET",  "/api/v1/agents/{{agent_id}}/calls", "List Agent Calls"),
    req("GET",  "/api/v1/agents/{{agent_id}}/analytics", "Agent Analytics"),
  ]),

  folder("Calls", [
    req("POST", "/api/v1/calls", "Write Call Log",
        {"agent_id": "{{agent_id}}", "org_id": "{{org_id}}", "session_id": "{{$randomUUID}}",
         "direction": "inbound", "transport": "webrtc", "status": "completed", "duration_sec": 45}),
    req("GET",  "/api/v1/calls/{{call_id}}", "Get Call Log"),
    req("GET",  "/api/v1/calls/{{call_id}}/recording", "Get Recording Presigned URL"),
    req("POST", "/api/v1/agents/{{agent_id}}/calls/outbound", "Start Outbound Call",
        {"to_number": "+15005550001"}),
  ]),

  folder("Dashboard & Analytics", [
    req("GET",  "/api/v1/dashboard/overview",          "Dashboard Overview"),
    req("GET",  "/api/v1/dashboard/latency",           "Latency Percentiles",
        query={"window_min": "60"}),
    req("GET",  "/api/v1/dashboard/call-volume",       "Call Volume",
        query={"period": "7d"}),
    req("GET",  "/api/v1/dashboard/agent-performance", "Agent Performance"),
    req("GET",  "/api/v1/calls/live",                  "Live Calls SSE",
        desc="Server-Sent Events stream. Use EventSource in browser."),
    req("GET",  "/api/v1/admin/gpu-status",            "GPU VRAM Status (Admin)"),
    req("GET",  "/api/v1/admin/queue-status",          "Celery Queue Status (Admin)"),
    req("POST", "/api/v1/admin/model-benchmark",       "Run Model Benchmark (Admin)"),
  ]),

  folder("Notifications", [
    req("GET",  "/api/v1/notifications",                         "List Notifications"),
    req("GET",  "/api/v1/notifications/count",                   "Unread Count"),
    req("GET",  "/api/v1/notifications/stream",                  "SSE Notification Stream"),
    req("PUT",  "/api/v1/notifications/read-all",                "Mark All Read"),
    req("PUT",  "/api/v1/notifications/{{notification_id}}/read","Mark Read"),
    req("GET",  "/api/v1/notifications/preferences",             "Get Preferences"),
    req("PUT",  "/api/v1/notifications/preferences",             "Update Preferences",
        {"email": True, "sms": False, "in_app": True}),
    req("POST", "/api/v1/notifications/test-send",               "Send Test Notification",
        {"channel": "in_app", "message": "Test notification"}),
  ]),

  folder("Files", [
    req("POST", "/api/v1/files/upload", "Upload File",
        desc="multipart/form-data; field: file (binary)"),
    req("GET",  "/api/v1/files/",                 "List Files"),
    req("GET",  "/api/v1/files/{{file_id}}",      "Get File Metadata"),
    req("GET",  "/api/v1/files/{{file_id}}/download", "Download File"),
    req("DELETE","/api/v1/files/{{file_id}}",     "Delete File"),
  ]),

  folder("API Keys & Webhooks", [
    req("POST", "/api/v1/api-keys", "Create API Key",
        {"name": "CI pipeline", "scopes": ["agents:read"]}),
    req("GET",  "/api/v1/api-keys",         "List API Keys"),
    req("DELETE","/api/v1/api-keys/{{key_id}}", "Revoke API Key"),
    req("GET",  "/api/v1/api-keys/verify",  "Verify API Key"),
    req("POST", "/api/v1/webhooks", "Create Webhook",
        {"url": "https://example.com/hook", "events": ["call.completed"]}),
    req("GET",  "/api/v1/webhooks", "List Webhooks"),
    req("GET",  "/api/v1/webhooks/{{webhook_id}}", "Get Webhook"),
    req("PATCH","/api/v1/webhooks/{{webhook_id}}", "Update Webhook",
        {"events": ["call.completed", "call.started"]}),
    req("DELETE","/api/v1/webhooks/{{webhook_id}}", "Delete Webhook"),
    req("GET",  "/api/v1/webhooks/{{webhook_id}}/deliveries", "Webhook Deliveries"),
  ]),

  folder("Audit", [
    req("GET", "/api/v1/audit/logs",          "List Audit Logs",
        query={"page": "1", "page_size": "20"}),
    req("GET", "/api/v1/audit/logs/export",   "Export Audit Logs (CSV)"),
    req("GET", "/api/v1/audit/logs/{{log_id}}","Get Audit Log Entry"),
  ]),

  folder("Security", [
    req("GET",  "/api/v1/security/login-attempts", "Login Attempts"),
    req("GET",  "/api/v1/security/blocked-ips",    "Blocked IPs"),
    req("POST", "/api/v1/security/blocked-ips",    "Block IP",
        {"ip_address": "1.2.3.4", "reason": "Brute force"}),
    req("DELETE","/api/v1/security/blocked-ips/{{blocked_id}}", "Unblock IP"),
    req("GET",  "/api/v1/security/events",         "Security Events"),
  ]),

  folder("System", [
    req("GET", "/health",                    "Health Check", no_auth=True),
    req("GET", "/api/v1/system/health",      "System Health Detail"),
    req("GET", "/api/v1/system/metrics",     "Prometheus Metrics"),
    req("GET", "/api/v1/system/settings",    "List System Settings (Admin)"),
    req("GET", "/api/v1/system/settings/{{key}}", "Get Setting"),
    req("PUT", "/api/v1/system/settings/{{key}}", "Update Setting",
        {"value": "new_value"}),
    req("DELETE", "/api/v1/system/settings/{{key}}", "Delete Setting"),
    req("GET", "/api/v1/admin/stats",        "Platform Stats (Admin)"),
  ]),

  folder("Twilio Webhooks (internal)", [
    req("POST", "/api/v1/webhooks/twilio/inbound/{{phone_number}}", "Twilio Inbound",
        desc="Called by Twilio — requires HMAC-SHA1 X-Twilio-Signature header.", no_auth=True),
    req("POST", "/api/v1/webhooks/twilio/connect/{{session_id}}", "Twilio Connect Callback",
        desc="Outbound call connect callback from Twilio.", no_auth=True),
  ]),
]

collection = {
  "info": {
    "_postman_id": str(uuid.uuid4()),
    "name": "VoiceSaaS Platform — All Endpoints",
    "description": (
        "Complete API collection for the VoiceSaaS multi-tenant platform.\n\n"
        "Set collection variables:\n"
        "  base_url  — http://localhost:8000\n"
        "  token     — fill after login\n"
        "  org_id    — X-Org-ID header value\n\n"
        "Generated by scripts/generate_postman_collection.py"
    ),
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
  },
  "item": items,
  "variable": [
    {"key": "base_url",         "value": "http://localhost:8000"},
    {"key": "token",            "value": ""},
    {"key": "org_id",           "value": ""},
    {"key": "org_slug",         "value": "demo-org"},
    {"key": "agent_id",         "value": ""},
    {"key": "call_id",          "value": ""},
    {"key": "plan_id",          "value": ""},
    {"key": "role_id",          "value": ""},
    {"key": "webhook_id",       "value": ""},
    {"key": "notification_id",  "value": ""},
    {"key": "file_id",          "value": ""},
    {"key": "key_id",           "value": ""},
    {"key": "pm_id",            "value": ""},
    {"key": "member_id",        "value": ""},
    {"key": "user_id",          "value": ""},
    {"key": "session_id",       "value": ""},
    {"key": "invoice_id",       "value": ""},
    {"key": "domain_id",        "value": ""},
    {"key": "invitation_id",    "value": ""},
    {"key": "override_id",      "value": ""},
    {"key": "blocked_id",       "value": ""},
    {"key": "log_id",           "value": ""},
    {"key": "doc_id",           "value": ""},
    {"key": "phone_number",     "value": "+15005550006"},
    {"key": "key",              "value": "maintenance.mode"},
    {"key": "refresh_token",    "value": ""},
    {"key": "verify_token",     "value": ""},
    {"key": "reset_token",      "value": ""},
    {"key": "invite_token",     "value": ""},
  ],
  "auth": AUTH,
}

out = "postman_collection.json"
with open(out, "w") as fh:
    json.dump(collection, fh, indent=2)

# Count requests
total = sum(len(f["item"]) for f in items)
print(f"Written {out}  ({total} requests across {len(items)} folders)")
