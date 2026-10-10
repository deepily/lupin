> Part 3 of 9 of the [Lupin REST API Quick Reference](../rest-api-reference.md): routes 1 to 7: auth, admin, system, queue, notify.

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
| GET | `/` | Public | Health check with version + `code_identity` |
| GET | `/health` | Public | Simplified health check (2 fields only, by choice — backs a 30s docker healthcheck) |
| GET | `/api/code-identity` | Public | Which code the running process holds — captured at module import, never re-read |
| GET | `/api/init` | Admin | Hot-reload config; `?config_block_id=` also swaps the running DB connection. Admin-only — it was `Public` before, which is what made it a P1 |
| POST | `/api/prediction-engine/reset` | Auth | Reset the PredictionEngine singleton; `?drop_table=true` clears the decision rows. If the clear fails the singleton is still reset but the answer is `status: error` with `table_dropped: false`. Was an **unauthenticated GET whose `drop_table` defaulted to true** — hardened to POST + credential + default false |
| GET | `/api/get-session-id` | Public | Generate new session ID. Warning: Not read-only: it grows `TwoWordIdGenerator.generated_ids`, a process-lifetime set that is never pruned |
| GET | `/api/auth-test` | JWT | Verify token validity |
| GET | `/api/config/client` | JWT | Get client configuration values |
| GET | `/api/config/similarity-confirmation` | JWT | Get similarity confirmation setting |
| POST | `/api/config/similarity-confirmation` | JWT | Toggle similarity confirmation |
| GET | `/api/debug/websocket-state` | Public | Full WebSocket diagnostic state |

## 4. Queue Management

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/push` | — | 🪦 **Gone (410)** — use `/api/v2/ask`. Remove by end of 2026. |
| POST | `/api/push-agentic` | — | 🪦 **Gone (410)** — use `/api/v2/submit`. Remove by end of 2026. It was the closest thing to `submit` that already existed: `routing_command` becomes `command`, `websocket_id` becomes optional. And `args` / `question` / `scheduled_at` / `monopolize` keep their names. |
| GET | `/api/get-queue/{queue_name}` | JWT | Get queue contents (user-filtered) |
| GET | `/api/queue/pool-status` | JWT | CJ Flow agentic-pool state + per-provider API contention (core state, plus the `api_resource_manager` enrichment) |
| POST | `/api/reset-queues` | JWT | Clear all queues for current user |
| GET | `/api/get-job-interactions/{job_id}` | JWT | Get interaction history for a job |
| POST | `/api/jobs/{job_id}/message` | JWT | Send message to running job |
| GET | `/api/job-history` | JWT | Paginated job history (days, status, job_type, exclude_ids filters) |
| GET | `/api/job-history/{job_id}` | JWT | Single job detail by ID hash |
| DELETE | `/api/job-history/{job_id}` | JWT | Delete job from history (admin or owner) |
| POST | `/api/job-history/{job_id}/retry` | — | 🪦 **Gone (410)** — use `/api/v2/ask`. Remove by end of 2026. |
| POST | `/api/jobs/{id_hash}/resume-from-checkpoint` | — | 🪦 **Gone (410)** — use `/api/v2/resume-job` with `{ "resume_from": "<id_hash>" }` plus the same optional overrides. Remove by end of 2026. |
| POST | `/api/v2/resume-job` | JWT | Resume a stalled job from its checkpoint and queue the new job. Body `{ resume_from, lead_model_override?, worker_model_override?, thinking_effort? }`. 200 `{ status: resumed, resumed_job_id, original_job_id, resume_from_phase, phase_name, resume_count, queue_position, source_type, … }` or `{ status: ambiguous, candidates, diagnostic }` (nothing queued) · 404 unknown / not stalled / no checkpoint · 401 identity · 422 empty `resume_from`. Not behind `v2 flow enabled`. Not `/api/v2/resume`, which answers a parked question |

## 5. Notifications (`/api/notify/*`)

> **Deep-dive**: See [`notification-api.md`](../notification-api.md)

Warning: **Every row's `Auth` below was re-derived from the router, not copied forward**.
Fifteen rows read `Public` and none of them was.
Twelve are owner-gated by `require_path_identity_owner`, and three take any valid credential.
Eight routes were missing from the table altogether.
Walking `router.routes` and following each route's dependency tree shows **24 of 24 notification routes gated and 0 open**.
That measurement reads the definition, which is the weaker instrument: a path measurement can disagree with it.

Warning: **A wrong reassurance costs more than a wrong instruction**.
A reader who follows a bad instruction finds out.
A reader told these are `Public` believes the hole is already known and does not look.
The pass that produced this table was sent to fix twelve rows. Three more were wrong and eight were absent.
That is why the population was re-derived rather than patched.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/notify` | API Key or JWT | Send notification to user |
| POST | `/api/notify/response` | JWT | Submit response to notification |
| POST | `/api/notify/prediction-vote/{notification_id}` | Credential | Vote on a prediction-engine suggestion |
| GET | `/api/notifications/{user_id}` | Owner | Get user notifications (with filters) |
| GET | `/api/notifications/{user_id}/next` | Owner | Get next unplayed notification |
| POST | `/api/notifications/{notification_id}/played` | Credential | Mark notification as played |
| DELETE | `/api/notifications/{notification_id}` | Credential | Delete single notification |
| GET | `/api/notifications/response/{notification_id}` | Credential | Read the response submitted to a notification |
| DELETE | `/api/notifications/bulk/{user_email}` | Owner | Bulk delete by user (optional hours filter) |
| GET | `/api/notifications/senders/{user_email}` | Owner | Get senders list with activity |
| GET | `/api/notifications/conversation/{sender_id}/{user_email}` | Owner | Get sender-recipient conversation |
| DELETE | `/api/notifications/conversation/{sender_id}/{user_email}` | Owner | Delete entire conversation |
| GET | `/api/notifications/conversation-by-date/{sender_id}/{user_email}` | Owner | Conversation grouped by date |
| DELETE | `/api/notifications/date/{sender_id}/{user_email}/{date_string}` | Owner | Soft-delete notifications by date |
| GET | `/api/notifications/sender-dates/{sender_id}/{user_email}` | Owner | Date summaries for sender |
| GET | `/api/notifications/senders-visible/{user_email}` | Owner | Visible senders (exclude hidden) |
| GET | `/api/notifications/active-conversation/{user_email}` | Owner | Most recent sender conversation |
| GET | `/api/notifications/project-sessions/{project}/{user_email}` | Owner | Sessions for project + user |
| POST | `/api/notifications/generate-gist` | Credential | Generate 3-4 word session gist |
| GET | `/api/notifications/answers-owed` | Credential | Questions this caller still owes an answer to |
| POST | `/api/notifications/answers-owed/ack` | Credential | Acknowledge an owed-answer item |
| GET | `/api/notifications/undelivered` | Credential | Notifications not yet delivered to this caller |
| GET | `/api/notifications/awaiting-response` | Credential | Response cards still waiting for an answer, as a live push carries them. Both pages draw these at load |
| POST | `/api/notifications/undelivered/dismiss` | Credential | Dismiss an undelivered notification |
| GET | `/api/notifications/broadcast-acks/{broadcast_id}` | Credential | Acks collected for one broadcast |

**Reading the `Auth` column here**.

- `Owner` is `require_path_identity_owner`: 401 with no valid credential, then 403 unless the user named in the path is the caller. It is owner-only, with no admin bypass.
- `Credential` is `require_api_key_or_jwt`: any valid API key or Bearer token, with no second check.
- `JWT` is a Bearer token specifically.

## 6. Speech I/O

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/upload-and-transcribe-mp3` | Public | Transcribe base64 MP3 via Whisper |
| POST | `/api/get-speech` | JWT | Generate TTS via OpenAI and stream to WebSocket |
| POST | `/api/get-speech-elevenlabs` | JWT | Generate TTS via ElevenLabs and stream to WebSocket |
| POST | `/api/upload-and-transcribe-wav` | Public | Transcribe WAV file upload via Whisper |
| POST | `/api/v2/ask-audio` | JWT | Spoken `/api/v2/ask`: multipart `file` (any audio; the filename's extension picks the decoder), query `websocket_id`, `speak`, `interactive`. Streams `application/x-ndjson`: a `transcript` line, then an `ask` line holding the full AskResponse, or an `error` line if the ask fails after the transcript. Contract fixture: `src/tests/fixtures/ask_audio_ndjson_contract.json` |
| POST | `/api/v2/transcribe` | JWT | Transcribe only, nothing asked: multipart `file`, its extension (`.ogg`, `.wav`) picks the decoder. Returns JSON `{ transcription, trace: { stt_ms, upload_bytes } }`. 401 identity · 422 missing file part, empty upload, or no speech · 503 + `Retry-After: 5` on GPU OOM · 500 `Could not transcribe the audio.` Not behind `v2 flow enabled`. Replaces the phone's use of `/api/upload-and-transcribe-wav` |
| WebSocket | `/api/ws/pcm-tts` | Public | Full-duplex streaming TTS (ElevenLabs PCM) |

## 7. Jobs (Stubs)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/delete-snapshot/{id}` | Public | Delete snapshot stub |
| GET | `/get-answer/{id}` | Public | Serve audio file stub |
