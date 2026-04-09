# VoiceSaaS Platform

> **Production-ready, multi-tenant AI Voice Bot platform.**  
> FastAPI · SQLAlchemy 2.0 async · PostgreSQL 16 · Redis · Qdrant · Celery · Docker

---

## ⚡ 5-Minute Quick-Start

### Prerequisites

| Tool | Minimum version |
|------|----------------|
| Docker Engine | 24+ |
| Docker Compose | v2 (plugin) |
| Python | 3.14 (for local dev) |
| uv | 0.5+ |

---

### Step 1 — Clone & configure

```bash
git clone <repo-url> voice_saas
cd voice_saas/saas_platform

cp .env.example .env
# Edit .env — at minimum set:
#   SECRET_KEY, JWT_SECRET, ENCRYPTION_KEY  (generate with: openssl rand -hex 32)
#   POSTGRES_PASSWORD
```

---

### Step 2 — Start infrastructure (single command)

```bash
# Development stack (hot-reload)
docker compose up -d

# Production stack (Dockerfile.prod, gunicorn workers)
docker compose -f docker-compose.prod.yml up -d
```

Wait ~10 seconds for PostgreSQL to become healthy, then:

```bash
docker compose logs api | tail -20
# Expected: "Application startup complete."
```

---

### Step 3 — Run database migrations

```bash
# Docker (recommended)
docker compose -f docker-compose.prod.yml run --rm migrate

# Local
make migrate         # or: alembic upgrade head
```

---

### Step 4 — Create superuser & seed demo agents

```bash
# Create admin account
docker compose exec api python scripts/create_superuser.py \
    --email admin@demo.local --password demo1234 --org-slug demo-org

# Seed 4 demo AI agents (Aria / DocuBot / OrderBot / Announcer)
docker compose exec api python scripts/seed_demo_agents.py \
    --org-slug demo-org

# (optional) Seed billing plans & permissions
docker compose exec api python scripts/seed_plans.py
docker compose exec api python scripts/seed_permissions.py
```

---

### Step 5 — Verify

```bash
# Health check
curl http://localhost:8000/health

# Interactive API docs
open http://localhost:8000/docs

# Login
curl -s -X POST http://localhost:8000/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"admin@demo.local","password":"demo1234"}' | jq .access_token
```

All 135 API endpoints are documented at `/docs` (Swagger UI) and `/redoc`.

---

## 🤖 The Four Bot Types

| Bot | Agent type | Voice | Use case |
|-----|-----------|-------|----------|
| **Aria** | `conversational` | `af_heart` | Open-ended dialogue, customer service |
| **DocuBot** | `rag_bot` | `bf_emma` | FAQ, policy lookup via private knowledge base |
| **OrderBot** | `db_bot` | `am_adam` | Real-time DB queries (orders, inventory) |
| **Announcer** | `speaker_only` | `af_sky` | One-way broadcast (reminders, alerts) |

---

## 📡 API Overview

Base URL: `http://localhost:8000/api/v1`

| Module | Prefix | Endpoints |
|--------|--------|-----------|
| Auth | `/auth` | Register, login, 2FA, OAuth, sessions |
| Tenancy | `/organizations` | Orgs, members, invitations, domains |
| Agents | `/agents` | CRUD, WebRTC, phone numbers, RAG, tools |
| Calls | `/calls` | Call logs, recordings, outbound |
| Dashboard | `/dashboard` | KPIs, latency, call volume, live SSE |
| Billing | `/billing` | Plans, subscriptions, invoices, Stripe |
| RBAC | `/rbac` | Roles, permissions, member assignments |
| Features | `/features` | Feature flags, per-org overrides |
| Notifications | `/notifications` | SSE stream, preferences, read state |
| Audit | `/audit/logs` | Immutable event log, CSV export |
| Security | `/security` | Login attempts, IP blocklist |
| Files | `/files` | Presigned upload/download |
| API Keys | `/api-keys` | API key management |
| Webhooks | `/webhooks` | Outbound webhook delivery |
| System | `/system` | Health, metrics, settings |

Full Postman collection: **`postman_collection.json`** (import → File → Import).

---

## 🔐 Security Features

- **JWT** (RS256 / HS256 configurable) + refresh tokens
- **TOTP 2FA** with backup codes
- **Twilio HMAC-SHA1** webhook validation (HTTP 401 on failure)
- **System prompt isolation** — never returned in list/detail endpoints
- **PII detection** — phone, email, CC, SSN flagged in call metadata
- **SQL sanitiser** — DDL block, schema-access block, table allowlist
- **VRAM guard** — 503 when GPU free memory < 1.5 GB
- **IP blocklist** middleware
- **AES-256** field-level encryption for secrets
- **Immutable audit log** for all write operations

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    VoiceSaaS API                        │
│   FastAPI  ·  gunicorn/uvicorn  ·  port 8000            │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
     ┌─────▼──────┐            ┌──────▼──────┐
     │ PostgreSQL │            │    Redis    │
     │    16      │            │  7 (queue,  │
     │  (data)    │            │   cache,    │
     └────────────┘            │   pub/sub)  │
                               └─────────────┘
           │
     ┌─────▼──────┐
     │   Qdrant   │  ← backend-only, no public port
     │ (vectors)  │
     └────────────┘
           │
     ┌─────▼──────┐
     │  Celery    │  ← email, maintenance, webhook delivery
     │  Worker    │
     └────────────┘
```

**Pipeline service** (AI inference, STT, TTS, LLM) runs separately on port 8001.

---

## 🧪 Testing

```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests (requires running stack)
pytest tests/integration/ -v

# Load test: 3 concurrent calls, P95 < 900 ms
pip install locust
locust -f tests/performance/locustfile.py \
       --headless -u 3 -r 1 --run-time 60s \
       --host http://localhost:8000 \
       --html tests/performance/report.html
```

---

## 🐳 Docker Images

| Image | Purpose |
|-------|---------|
| `Dockerfile` | Development (volume-mounted source, hot-reload) |
| `Dockerfile.prod` | Production (multi-stage, non-root, gunicorn, audio libs) |

Build production image:

```bash
docker build -f Dockerfile.prod -t voicesaas:prod .
docker run --rm -p 8000:8000 --env-file .env voicesaas:prod
```

---

## 🛠 Developer Workflow

```bash
# Install deps (local)
uv sync

# Activate venv
source .venv/bin/activate

# Start dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Create migration
alembic revision --autogenerate -m "describe_change"
alembic upgrade head

# Lint + format
ruff check . && ruff format .
```

Makefile shortcuts: `make dev`, `make migrate`, `make test`, `make lint`.

---

## 📁 Project Layout

```
saas_platform/
├── app/
│   ├── core/           # Database, Redis, security, middleware, utils
│   ├── modules/        # Feature modules (auth, agents, billing, …)
│   │   └── agents/     # AI agents, call logs, WebRTC, Twilio
│   ├── shared/         # Base models, schemas, repositories
│   └── tasks/          # Celery tasks (email, files, webhooks, …)
├── alembic/            # Database migrations
├── scripts/            # Seeding, smoke tests, collection generator
├── tests/
│   ├── unit/
│   ├── integration/
│   └── performance/    # Locust load test
├── Dockerfile          # Dev image
├── Dockerfile.prod     # Production image
├── docker-compose.yml  # Dev stack
├── docker-compose.prod.yml  # Production stack
└── postman_collection.json  # 135-endpoint Postman collection
```

---

## 📜 Licence

Proprietary — all rights reserved.
