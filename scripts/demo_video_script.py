"""
VoiceSaaS Demo Video Script — 3-Minute Investor Demo
=====================================================
Four AI Voice Bot Types in Action

PRODUCTION NOTES
----------------
Recording tool : OBS Studio (1920×1080, 30fps, screen + microphone)
Browser        : Chrome  (DevTools closed, bookmark bar hidden)
Terminal       : kitty / iTerm2 — font size 18, dark theme
Environment    : docker-compose up running locally (all services healthy)
Seed data      : python scripts/seed_demo_agents.py --org-slug=demo-org
Postman        : collection loaded, env vars filled (token, org_id, agent_ids)

PRE-SHOOT CHECKLIST
-------------------
[ ] docker-compose up — all containers green
[ ] DB schema migrated (make migrate)
[ ] Superuser created + logged in  →  token saved in Postman env
[ ] All 4 demo agents active in /api/v1/agents
[ ] Browser tabs pre-loaded (minimise navigation during recording)
[ ] Phone available for live inbound Twilio demo (optional)
"""

SCRIPT = """
╔══════════════════════════════════════════════════════════════════════╗
║         VoiceSaaS Platform — 3-Minute Investor Demo Script           ║
╚══════════════════════════════════════════════════════════════════════╝

───────────────────────────────────────────────────────────────────────
SEGMENT 1  [0:00 – 0:30]  Hook & Platform Overview
───────────────────────────────────────────────────────────────────────

SHOW:  Terminal — docker-compose ps (all services green)
SHOW:  Browser — http://localhost:8000/docs (OpenAPI page loads instantly)

NARRATE:
  "In 2025, companies are replacing human call centres with AI voice bots
   that are indistinguishable from real agents.
   VoiceSaaS is a production-ready, multi-tenant platform that lets you
   deploy four specialised bot types — conversational, RAG-powered,
   database-driven, and one-way broadcast — all on a single stack,
   live in under five minutes.
   Let me show you."

SHOW:  Postman — GET /api/v1/agents  →  show 4 demo agents in response


───────────────────────────────────────────────────────────────────────
SEGMENT 2  [0:30 – 1:00]  Bot Type 1 — Aria (Conversational)
───────────────────────────────────────────────────────────────────────

SHOW:  Postman — POST /api/v1/agents/{{aria_agent_id}}/test-call
       Body: { "message": "Hi, what can you help me with today?" }
SHOW:  Response arrives < 300 ms — highlight duration_sec field
SHOW:  Postman — POST /api/v1/agents/{{aria_agent_id}}/webrtc/connect
SHOW:  JSON response — sdp answer, session_id, ice_servers

NARRATE:
  "Aria is our conversational bot powered by a fine-tuned LLM with
   sub-300 ms first-token latency.
   She handles open-ended dialogue using a WebRTC transport — zero PSTN
   cost for web and mobile apps.
   Notice the SDP answer comes back in under 200 ms — that's our VRAM
   guard and session pool working together."

SHOW:  Terminal — scroll service logs showing LLM token stream


───────────────────────────────────────────────────────────────────────
SEGMENT 3  [1:00 – 1:30]  Bot Type 2 — DocuBot (RAG) & OrderBot (DB)
───────────────────────────────────────────────────────────────────────

SHOW:  Postman — POST /api/v1/agents/{{docubot_id}}/test-call
       Body: { "message": "What is your return policy?" }
SHOW:  Response references seeded knowledge-base document

NARRATE:
  "DocuBot uses Retrieval-Augmented Generation — it searches a private
   Qdrant vector store, then synthesises a grounded answer.
   All document retrieval stays inside our network; Qdrant is never
   reachable from the public internet.

   Our third type, OrderBot, hits a real-time database view —
   safely, through an SQL sanitiser that blocks DDL, schema access,
   and non-allowlisted tables."

SHOW:  Postman — POST /api/v1/agents/{{orderbot_id}}/test-call
       Body: { "message": "What's the status of order 1042?" }
SHOW:  Response contains live order data from DB query


───────────────────────────────────────────────────────────────────────
SEGMENT 4  [1:30 – 2:00]  Bot Type 4 — Announcer (PSTN Outbound)
───────────────────────────────────────────────────────────────────────

SHOW:  Postman — POST /api/v1/agents/{{announcer_id}}/calls/outbound
       Body: { "to_number": "+15005550001" }
SHOW:  Response — call_sid, session_id, status: "initiated"

NARRATE:
  "Announcer is a one-way broadcast bot — think appointment reminders,
   fraud alerts, parcel notifications at scale.
   It initiates a Twilio outbound call, streams TTS audio, then hangs
   up — no LLM latency, virtually zero cost per message.
   All four bot types share the same auth, billing, and audit trail."

SHOW:  Browser — GET /api/v1/audit/logs  showing the outbound call event


───────────────────────────────────────────────────────────────────────
SEGMENT 5  [2:00 – 2:30]  Security & Multi-Tenancy
───────────────────────────────────────────────────────────────────────

SHOW:  Postman — GET /api/v1/agents/{{aria_agent_id}}/prompt
       Show AgentPromptResponse { agent_id, system_prompt }
SHOW:  GET /api/v1/agents/{{aria_agent_id}}  — system_prompt field ABSENT

NARRATE:
  "Security is first-class.
   System prompts are never leaked in list or detail API responses —
   only accessible via a separate, permission-gated endpoint.
   PII is flagged, not stored; all Twilio webhooks are HMAC-signed;
   VRAM exhaustion triggers a 503 before the LLM even loads.
   Every action is immutably logged in the audit trail."

SHOW:  Browser — /api/v1/dashboard/overview — real-time stats panel
SHOW:  Highlight: calls_today, avg_latency_ms, active_orgs


───────────────────────────────────────────────────────────────────────
SEGMENT 6  [2:30 – 3:00]  Production Deployment & Closing
───────────────────────────────────────────────────────────────────────

SHOW:  Terminal —
         docker build -f Dockerfile.prod -t voicesaas:prod .
         (build succeeds, image size shown)

NARRATE:
  "Deployment is a single command.
   Our production Docker image is multi-stage — audio libs, ffmpeg,
   non-root user, health-check baked in.
   docker-compose up --profile prod points directly at it.

   The platform is ready for Series A infrastructure:
   horizontal scale via the Celery task queue,
   per-tenant feature flags, Stripe billing, role-based access control,
   and a Locust load test that proves P95 latency under 900 ms with
   zero crash rate.

   We are looking for [AMOUNT] to [MILESTONE].
   Thank you."

SHOW:  Freeze on OpenAPI docs page — all 135 endpoints listed
       Fade to black / logo card


───────────────────────────────────────────────────────────────────────
POST-PRODUCTION NOTES
───────────────────────────────────────────────────────────────────────
• Trim dead time in Postman request-response cycles (CapCut / DaVinci)
• Add lower-thirds text for each bot type name
• Background music: ambient lo-fi at -18 dBFS
• Captions: 85% accuracy via Whisper auto-transcription, review manually
• Upload: Unlisted YouTube link for investor due-diligence package
"""

if __name__ == "__main__":
    print(SCRIPT)
