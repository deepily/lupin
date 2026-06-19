# Lupin REST API Quick Reference

> **Last Updated**: 2026.06.12
>
> For detailed request/response schemas, see the interactive API docs at `/docs` (Swagger UI) or `/redoc` (ReDoc).

---

## Authentication Legend

| Symbol | Meaning |
|--------|---------|
| **Public** | No authentication required |
| **JWT** | Bearer token in `Authorization: Bearer <token>` header |
| **Admin** | JWT + `admin` role required |
| **API Key** | `X-API-Key` header |

---

## 1. Authentication (`/auth/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/auth/register` | Public | Create new user account |
| POST | `/auth/login` | Public | Authenticate and get tokens |
| POST | `/auth/refresh` | Public | Exchange refresh token for new pair |
| POST | `/auth/logout` | Public | Revoke refresh token |
| GET | `/auth/me` | JWT | Get current user profile |
| PUT | `/auth/change-password` | JWT | Change password (requires current) |
| POST | `/auth/request-verification` | JWT | Resend email verification link |
| POST | `/auth/verify-email` | Public | Verify email with token |
| POST | `/auth/request-password-reset` | Public | Request password reset email |
| POST | `/auth/reset-password` | Public | Reset password with token |

## 2. Admin (`/admin/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/admin/users` | Admin | List users with pagination and filters |
| GET | `/admin/users/{user_id}` | Admin | Get user details |
| PUT | `/admin/users/{user_id}/roles` | Admin | Update user roles |
| PUT | `/admin/users/{user_id}/status` | Admin | Activate/deactivate user |
| POST | `/admin/users/{user_id}/reset-password` | Admin | Generate temporary password |
| GET | `/admin/snapshots/search` | Admin | Search solution snapshots by query |
| GET | `/admin/snapshots/{id_hash}` | Admin | Get full snapshot details |
| DELETE | `/admin/snapshots/{id_hash}` | Admin | Delete snapshot |
| GET | `/admin/snapshots/{id_hash}/preview` | Admin | Get snapshot hover preview |
| GET | `/admin/snapshots/{id_hash}/similar` | Admin | Find similar snapshots |

## 3. System

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/` | Public | Health check with version |
| GET | `/health` | Public | Simplified health check |
| GET | `/api/init` | Public | Init configuration status |
| GET | `/api/get-session-id` | Public | Generate new session ID |
| GET | `/api/auth-test` | JWT | Verify token validity |
| GET | `/api/config/client` | JWT | Get client configuration values |
| GET | `/api/config/similarity-confirmation` | JWT | Get similarity confirmation setting |
| POST | `/api/config/similarity-confirmation` | JWT | Toggle similarity confirmation |
| GET | `/api/debug/websocket-state` | Public | Full WebSocket diagnostic state |

## 4. Queue Management

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/push` | JWT | Submit question to processing queue |
| GET | `/api/get-queue/{queue_name}` | JWT | Get queue contents (user-filtered) |
| GET | `/api/queue/pool-status` | JWT | CJ Flow agentic-pool state + per-provider API contention (Phase 2 core + Phase 3 `api_resource_manager` enrichment) |
| POST | `/api/reset-queues` | JWT | Clear all queues for current user |
| GET | `/api/get-job-interactions/{job_id}` | JWT | Get interaction history for a job |
| POST | `/api/jobs/{job_id}/message` | JWT | Send message to running job |
| GET | `/api/job-history` | JWT | Paginated job history (days, status, job_type, exclude_ids filters) |
| GET | `/api/job-history/{job_id}` | JWT | Single job detail by ID hash |
| DELETE | `/api/job-history/{job_id}` | JWT | Delete job from history (admin or owner) |
| POST | `/api/job-history/{job_id}/retry` | JWT | Retry failed/interrupted job |

## 5. Notifications (`/api/notify/*`)

> **Deep-dive**: See [`notification-api.md`](notification-api.md)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/notify` | API Key or JWT | Send notification to user |
| POST | `/api/notify/response` | JWT | Submit response to notification |
| GET | `/api/notifications/{user_id}` | Public | Get user notifications (with filters) |
| GET | `/api/notifications/{user_id}/next` | Public | Get next unplayed notification |
| POST | `/api/notifications/{notification_id}/played` | Public | Mark notification as played |
| DELETE | `/api/notifications/{notification_id}` | Public | Delete single notification |
| DELETE | `/api/notifications/bulk/{user_email}` | Public | Bulk delete by user (optional hours filter) |
| GET | `/api/notifications/senders/{user_email}` | Public | Get senders list with activity |
| GET | `/api/notifications/conversation/{sender_id}/{user_email}` | Public | Get sender-recipient conversation |
| DELETE | `/api/notifications/conversation/{sender_id}/{user_email}` | Public | Delete entire conversation |
| GET | `/api/notifications/conversation-by-date/{sender_id}/{user_email}` | Public | Conversation grouped by date |
| DELETE | `/api/notifications/date/{sender_id}/{user_email}/{date_string}` | Public | Soft-delete notifications by date |
| GET | `/api/notifications/sender-dates/{sender_id}/{user_email}` | Public | Date summaries for sender |
| GET | `/api/notifications/senders-visible/{user_email}` | Public | Visible senders (exclude hidden) |
| GET | `/api/notifications/active-conversation/{user_email}` | Public | Most recent sender conversation |
| GET | `/api/notifications/project-sessions/{project}/{user_email}` | Public | Sessions for project + user |
| POST | `/api/notifications/generate-gist` | Public | Generate 3-4 word session gist |

## 6. Speech I/O

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/upload-and-transcribe-mp3` | Public | Transcribe base64 MP3 via Whisper |
| POST | `/api/get-speech` | JWT | Generate TTS via OpenAI and stream to WebSocket |
| POST | `/api/get-speech-elevenlabs` | JWT | Generate TTS via ElevenLabs and stream to WebSocket |
| POST | `/api/upload-and-transcribe-wav` | Public | Transcribe WAV file upload via Whisper |
| WebSocket | `/api/ws/pcm-tts` | Public | Full-duplex streaming TTS (ElevenLabs PCM) |

## 7. Jobs (Stubs)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/delete-snapshot/{id}` | Public | Delete snapshot stub |
| GET | `/get-answer/{id}` | Public | Serve audio file stub |

## 8. Embeddings (`/api/embeddings/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/embeddings/generate` | JWT | Generate single embedding |
| POST | `/api/embeddings/batch` | JWT | Generate batch embeddings |
| GET | `/api/embeddings/info` | JWT | Get embedding engine info |

## 9. Mode (`/api/mode/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/mode/available` | JWT | List available modes |
| GET | `/api/mode/current` | JWT | Get current mode for user |
| POST | `/api/mode/current` | JWT | Set mode for user |
| DELETE | `/api/mode/current` | JWT | Clear mode (revert to system) |

## 10. Statistics (`/api/stats/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/stats/time-saved` | JWT | Personal time-saved stats |
| GET | `/api/stats/time-saved/global` | JWT | Global leaderboard stats |

## 11. Deep Research (`/api/deep-research/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research/submit` | JWT | Submit research job to queue |
| GET | `/api/deep-research/report` | Public | Retrieve research report (local or GCS) |
| GET | `/api/deep-research/health` | Public | Deep research subsystem health |

## 12. Podcast Generator (`/api/podcast-generator/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/podcast-generator/submit` | JWT | Submit podcast generation job |

## 13. Research-to-Podcast

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research-to-podcast/submit` | JWT | Submit chained research + podcast job |

## 14. Claude Code (`/api/claude-code/*`) — RETIRED 2026-05-05

> **Retired endpoints.** The legacy direct-dispatch + interactive-control cluster was eliminated on 2026-05-05 due to four catalogued structural defects (URL contract mismatch, no auth, module-level state, parallel pre-cj-flow path). Use **Section 15 (`/api/claude-code/queue/submit`)** instead — it is JWT-authenticated and rides the standard CJ Flow + WebSocketManager dispatch plane. See `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md`.

| Method | Path | Status |
|--------|------|--------|
| POST | `/api/claude-code/dispatch` | ❌ Retired 2026-05-05 → use `/api/claude-code/queue/submit` |
| POST | `/api/claude-code/{task_id}/inject` | ❌ Retired 2026-05-05 → INTERACTIVE control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/interrupt` | ❌ Retired 2026-05-05 → INTERACTIVE control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/end` | ❌ Retired 2026-05-05 → INTERACTIVE control parity pending on cj-flow path |
| GET | `/api/claude-code/{task_id}/status` | ❌ Retired 2026-05-05 → use job-card status via CJ Flow accordion |
| WebSocket | `/api/claude-code/ws/{task_id}` | ❌ Retired 2026-05-05 → progress now arrives via `/ws/queue/{session_id}` notifications keyed by `cc-*` job_id |

## 15. Claude Code Queue (active path)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/claude-code/queue/submit` | JWT | Queue Claude Code job via CJ Flow |

## 16. SWE Team (`/api/swe-team/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/swe-team/submit` | JWT | Submit SWE team job to queue |

## 17. Test Suite (`/api/test-suite/*`)

> **Deep-dive**: See [`agents/test-suite-scheduling-guide.md`](agents/test-suite-scheduling-guide.md)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/test-suite/submit` | JWT | Submit test suite job to queue (always monopolize). Accepts `test_types` (comma-separated or list), `pytest_args`, `scheduled_at` (ISO datetime), `dry_run`. Returns `{ job_id, status, scheduled_at, test_types, monopolize }`. Produces a remediation snapshot JSON + Markdown report at completion. |

## 17a. Bug Fix Expediter (`/api/push` with BFE command)

> **Deep-dive**: See [`agents/bug-fix-expediter-guide.md`](agents/bug-fix-expediter-guide.md)

BFE is submitted via the generic `/api/push` endpoint using the agent router command string. Used manually when curating which dead jobs get auto-recovery; automatic dispatch happens via the `DeadQueueWatchdog` when `bug fix expediter enabled = true` in INI.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/push` | JWT | Submit BFE job with `question = "agent router go to bug fix expediter"` and `args = { dead_job_id, extra_context (optional), dry_run (optional) }`. Returns `{ job_id }` with `bfe-` prefix. |

Watchdog auto-dispatch: requires `bug fix expediter enabled = true` in `lupin-app.ini`. See the BFE guide for full INI reference, trust-to-git mapping, and Phase 6 automated repair loop configuration.

## 17b. Test Fix Expediter (`/api/push` with TFE command)

> **Deep-dive**: See [`agents/test-fix-expediter-guide.md`](agents/test-fix-expediter-guide.md)

TFE is submitted via the generic `/api/push` endpoint using the agent router command string. Normally invoked automatically by `TestSuiteCompletionWatchdog` when a `TestSuiteJob` completes with failures; manual submission is supported for curated fix runs.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/push` | JWT | Submit TFE job with `question = "agent router go to test fix expediter"` and `args = { remediation_snapshot_path, source_test_suite_job_id, original_test_types (comma-separated), original_pytest_args (optional), dry_run (optional) }`. Returns `{ job_id }` with `tfe-` prefix. |

Watchdog auto-dispatch: requires `test fix expediter auto fix enabled = true` in `lupin-app.ini`. See the TFE guide for full INI reference (16 keys), six-phase pipeline, and the `TestSuiteCompletionWatchdog` eligibility gates.

## 17c. Inter-Session Commons (`/api/commons/*`)

> **Deep-dive**: See [`../rnd/v0.1.7/2026.05.09-inter-session-commons/`](../rnd/v0.1.7/2026.05.09-inter-session-commons/) (design + execution log) and [`notification-types.md`](notification-types.md) §`commons_broadcast_ack` for the ack notification contract.

The commons subsystem layers two related capabilities on the same file-backed transport (`<LUPIN_ROOT>/io/commons/*.md`):

1. **Session ↔ Session commons** — Claude Code instances post / read from a shared blackboard via the 5 cosa-voice MCP tools (`commons_post`, `commons_read`, `commons_who`, `commons_ask_sync`, `commons_ask_async`).
2. **User → All Sessions broadcast** — single message from the notifications UI fans out to every active CC session belonging to the authenticated user, with persona-aware directive parsing (`@PersonaName:` lines).

The endpoints below cover surface #2. The MCP tools are surface #1 and are not REST endpoints.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET    | `/api/commons/active-sessions`           | JWT | Returns same-user-scoped active CC sessions for the broadcast recipient preview. Same-user filter (per `user_id` on each bridge file) + freshness filter (`commons broadcast active session threshold seconds`, default 600). Response: `{ sessions: [{ session_id, persona_name, persona_icon, persona_color, last_seen_iso, speakerphone_on }] }`. Never leaks bridge filesystem paths. |
| POST   | `/api/commons/broadcast-to-cc-sessions`  | JWT | Fans out a message to every active CC session belonging to the caller. Body: `{ message, broadcast_id?, require_ack=true, include_originator=true }`. Rate-limited at 1 broadcast per `commons broadcast rate limit seconds` (default 30) per `user_id`; exceeded → `HTTP 429` with `Retry-After` header. Body containing literal `<system-reminder>` / `</system-reminder>` substring → `HTTP 400`. Caller-supplied `broadcast_id` colliding with an in-flight broadcast → `HTTP 409`. Zero recipients → `HTTP 200` with `status="no-active-sessions"`. Success → `HTTP 200` with `{ broadcast_id, recipients, failed_recipients, filtered_out, status="queued" }`. `filtered_out[]` (**2026-06-11 fanout receipts**) lists every enumerated session the recipient filter dropped — `{ session_id, reason }`, reason ∈ `bridge_unreadable` / `owner_mismatch` / `stale_bridge_mtime` (adds `age_seconds` + `threshold_seconds`) / `bridge_vanished` / `originator_excluded` — present in BOTH 200 shapes so a silent miss is visible to the sender. When `require_ack=true`, downstream `commons_broadcast_ack` notifications stream in via the existing `notification_queue_update` envelope as each recipient listener acks. |
| GET    | `/api/commons/broadcast-history`         | JWT | **NEW 2026-05-14** — Aggregates entries across all commons topics (minus the configurable blacklist; defaults to `presence` + `system-events` per Q5) and returns them newest-first, scoped to the authenticated user. Powers the broadcast-card Recent Activity admin-oversight stream (Phase 2.5/3.5). Query params: `since` (ISO cutoff), `hours` (back-window from now; e.g. `today`-equivalent), `limit` (default 200; capped server-side by `commons traffic visibility max entries per response`, default 1000). Response: `{ entries: [{ ts, topic, topic_kind: "reserved"\|"free-form", sender_session_id, persona_name, persona_icon, persona_color, body, metadata }], since_used, next_cursor }`. When the master INI flag `commons traffic visibility enabled` is False, returns `{ entries: [], since_used: null, next_cursor: null, disabled: true }`. Same-user scoping mirrors `/active-sessions`: graceful-degradation for un-stamped legacy bridges (`owner_user_id == None` passes through). Design: [`../rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md`](../rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md). |

### Broadcast directive parsing

`message` body is free-form text with optional `@PersonaName:` directive lines:

```text
Run the daily smoke check on master.
@Maria: also re-baseline the visual snapshots.
```

Default lines (no leading `@`) apply to every recipient. `@PersonaName:` lines apply only to sessions whose persona matches (case-insensitive + punctuation-tolerant per `commons_persona_matcher.match_persona`). `@all:` / `@everyone:` aliases match the default scope. Sessions whose persona doesn't match any `@` line — and the body has no default lines — ack with `status="skipped"`.

### Ack flow

When `require_ack=true`:

1. Server registers the `broadcast_id` in the `CommonsAckWatcher` in-flight tracker (5-min TTL).
2. Per-recipient fanout writes one entry to the `broadcasts` reserved topic + pushes one `user_initiated_message` notification with `title="action:broadcast_received"` to each listener.
3. Each listener's `_handle_action()` dispatcher routes to `broadcast_handler.handle_broadcast()`, which parses the directive, injects the effective text as a `<system-reminder>` block, and posts an ack to the `broadcast-acks` reserved topic.
4. `CommonsAckWatcher` daemon (poll every `commons broadcast ack watch interval seconds`, default 1) tails `broadcast-acks` and dispatches one `commons_broadcast_ack` notification per ack to the originating user — see [`notification-types.md`](notification-types.md) for the payload shape.

When `require_ack=false`: steps 1–3 still happen, but no acks fan back to the user — the watcher's in-flight tracking is skipped for this broadcast.

### INI configuration

| Key | Default | Effect |
|---|---|---|
| `commons broadcast rate limit seconds` | `30` | Per-user sliding-window rate limit |
| `commons broadcast active session threshold seconds` | `600` | Inactivity threshold (s) — sessions older than this are excluded from fanout |
| `commons broadcast ack watch interval seconds` | `1` | Poll period for the `CommonsAckWatcher` daemon |

Paired splainer entries are in `src/conf/lupin-app-splainer.ini`.

## 18. Decision Proxy (`/api/proxy/*`)

> **Deep-dive**: See [`proxy-admin-guide.md`](proxy-admin-guide.md)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/proxy/acknowledge` | Public | Retire current batch, start new one |
| GET | `/api/proxy/batch-id` | Public | Get current proxy batch ID |
| GET | `/api/proxy/pending/{user_email}` | Public | Get pending decisions |
| POST | `/api/proxy/ratify/{decision_id}` | Public | Approve or reject decision |
| DELETE | `/api/proxy/decision/{decision_id}` | Public | Hard-delete decision |
| GET | `/api/proxy/trust/{user_email}` | Public | Get trust state for user |
| GET | `/api/proxy/decisions/{domain}/{category}` | Public | Decision history by domain/category |
| GET | `/api/proxy/mode` | JWT | Get current trust mode |
| PUT | `/api/proxy/mode` | JWT | Update trust mode |

## 19. Mock Job (`/api/mock-job/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/mock-job/submit` | JWT | Submit mock job for queue UI testing |
| GET | `/api/mock-job/health` | Public | Mock job subsystem health |

## 20. I/O Files (`/api/io/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/io/file` | Public | Serve file from io/ directory |
| GET | `/api/io/health` | Public | I/O subsystem health |

## 21. WebSocket Admin (`/api/websocket-sessions/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/websocket-sessions` | JWT | List all active sessions |
| GET | `/api/websocket-sessions/stats` | JWT | Connection statistics |
| POST | `/api/websocket-sessions/cleanup` | JWT | Remove stale sessions |
| GET | `/api/websocket-sessions/{session_id}` | JWT | Get session details |
| DELETE | `/api/websocket-sessions/{session_id}` | JWT | Force-disconnect session |
| PUT | `/api/websocket-sessions/single-session-policy` | JWT | Toggle single-session policy |
| GET | `/api/websocket-events` | JWT | List available event types |

---

## 22. WebSocket Connections (`/ws/*`)

> **Deep-dive**: See [`websocket-architecture.md`](websocket-architecture.md)

| Type | Path | Auth | Summary |
|------|------|------|---------|
| WebSocket | `/ws/queue/{session_id}` | JWT (first message) | Main application WebSocket |
| WebSocket | `/ws/audio/{session_id}` | Optional | Audio-only TTS streaming |

**Authentication**: First message on `/ws/queue` must be `{ type: "auth_request", token: "Bearer ..." }`.

**Session ID format**: Two lowercase words (e.g., "wise penguin").

---

## 23. Pages (`/app/*`)

> UI page routes. All return HTML. Not in OpenAPI schema. Auth enforced client-side via JS JWT validation.

| Path | Page |
|------|------|
| `/app` | Landing page |
| `/app/notifications` | Notifications dashboard |
| `/app/auth/login` | Login form |
| `/app/auth/register` | Registration form |
| `/app/auth/profile` | User profile |
| `/app/auth/change-password` | Password change |
| `/app/admin` | Admin dashboard |
| `/app/admin/users` | User management |
| `/app/admin/snapshots` | Snapshot admin |
| `/app/admin/proxy-ratify` | Proxy ratification |
| `/app/admin/proxy-dashboard` | Trust dashboard |
| `/app/admin/dev-tools` | Developer tools |

## 24. Multiplexer (`/api/multiplexer/*`)

> Front-end client-config exposer. Returns display-tuning values fetched once at boot by `/static/js/multiplexer/boot.ts`. No auth required (display tuning, no PII or state).

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/multiplexer/config` | None | Multiplexer client-config (boot-time tuning values) |

---

## 25. FCM Wake Push (`/api/fcm/*`)

> Mobile silent-relay wake channel (S6). The mobile app registers its FCM device token; the parent fires a content-free, data-only `ws_wake` push when a notification is enqueued for a user with no live WebSocket session marked `client_type: "mobile"` (web sessions never suppress the wake). Tokens persist in the `fcm_tokens` table. Spec: `src/lupin-mobile/src/rnd/2026.06.11-focus-mode-voice-chat/15-section-s6-fcm-backend-interface.md`.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/fcm/register-token` | JWT | Register device token. Body `{ token, platform, user_email }` → `{ "status": "ok" }`. Upsert keyed on token; multiple devices per user. |
| POST | `/api/fcm/unregister-token` | JWT | Unregister device token (best-effort logout). Body `{ token }` → `{ "status": "ok" }`, idempotent. |

---

## Job ID Prefixes

| Prefix | Job Type | Submit Endpoint |
|--------|----------|-----------------|
| `dr-` | Deep Research | `/api/deep-research/submit` |
| `pg-` | Podcast Generator | `/api/podcast-generator/submit` |
| `rp-` | Research-to-Podcast | `/api/deep-research-to-podcast/submit` |
| `cc-` | Claude Code | `/api/claude-code/queue/submit` |
| `swe-` | SWE Team | `/api/swe-team/submit` |
| `ts-` | Test Suite | `/api/test-suite/submit` |
| `bfe-` | Bug Fix Expediter | `/api/push` with `"agent router go to bug fix expediter"` |
| `tfe-` | Test Fix Expediter | `/api/push` with `"agent router go to test fix expediter"` |
| `mock-` | Mock Job | `/api/mock-job/submit` |

---

## Cross-Reference: Deep-Dive Documentation

| Topic | Document |
|-------|----------|
| Notification system | [`notification-api.md`](notification-api.md) |
| Decision proxy | [`proxy-admin-guide.md`](proxy-admin-guide.md) |
| WebSocket architecture | [`websocket-architecture.md`](websocket-architecture.md) |
| WebSocket events | [`websocket-events.md`](websocket-events.md) |
| WebSocket troubleshooting | [`websocket-troubleshooting.md`](websocket-troubleshooting.md) |
| Interactive testing | [`automated-interactive-testing.md`](automated-interactive-testing.md) |
| Frontend architecture | [`lupin-mpa-frontend-architecture.md`](lupin-mpa-frontend-architecture.md) |
