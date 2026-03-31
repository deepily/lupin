# Lupin REST API Quick Reference

> **Last Updated**: 2026.03.20
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

## 14. Claude Code (`/api/claude-code/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/claude-code/dispatch` | Public | Dispatch Claude Code task |
| POST | `/api/claude-code/{task_id}/inject` | Public | Inject message into session |
| POST | `/api/claude-code/{task_id}/interrupt` | Public | Interrupt running session |
| POST | `/api/claude-code/{task_id}/end` | Public | End session |
| GET | `/api/claude-code/{task_id}/status` | Public | Get task status |
| WebSocket | `/api/claude-code/ws/{task_id}` | Public | Stream task output |

## 15. Claude Code Queue

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/claude-code/queue/submit` | JWT | Queue Claude Code job via CJ Flow |

## 16. SWE Team (`/api/swe-team/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/swe-team/submit` | JWT | Submit SWE team job to queue |

## 17. Test Suite (`/api/test-suite/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/test-suite/submit` | JWT | Submit test suite job to queue (always monopolize) |

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
