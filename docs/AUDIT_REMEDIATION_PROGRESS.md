# Audit Remediation Progress

Source: full-codebase audit (infra/AI-pipeline, backend app/API, frontend/SDK,
tests/migrations/hygiene) run 2026-10-25 against
`AI_Call_SaaS_Technical_Implementation_Plan.md`. Remediation executed the
same day across four workstreams (backend core done directly; infra,
pipeline, and frontend each done by a dedicated agent working on disjoint
files). This file is the source of truth for what shipped vs. what's left —
keep it current as follow-up work lands.

Status legend: `[x]` done · `[~]` partially done (see note) · `[ ]` pending/deferred

---

## P0 — breaks prod / security / data loss

- [x] **1. `docker-compose.prod.yml` couldn't boot the API.** Fixed env var
  names (`JWT_SECRET`→`JWT_SECRET_KEY`, `APP_ENV`→`ENVIRONMENT`,
  `PIPELINE_BASE_URL`→`PIPELINE_SERVICE_URL:7000`), removed dead
  `SECRET_KEY`/`SENTRY_DSN` vars, added a `pipeline` service to the prod
  compose file on both `saas-net` and `ai-net` so the hostname actually
  resolves, bumped Qdrant to v1.9.0 to match infra. Full var-by-var trace
  against `app/config.py` confirmed no other mismatches.
- [x] **2. SQL injection in the tool executor.** `SQLQueryExecutor` now
  parameterizes via asyncpg `$1, $2, ...` positional binds instead of
  `str.format()` into the query string; caller/LLM-supplied values never
  touch the SQL text. DDL/DML blocklist kept as defense-in-depth. Negative
  tests added (boolean + UNION payloads proven to never appear in the query
  string).
- [x] **3. Twilio PSTN was completely broken.** Fixed `agent.is_active` →
  `agent.status == "active"` and `agent.voice_id` → `agent.tts_voice`
  (neither field existed). Also found and fixed a **second, deeper bug**
  the audit didn't catch: `TwilioCallService._create_pipeline_session` was
  sending a flat camelCase payload the pipeline's `/sessions` endpoint
  doesn't accept at all (it expects a nested `agent_config` object) — every
  Twilio call would have failed at that step even after the AttributeError
  fix. Rewrote it to share the same `_build_agent_config()` helper as
  WebRTC, so both transports now send an identical, schema-correct payload.
- [x] **4. Audit-log crash after Twilio calls connect.** Fixed kwarg
  mismatches (`metadata=`→`new_values=`, `actor_id=`→`actor_user_id=`) at
  both `AuditService.log()` call sites in `TwilioCallService`.
- [x] **5. VRAM-exhaustion guard was dead code.** `ServiceUnavailableException`
  is now imported in `agents/service.py`; the guard actually fires.
- [x] **6. Alembic chain was broken.** Hand-wrote a base migration
  (`f3a1c9d04b7e`, down_revision=None) covering all 30 previously-unmigrated
  tables (users, organizations, rbac, billing, features, audit, etc.),
  repointed the existing agents/call_logs migration's down_revision at it,
  added a new migration for the previously-missing `kb_documents` table.
  Chain is now `f3a1c9d04b7e → ad24a2368af2 → 0c6e2a9d7f41` (head), unbroken.
  `alembic/versions/*.py` is no longer gitignored.
  **Caveat:** hand-transcribed from model files, not generated via
  `alembic revision --autogenerate` against a live DB (none was available in
  the execution sandbox) — **run a real `alembic upgrade head` against a
  fresh Postgres instance before trusting this in CI/prod.**
- [x] **7. Qdrant was publicly exposed, no auth.** Ports now bind to
  `127.0.0.1` only; `QDRANT__SERVICE__API_KEY` added and wired into every
  Qdrant client construction site (`app/core/qdrant.py` already had it;
  `services/rag/ingestion.py` and `services/pipeline/processors/rag.py`
  fixed to pass it too).
- [x] **8. Recording URLs were a non-expiring stub.** `get_recording_url`
  now presigns a real 1-hour MinIO URL via `aioboto3`, using the same
  endpoint/credentials the pipeline's `call_recorder.py` uploads to (added
  `MINIO_*` settings to `app/config.py` mirroring the pipeline's env vars).
- [x] **9. Cross-tenant call-log forgery.** `write_call_log` now verifies
  `agent_id` actually belongs to `org_id` before persisting, instead of
  trusting the body unconditionally.
- [x] **10. Billing/plan limits were unenforced.** `CallCreditService` is
  now actually wired into the call lifecycle (previously only called from
  tests): pre-call check + post-call deduction in `webrtc_connect`,
  `test_call`'s callers, Twilio inbound/outbound, and `write_call_log`.
  Added `ai.agents.max` (checked in `create_agent`), `ai.calls.concurrent`
  (new atomic Redis slot-acquisition in `credits.py`, previously only a
  hardcoded global pipeline-side cap), and `ai.rag.doc_limit` (checked in
  `KnowledgeBaseService.upload_document`).
  **Also fixed a logic bug the audit flagged**: a plan with the feature
  *disabled* used to fall through to "unlimited" instead of being blocked —
  `check_and_deduct`/`acquire_call_slot` now check `result.enabled` directly
  and reject immediately when the org's plan doesn't include the feature.
  **Also fixed a second, previously-undiscovered bug**: the `/calls`
  endpoint always constructed `CallLogService(db)` with no Redis, so the
  "working" `call.started/ended/failed` webhook/SSE publishing documented by
  the backend audit had actually **never fired in production** — Redis is
  now injected from the router.
- [x] **11. LLM didn't cancel generation on barge-in.** `OllamaLLMProcessor`
  now tracks and cancels the in-flight generation task on
  `StartInterruptionFrame`; a cancelled response is discarded, never
  appended to history.
- [x] **12. TOCTOU race in the call-concurrency gate.** The pipeline's
  "count active, then admit" sequence in all three session entry points now
  happens atomically under the existing session lock. (Separately, the new
  *per-org* `ai.calls.concurrent` enforcement in `credits.py` uses an
  INCR-then-check-and-compensate pattern, which is atomic by construction.)
- [x] **13. Call recordings were fully in-memory until call end.** Pipeline
  now spools inbound/outbound PCM to temp files instead of growing Python
  lists — bounds memory for the call's duration. **Caveat (documented in
  code):** still does not survive a hard process kill before `finish()`
  uploads — true crash-safety would need periodic multipart upload to
  MinIO, which was flagged as a follow-up rather than built under time
  pressure (no existing background-flush mechanism to hook into).
- [x] **14. Function-calling secrets never reached the pipeline.** New
  `OrgSecretsService` (`app/modules/agents/secrets_service.py`) stores
  Fernet-encrypted secrets inside `Organization.settings["ai_secrets"]` (no
  new table/migration needed) and decrypts them only in-process right
  before attaching to a session payload. Wired into both `webrtc_connect`
  and `TwilioCallService._create_pipeline_session`. Added admin-only
  (`agents.admin.models`) endpoints: `PUT/GET/DELETE /agents/org-secrets`.

## P1/P2 — frontend gap

- [x] **16. Frontend stub pages.** Built out: agent detail/edit/prompt/
  tools/phone-numbers pages, knowledge-base upload+status+delete UI (new
  `features/knowledge-base/`), per-agent calls list + global call detail +
  per-agent analytics (new `features/calls/`), full billing UI — usage,
  plans, invoices, payment methods (new `features/billing/`), and the
  previously-orphaned `sdk/ai-call-sdk.js` is now ported to TypeScript and
  wired into a working test-call page with its error/status callbacks
  surfaced in the UI instead of only console-logged.
  Verified with a full-project `tsc --noEmit` — zero errors.
  **Known gaps the frontend agent flagged honestly rather than faking —
  both now closed in the follow-up round (see "Smaller items" below):**
  the missing global `GET /calls` endpoint was added and the calls page
  rewired to a real table, and the phone-number unassign TODO was wired up
  once the backend route existed.
  **Still open:** payment-method collection is a manual-entry form (no
  Stripe Elements — no `@stripe/stripe-js` dependency exists yet).

## Bonus fixes beyond the original 20 findings (found/fixed during remediation)

- Added `DELETE /agents/{agent_id}/phone-numbers/{phone_number_id}`
  (`AgentService.unassign_phone_number` + repository support) — was listed
  as a known gap in the original audit; now closed.
- Fixed a route collision: both `app/modules/agents/router.py` and
  `app/modules/dashboard/router.py` registered `GET /agents/{id}/analytics`
  with different response models — the dashboard one was silently
  unreachable (shadowed by router include order). Renamed the dashboard
  deep-dive route to `/agents/{agent_id}/analytics/deep-dive`.
- Fixed `TwilioCallService._create_pipeline_session`'s payload shape
  mismatch with the pipeline's actual `/sessions` contract (see item 3 above)
  — a bug one layer deeper than what the audit caught.
- Fixed the `CallLogService(db)` missing-Redis bug that silently disabled
  all call lifecycle webhooks/SSE (see item 10 above).
- `KnowledgeBaseIngestor` is now a cached singleton instead of reloading its
  FastEmbed ONNX model on every delete/clear-all request.

## P3 — hygiene

- [x] **15. Test coverage for the fixed logic.** SQL injection (executor
  fix, item 2), tenant-binding rejection on `write_call_log` (item 9),
  credit-deduction + concurrency-slot wiring (item 10), and the
  `ai.agents.max` limit — all now have real, executed tests (see "Real
  verification round" below; 18 new tests, 53/53 unit + 43/43 pipeline
  tool-executor tests passing). **Still open:** no automated test actually
  drives `TwilioCallService.handle_inbound`/`start_outbound_call`
  end-to-end (only their collaborators are tested in isolation) — a test
  that called these with a mocked HTTP layer would have caught both the
  `agent.is_active`/`voice_id` AttributeErrors and the payload-shape
  mismatch immediately, and is the highest-value test still missing.
- [x] **17. `requirements.txt` regenerated** to match `pyproject.toml`
  (added `gunicorn`, `authlib`, `stripe`, `python-magic`,
  `prometheus-client`, `websockets`, `numpy`).
- [x] **18. RAG embedding model mismatch fixed** — retrieval now uses
  `BAAI/bge-small-en-v1.5` matching ingestion.
- [x] **19. Dead webhook events wired up.** `agent.limit_warning` /
  `agent.limit_exceeded` now fire from `write_call_log`'s credit-deduction
  path; `kb.ingestion.complete` now fires from `app/tasks/rag.py` after a
  document finishes processing.
- [x] **20. `.husky/pre-commit` fixed.** Added `frontend/.lintstagedrc.json`
  (eslint --fix + prettier on staged files); `.husky/` no longer gitignored.

## Smaller items from the original audit — status

- [x] Dead STT language-hint query param — whisper WS handler now honors it.
- [x] Duplicate `/agents/{id}/analytics` route — resolved (see bonus fixes).
- [x] Missing `DELETE /agents/{id}/phone-numbers` — added, **and** wired into
  the frontend (unassign button + confirm dialog) in the follow-up round.
- [x] Benchmark script `UnboundLocalError` — fixed.
- [x] `KnowledgeBaseIngestor` reloading per request — fixed (singleton).
- [x] **SSE auth token in URL — fixed, and turned out to be a deeper bug
  than just token exposure.** `GET /calls/live` required an `Authorization`
  header *and* an `X-Org-ID` header — neither of which a browser's native
  `EventSource` can ever set — so the endpoint was unreachable from a real
  browser regardless of how auth was passed. Added a short-lived (30s),
  single-use ticket exchange: `POST /dashboard/live-calls/ticket` (normal
  Bearer+org-header auth, fully permission-checked) returns a ticket;
  `GET /calls/live?ticket=...` consumes it via Redis `GETDEL`. Rewrote
  `useSSE` to fetch a ticket through the authenticated `apiClient` and
  reconnect with a *fresh* ticket on drop (the native EventSource
  auto-retry would otherwise keep retrying with the same, now-dead, ticket
  forever). Also fixed the endpoint's "~30s keepalive" comment, which was
  actually a no-op `sleep(0)` — switched to `pubsub.get_message(timeout=30)`
  so idle connections behind a proxy with an idle timeout don't get dropped.
  **Still not done:** the hook is now correct and ready to use, but nothing
  calls it yet — the dashboard's "Live Calls" widget still polls via
  `useOverview()`, which is a legitimate working design, not a bug. Wiring
  SSE into that widget is a feature addition, not a fix, so left for later.
- [x] Dual camelCase/snake_case guessing in both the ported TS SDK client
  and the original `sdk/ai-call-sdk.js` — confirmed backend responses are
  Pydantic `CamelModel`s (always camelCase on the wire) and removed the
  dead snake_case fallback branches in both files.
- [x] Added a global `GET /calls` endpoint (`CallLogRepository.list_by_org`
  + `CallLogService.list_calls_for_org`) since the frontend agent correctly
  flagged its absence rather than faking a list. Rewired
  `frontend/src/pages/calls/index.page.tsx` from its honest-empty-state
  placeholder to a real paginated table, reusing the same `DataTable`
  pattern as the per-agent calls page.
- [ ] Access/refresh tokens in `localStorage` — **not fixed**, no XSS
  vector currently exists to exploit it, but it's a landmine for the day one
  does (e.g. a markdown/HTML transcript renderer). Fixing this properly
  (httpOnly refresh cookie) touches the whole auth flow (login, refresh,
  CORS/SameSite) and couldn't be verified end-to-end in this environment
  (no backend/DB available to run against) — deferred rather than risking
  an unverified change to the auth path.
- [ ] Seeded fine-grained permissions (`agents.knowledge_base.*`,
  `agents.tools.manage`, `agents.call.export`) never used as actual route
  guards, and `POST /agents/{id}/calls/outbound` still gated by
  `agents.agent.read` instead of a dedicated start-call permission —
  **deliberately not changed**: renaming/adding RBAC permission checks
  without also confirming role-to-permission seed assignments risks locking
  everyone out of an endpoint. Flagged for a dedicated RBAC-audit pass.
- [ ] Payment-method collection is still manual-entry (no Stripe Elements —
  no `@stripe/stripe-js` dependency exists yet). Not revisited — this is a
  product decision (which payment processor UI to integrate), not a bug.

## Real verification round (2026-10-25, follow-up)

A throwaway venv was built (`pip install -r requirements.txt` worked fine —
this environment does have internet access even though it has no
preinstalled project venv) and used to **actually run** things previously
only hand-traced:

- `alembic history` against the rebuilt migration chain — confirmed
  `<base> → f3a1c9d04b7e → ad24a2368af2 → 0c6e2a9d7f41 (head)`, unbroken.
  (Still not run as `alembic upgrade head` against a real Postgres — Docker
  Desktop wouldn't start in this sandbox and no other Postgres was
  available. Do this before deploying.)
- **The full FastAPI app actually imports and all 115 routes register**
  (`app.openapi()`), including every new/changed endpoint from this
  remediation (`/agents/org-secrets*`, the new global `GET /calls`, the new
  `DELETE /agents/{id}/phone-numbers/{id}`, the de-collided
  `/agents/{id}/analytics/deep-dive`, the new SSE ticket endpoint). Zero
  import errors across the whole module graph.
- **The full `tests/unit/` suite runs — 53/53 pass**, including 18 new
  tests added in this round (see below) and the full pre-existing suite.
- `services/pipeline/tests/test_tool_executor.py` runs standalone (no
  pipecat import needed) — **43/43 pass**, including the two SQL-injection
  regression tests the pipeline-fix agent wrote (boolean and UNION payloads
  proven to bind as literal parameter values, never concatenated into the
  query string). This is the one pipeline-side fix with genuine executed
  verification rather than hand-tracing.
- The rest of `services/pipeline/tests/` (VAD/STT/TTS/interruption-handler
  tests) could **not** be run: `pipecat-ai`'s own import chain pulls in
  `loudness` and `soxr`, both native extensions whose `.pyd` files need the
  Microsoft Visual C++ runtime, which is not installed on this bare Windows
  sandbox (confirmed: `vcruntime140.dll`/`msvcp140.dll` absent from
  `System32`). This is a sandbox limitation, not a code bug — the real
  deployment target is the project's Linux Docker image, which installs its
  own native deps via `apt`. Given that, the `llm.py` (barge-in
  cancellation), `session_manager.py` (concurrency race fix), and
  `call_recorder.py` (temp-file spooling) fixes were instead verified by
  careful manual re-reading against their actual code (not just trusting
  the implementing agent's self-report) — all three held up: cancellation
  correctly discards history and doesn't leak the aiohttp connection, the
  lock is held only across the admit-decision (not the whole call), and
  `finish()`'s `try/finally` cleans up temp files on every path including
  early returns.
- Ran a live functional check (not just a test file) of the Fernet
  encrypt/decrypt roundtrip + `OrgSecretsService`'s full set/list/get/delete
  cycle with a mocked repository — confirmed ciphertext never matches
  plaintext, corrupted entries are skipped rather than raising, and
  org-not-found/invalid-key-format paths raise the right exceptions.

### New tests added (18), all passing

- `tests/unit/test_call_credits.py`: 9 new tests —
  `TestFeatureNotEnabledBlocks` (2, regression-proofing the "disabled
  feature must block, not grant unlimited" fix) and
  `TestConcurrentCallSlots` (7, using a real stateful fake-Redis counter —
  not a fixed-return mock — so the atomic INCR-then-compensate logic is
  actually exercised, including a full acquire/release/re-acquire lifecycle
  test).
- `tests/unit/test_agents_service.py` (new file, 9 tests): tenant-binding
  rejection/acceptance on `write_call_log`, credit-deduction +
  concurrency-slot-release wiring on terminal call status, the
  `ai.agents.max` limit check on `create_agent`, and `_build_agent_config`'s
  payload shape (the fix for the WebRTC/Twilio schema mismatch).

### A real bug this round of testing caught (not hand-traceable)

Writing `TestWriteCallLogCreditWiring` triggered `_dispatch_webhook`'s
actual exception path (its `WebhookService(session)` call fails against a
mocked session, which is exactly the scenario the `except Exception` there
is meant to handle gracefully) and that handler **itself crashed**:
`app/modules/agents/events.py` called `log.warning("...", event=event,
error=...)`, but structlog's logger already uses `event` as the reserved
name for the log message itself — passing it again as a kwarg raised
`TypeError: got multiple values for argument 'event'`. This means any real
webhook-delivery failure in production would have crashed the caller
instead of being silently logged and swallowed, as the module's own
docstring promises ("never raise"). Fixed by renaming the kwarg to
`webhook_event`. Grepped the whole `app/` tree for the same pattern — this
was the only occurrence.

## Not independently re-verified

- `alembic upgrade head` against a real Postgres (see above — chain
  structure confirmed, but not applied to a live DB).
- `services/pipeline/tests/` beyond `test_tool_executor.py` (sandbox-level
  native-dependency limitation, see above).
- Frontend was verified via `tsc --noEmit` (zero errors) but not run/clicked
  through in a browser against a live backend.

## Workstream log

- 2026-10-25: Audit completed (4 parallel sub-agents: pipeline/infra Days
  1-8, backend Days 9-16, frontend/SDK, tests/migrations/hygiene).
- 2026-10-25: Remediation executed as 4 parallel workstreams (backend core
  done directly in this session; infra, pipeline, and frontend each done by
  a dedicated agent on disjoint files) + follow-up consistency fixes
  (route collision, Qdrant api_key in `services/pipeline/processors/rag.py`,
  org-secrets management endpoints). All touched Python files verified to
  parse (`ast.parse`); all three `docker-compose*.yml` files verified via
  `docker compose config`; frontend verified via `tsc --noEmit`.
- 2026-10-25 (follow-up): closed remaining pending items — wired phone-number
  unassign into the frontend, added the global `GET /calls` endpoint +
  frontend table, fixed the SSE ticket-auth bug (discovered the endpoint
  was unreachable by any real browser, not just insecure), and removed the
  dead snake_case fallbacks in both SDK clients. Re-verified: backend
  files parse (`ast.parse`), frontend `tsc --noEmit` clean. No test runner
  or live DB was available in this environment (no venv, no `pytest`,
  no `sqlalchemy`/`fastapi` installed) — all verification was static.
