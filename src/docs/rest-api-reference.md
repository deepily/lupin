# Lupin REST API Quick Reference

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

## 🪦 Retired queue doors — gone (410), remove by end of 2026

Rick ruled that there is one entry point, and it is v2. Eighteen routes used to put work on the queue; sixteen are retired.
Each retired route stays registered on purpose and answers **410 Gone** with a body naming its replacement.
A deleted route is invisible, and nothing would stop someone re-adding it because the product needs it.
These stubs are removed by the end of 2026.

**The survivors**:

- `POST /api/v2/ask`: a bare question, which the router routes.
- `POST /api/v2/submit`: work whose command is already decided.
- `POST /api/v2/resume`: resume a parked question.
- `POST /api/v2/resume-job`: resume a stalled job from its checkpoint.
- `POST /api/v2/ask-audio`: `/api/v2/ask` with the question spoken. It transcribes, then asks through the same flow, so it is not a separate way onto the queue (see the Speech I/O section).

**Retired so far:**

| Retired door | Use instead |
|---|---|
| `POST /api/push` | `/api/v2/ask` |
| `POST /api/job-history/{job_id}/retry` | `/api/v2/ask` |
| `POST /api/bug-fix-expediter/submit` | `/api/v2/submit` |
| `POST /api/deep-research/submit` | `/api/v2/submit` |
| `POST /api/deep-research-to-podcast/submit` | `/api/v2/submit` |
| `POST /api/deep-research-to-presentation/submit` | `/api/v2/submit` |
| `POST /api/presentation-generator/submit` | `/api/v2/submit` |
| `POST /api/podcast-generator/submit` | `/api/v2/ask` |
| `POST /api/swe-team/submit` | `/api/v2/submit` |
| `POST /api/push-agentic` | `/api/v2/submit` |
| `POST /api/jobs/{id_hash}/resume-from-checkpoint` | `/api/v2/resume-job` |
| `POST /api/test-fix-expediter/resume-from` | `/api/v2/resume-job` |
| `POST /api/mock-job/submit` | `/api/v2/submit` |
| `POST /api/test-suite/submit` | `/api/v2/submit` |

The two question-shaped doors went first, when `/api/v2/ask` was the only live replacement.
The submit-shaped ones had to wait until `/api/v2/submit` existed and could build an agentic job.
A 410 naming a route that answers "I do not understand" teaches a caller less than the error it replaced.

`/api/podcast-generator/submit` is the one job-queueing door that retires into `ask` rather than `submit`.
Its description flow asked the user which document they meant, and which languages and audience they wanted.
It could also answer "cancelled". That is a conversation, which `ask` holds and `submit` refuses to hold by design.

**No queue door is left live**. `/api/test-suite/submit` retired last.
Rick ruled "retire after v2 gap". The gap was `queue_position`, now `AskResponse.queue_position`.
It is the todo queue's size right after the push, and null when nothing was queued. Every in-repo caller has moved.

A test-suite job is now `POST /api/v2/submit` with this body:

```json
{ "command": "agent router go to test suite",
  "args": { "test_types", "pytest_args", "dry_run", "auto_fix_on_failure", "env_vars" },
  "scheduled_at": "<optional>" }
```

The job forces `monopolize` itself. **What differs for a caller**:

- Success is `status: "waiting"`, not `queued`.
- A refused submit is **HTTP 200 with `status: "failed"` and the cause in `error`**, not the 400 the old door answered.
- A refusal covers an unknown suite name and malformed or contradictory `pytest_args`.

`cosa.agents.test_suite.v2_client` builds the body and reads the reply.

**The mock-job door retired**. Rick ruled to keep what it does.
The earlier "0 callers" figure counted shipped code only. Four test suites called it: the 12-scenario proxy suite, the swe-team proxy suite, the expeditor mock-job smoke and the CJ Flow pause/schedule e2e.
So its two modes became one command, `agent router go to mock job`, on `POST /api/v2/submit`.
That command is test scaffolding: it is not speakable and is not on the router prompt or card.

- **plain** (no `voice_command`) queues a zero-cost `MockAgenticJob`.
- **expeditor test** (`voice_command` given) runs the `RuntimeArgumentExpeditor`. It queues a dry-run job of the command it matches, with optional `force_failure_mode`.

Arguments go in `args`. `scheduled_at`, `monopolize` and `websocket_id` are top-level.
The response differs from the old door's:

- `status` is `waiting`, not `queued`.
- The old `config` dict is at `submit_details.config`.
- A cancelled interview is `status: failed` with `route_reason: expeditor_cancelled`.

The suites share `src/tests/helpers/mock_job_v2.py`, which maps a v2 response back to the old shape.
`GET /api/mock-job/health` is unchanged.

**The two resume doors retired**. Rick ruled: "build v2 resume, then retire".
They rebuild a job from server-side state, which a `SubmitRequest` cannot express. They needed a verb of their own: `POST /api/v2/resume-job`.
One body serves both kinds:

```json
{ "resume_from": "<job id_hash | tfe id | plan path | description>",
  "lead_model_override": "?", "worker_model_override": "?", "thinking_effort": "?" }
```

A job-id-shaped `resume_from` (not `tfe-`) goes straight to the factory, as door 6 did.
Anything else goes through the TFE resolver, as door 7 did, including its `ambiguous` answer.

**The direct path checks ownership**. The caller must own the job or be an admin.
Ownership is the owner on the `job_history` row, never the id string's suffix.
A non-owner, an unknown id and a row with no owner all get the same 404, so the answer does not reveal which ids exist.

**The Claude Code pair retired, and the upgrade is what made that possible**.
`/api/claude-code/submit` and its alias `/api/claude-code/queue/submit` (one handler) both answer 410 naming `/api/v2/submit`.
Rick ruled that the Claude Code job be upgraded to the front door rather than left to die.
The tombstone is the second half of that ruling, not a contradiction of it.
The work still runs, through `{"command": "agent router go to claude code", "args": {…}}`.

**One more route is a permanent survivor, not a door awaiting its turn**.
`/api/upload-and-transcribe-mp3` was in the retirement table and came back out the same day.
It is not a queue door. It accepts base64 MP3, transcribes with Whisper and runs the result through `MultiModalMunger`.
It queues only on the `munger.is_agent()` branch. The other branch returns the transcription and queues nothing.
`/api/v2/ask` takes text and cannot accept audio.
Retiring the route would take browser dictation, the admin snapshot search and the multiplexer's insert-at-cursor down with it, and offer them nothing in exchange.

Its enqueue branch has already moved. The `is_agent()` path calls `ask_flow.ask(...)` in-process and refuses without a signed-in user (`routers/speech.py`).
No `push_job` is left on this route.
Rick's framing: there are two ways to ask, post your text or speak it, and both end at the same flow.
Nothing further is owed here, and the route is not scheduled for removal.
It was checked against `RETIRED_DOORS`, which does not list it.

**Two separately-managed repos still call the retired doors**: `src/lupin-mobile` and `src/lupin-plugin-firefox`.
Neither can be edited from this repo. Their cutover is owed work in each repo.
The 410 body names the replacement, so the fix is discoverable from the failure. That is the whole mitigation.

Warning: **`/api/v2/ask` is not a drop-in for `/api/push`**.
`push` queued the job and returned `{status: "queued", job_id, …}` for the WebSocket to follow up on.
`ask` answers synchronously and returns an `AskResponse`.
It also validates with a Pydantic model, so a malformed body comes back **422, not 400**.
A caller cutting over changes how it reads the result, not only where it posts.
`AskResponse.queue_position` is the one v1 field with a v2 counterpart.
It is the todo queue's size right after a queued job was pushed: a snapshot, not a live position.
It is null on every path that queued nothing.

`AskRequest.parent_id_hash` is optional.
It is the id of the monopolizing job on whose behalf the ask is made, with the same meaning as on `/api/v2/submit`.
Under `v2 executor = queued` the executor stamps it on the job as `spawned_by_id_hash`.
The consumer's intake hold then admits the job as a lineage child instead of deferring it as foreign.
Absent, nothing changes.

The test-suite runner exports its id as `LUPIN_TEST_MONOPOLIZE_PARENT_ID`, which `v2_eval.py` echoes.
A fresh user who is not an admin, the test account or the parent's owner can still carry the claim.
They send the per-run suite token in the `X-Lupin-Lineage-Token` header, on either door, while that run holds the monopoly slot.
The server accepts the token only where `v2 parent stamp token enabled = true` (Development and Testing).

A refused claim drops the stamp with a reason word in `parent_id_hash_dropped`.
One case answers **403** instead, on either door, with the reason word in the body (`detail.error` is `parent_id_hash_refused`).
That case is a claim naming the test-suite job that holds the monopoly slot right now.
The 403 stops a suite's own child waiting behind the suite for the whole run.
The token is never logged, traced or echoed.

**Table of record**: `src/cosa/rest/routers/_retired_doors.py`. **Test**:
`src/tests/unit/test_retired_queue_doors_410.py`.

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
| GET | `/` | Public | Health check with version + `code_identity` |
| GET | `/health` | Public | Simplified health check (deliberately 2 fields — backs a 30s docker healthcheck) |
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

> **Deep-dive**: See [`notification-api.md`](notification-api.md)

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
| POST | `/api/deep-research/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to deep research"`. Remove by end of 2026. |
| GET | `/api/deep-research/report` | Public | Retrieve research report (local or GCS) |
| GET | `/api/deep-research/health` | Public | Deep research subsystem health |

## 12. Podcast Generator (`/api/podcast-generator/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/podcast-generator/submit` | — | 🪦 **Gone (410)** — use `/api/v2/ask` (it retires into `ask`, not `submit`: its description path held a conversation). Remove by end of 2026. |

## 12a. Presentation Generator (`/api/presentation-generator/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/presentation-generator/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to presentation generator"`. Remove by end of 2026. |

The door carried a path-escape check that nothing downstream repeated.
The guard moved onto the job (`presentation_generator/job.py`) in its own earlier commit, and the retirement waited for it.
Retiring the door first would have left a window with no check at all.

## 13. Research-to-Podcast

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research-to-podcast/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to research to podcast"`. Remove by end of 2026. |

## 13a. Research-to-Presentation

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research-to-presentation/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to research to presentation"`. Remove by end of 2026. |

## 14. Claude Code (`/api/claude-code/*`) — retired

**Retired endpoints**. The legacy direct-dispatch and interactive-control cluster was eliminated.
Four catalogued structural defects caused it: a URL contract mismatch, no auth, module-level state and a parallel pre-cj-flow path.
Use **`/api/v2/submit`** instead. It is JWT-authenticated and rides the standard CJ Flow and WebSocketManager dispatch plane.
Section 15 records the two `/api/claude-code/*` tombstones that replaced the cluster and were themselves retired.
See `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md`.

| Method | Path | Status |
|--------|------|--------|
| POST | `/api/claude-code/dispatch` | ❌ Retired → use `/api/v2/submit` (the `/api/claude-code/queue/submit` it originally named is itself 410) |
| POST | `/api/claude-code/{task_id}/inject` | ❌ Retired → interactive control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/interrupt` | ❌ Retired → interactive control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/end` | ❌ Retired → interactive control parity pending on cj-flow path |
| GET | `/api/claude-code/{task_id}/status` | ❌ Retired → use job-card status via CJ Flow accordion |
| WebSocket | `/api/claude-code/ws/{task_id}` | ❌ Retired → progress now arrives via `/ws/queue/{session_id}` notifications keyed by `cc-*` job_id |

## 15. Claude Code Queue (retired — use `/api/v2/submit`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/claude-code/submit` | none | ❌ Retired → 410 Gone, use `/api/v2/submit` (remove by end of 2026) |
| POST | `/api/claude-code/queue/submit` | none | ❌ Retired → 410 Gone, use `/api/v2/submit` (remove by end of 2026) |

A tombstone carries no auth dependency on purpose.
An unauthenticated caller must learn the same thing an authenticated one does.
A 401 teaches nobody anything.

```json
POST /api/v2/submit
{
  "command"      : "agent router go to claude code",
  "args"         : { "prompt": "…", "project": "lupin", "task_type": "BOUNDED",
                     "max_turns": 50, "dry_run": false },
  "websocket_id" : "<session id>",
  "scheduled_at" : "2026-08-22T11:00:00-04:00"
}
```

`prompt` / `project` / `task_type` / `max_turns` / `dry_run` are arguments to the job. So
they go in `args`. `websocket_id` / `scheduled_at` / `monopolize` are directives to the
queue and stay top-level. `task_type` must be `BOUNDED` or `INTERACTIVE`. Anything else is
refused when the job is built.

## 16. SWE Team (`/api/swe-team/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/swe-team/submit` | — | 🪦 **Gone (410)** — use `/api/v2/submit` with `"agent router go to swe team"`; `parent_id_hash` is top-level there. Remove by end of 2026. |

## 17. Test Suite (`/api/test-suite/*`)

> **Deep-dive**: See [`agents/test-suite-scheduling-guide.md`](agents/test-suite-scheduling-guide.md)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/test-suite/submit` | — | 🪦 **Gone (410)**. Use `/api/v2/submit` with `"agent router go to test suite"` (suite arguments in `args`; `scheduled_at` top-level; a refused submit is HTTP 200 with `status: "failed"`, not a 400). Remove by end of 2026. |

## 17a. Bug Fix Expediter (`/api/v2/ask` with BFE command)

> **Deep-dive**: See [`agents/bug-fix-expediter-guide.md`](agents/bug-fix-expediter-guide.md)

BFE is submitted via the generic `/api/v2/ask` endpoint using the agent router command string (`/api/push` was retired and answers 410). Used manually when curating which dead jobs get auto-recovery; automatic dispatch happens via the `DeadQueueWatchdog` when `bug fix expediter enabled = true` in INI.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/v2/ask` | JWT | Submit BFE job with `question = "agent router go to bug fix expediter"` and `args = { dead_job_id, extra_context (optional), dry_run (optional) }`. Returns `{ job_id }` with `bfe-` prefix. |
| POST | `/api/bug-fix-expediter/submit` | — | 🪦 **Gone (410)** — remove by end of 2026. Its refusal names `/api/v2/submit`, which accepts the decided command; the row above is the same job asked as a question through `/api/v2/ask`. Both reach BFE. |

Watchdog auto-dispatch: requires `bug fix expediter enabled = true` in `lupin-app.ini`. See the BFE guide for full INI reference, trust-to-git mapping, and the automated repair loop configuration.

## 17b. Test Fix Expediter (`/api/v2/ask` with TFE command)

> **Deep-dive**: See [`agents/test-fix-expediter-guide.md`](agents/test-fix-expediter-guide.md)

TFE is submitted via the generic `/api/v2/ask` endpoint using the agent router command string (`/api/push` was retired and answers 410). Normally invoked automatically by `TestSuiteCompletionWatchdog` when a `TestSuiteJob` completes with failures; manual submission is supported for curated fix runs.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/v2/ask` | JWT | Submit TFE job with `question = "agent router go to test fix expediter"` and `args = { remediation_snapshot_path, source_test_suite_job_id, original_test_types (comma-separated), original_pytest_args (optional), dry_run (optional) }`. Returns `{ job_id }` with `tfe-` prefix. |
| POST | `/api/test-fix-expediter/resume-from` | — | 🪦 **Gone (410)** — use `/api/v2/resume-job` with `{ "resume_from": "<tfe id, plan path, or description>" }`. Remove by end of 2026. |

Watchdog auto-dispatch: requires `test fix expediter auto fix enabled = true` in `lupin-app.ini`. See the TFE guide for full INI reference (16 keys), six-phase pipeline, and the `TestSuiteCompletionWatchdog` eligibility gates.

## 17c. Inter-Session Commons (`/api/commons/*`)

> **Deep-dive**: See [`../rnd/v0.1.7/2026.05.09-inter-session-commons/`](../rnd/v0.1.7/2026.05.09-inter-session-commons/) (design + execution log) and [`notification-types.md`](notification-types.md) §`commons_broadcast_ack` for the ack notification contract.

The commons subsystem layers two related capabilities on the same file-backed transport (`<LUPIN_ROOT>/io/commons/*.md`):

1. **Session to session commons**. Claude Code instances post to and read from a shared blackboard.
   They use the 5 cosa-voice MCP tools: `commons_post`, `commons_read`, `commons_who`, `commons_ask_sync` and `commons_ask_async`.
2. **User to all sessions broadcast**. One message from the notifications UI fans out to every active CC session of the authenticated user.
   Directive parsing is persona-aware (`@PersonaName:` lines).

The endpoints below cover surface #2. The MCP tools are surface #1 and are not REST endpoints.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/commons/active-sessions`           | JWT | Returns same-user-scoped active CC sessions for the broadcast recipient preview. Same-user filter (per `user_id` on each bridge file) + freshness filter (`commons broadcast active session threshold seconds`, default 600). Response: `{ sessions: [{ session_id, sender_id, persona_name, persona_icon, persona_color, last_seen_iso, speakerphone_on }] }`. Never leaks bridge filesystem paths. `sender_id` (**added**) is the notification routing key `claude.code@<project>.deepily.ai#<hash8>`, derived from the bridge's `cwd` via `detect_project_for_path`. A client cannot rebuild it from `session_id` alone because the project segment differs per seat (`@lupin`, `@lupin-mobile`, `@plan`). It is `null` when the bridge carries no usable `cwd`, never a guess. Consumer: the phone seeds its focus rail from this roster so a live seat appears before it has ever notified the user. |
| POST | `/api/commons/broadcast-to-cc-sessions`  | JWT | Fans out a message to every active CC session belonging to the caller. Body: `{ message, broadcast_id?, require_ack=true, include_originator=true }`. Rate-limited at 1 broadcast per `commons broadcast rate limit seconds` (default 30) per `user_id`; exceeded → `HTTP 429` with `Retry-After` header. Body containing literal `<system-reminder>` / `</system-reminder>` substring → `HTTP 400`. Caller-supplied `broadcast_id` colliding with an in-flight broadcast → `HTTP 409`. Zero recipients → `HTTP 200` with `status="no-active-sessions"`. Success → `HTTP 200` with `{ broadcast_id, recipients, failed_recipients, filtered_out, status="queued" }`. `filtered_out[]` (** fanout receipts**) lists every enumerated session the recipient filter dropped. `{ session_id, reason }`, reason ∈ `bridge_unreadable` / `owner_mismatch` / `stale_bridge_mtime` (adds `age_seconds` + `threshold_seconds`) / `bridge_vanished` / `originator_excluded`. Present in both 200 shapes so a silent miss is visible to the sender. When `require_ack=true`, downstream `commons_broadcast_ack` notifications stream in via the existing `notification_queue_update` envelope as each recipient listener acks. |
| GET    | `/api/commons/broadcast-history`         | JWT | Aggregates entries across all commons topics and returns them newest-first, scoped to the authenticated user. The configurable blacklist defaults to `presence` and `system-events`. It powers the broadcast-card Recent Activity admin-oversight stream. Query params: `since` (ISO cutoff), `hours` (back-window from now) and `limit` (default 200, capped server-side by `commons traffic visibility max entries per response`, default 1000). Response: `{ entries: [{ ts, topic, topic_kind: "reserved"\|"free-form", sender_session_id, persona_name, persona_icon, persona_color, body, metadata }], since_used, next_cursor }`. When the master INI flag `commons traffic visibility enabled` is False, it returns `{ entries: [], since_used: null, next_cursor: null, disabled: true }`. Same-user scoping mirrors `/active-sessions`. Un-stamped legacy bridges degrade gracefully (`owner_user_id == None` passes through). |

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
3. Each listener's `_handle_action()` dispatcher routes to `broadcast_handler.handle_broadcast()`.
   That handler parses the directive and injects the effective text as a `<system-reminder>` block.
   It then posts an ack to the `broadcast-acks` reserved topic.
4. The `CommonsAckWatcher` daemon polls every `commons broadcast ack watch interval seconds` (default 1) and tails `broadcast-acks`.
   It dispatches one `commons_broadcast_ack` notification per ack to the originating user.
   [`notification-types.md`](notification-types.md) gives the payload shape.

When `require_ack=false`, the first three steps still happen. No acks fan back to the user, and the watcher's in-flight tracking is skipped for this broadcast.

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
| POST | `/api/proxy/acknowledge` | Credential | Retire current batch, start new one. Gated; no owner check — see the note below |
| GET | `/api/proxy/batch-id` | Credential | Get current proxy batch ID. Gated |
| GET | `/api/proxy/pending/{user_email}` | Owner | Get pending decisions. Owner-only — 401 without a credential, 403 if the path names another user. It was `Public`, and an uncredentialed call really did return 200 |
| POST | `/api/proxy/ratify/{decision_id}` | Owner (query) | Approve or reject decision. Owner-only — 401 without a credential, 403 if `?user_email=` names another user. `ratified_by` is taken from the credential, not from that parameter |
| DELETE | `/api/proxy/decision/{decision_id}` | Owner (query) | Hard-delete decision. Same gate as `/ratify`; `deleted_by` likewise comes from the credential |
| GET | `/api/proxy/trust/{user_email}` | Owner | Get trust state for user. Owner-only — same gate as `/pending` |
| GET | `/api/proxy/decisions/{domain}/{category}` | Credential | Decision history by domain/category. Gated |
| GET | `/api/proxy/mode` | JWT | Get current trust mode |
| PUT | `/api/proxy/mode` | JWT | Update trust mode |

✅ **All nine rows are gated, measured at the path**.
Driving the real router with no credential, every one of the nine now answers **401**.
Five did not before: `batch-id`, `acknowledge`, `ratify`, `decision` and `decisions/{domain}/{category}`.
Two of those five had reached the **database**.
A bare call to `ratify` or `decision` answered 422 for the missing `user_email`, which reads like a refusal and is not one.
A well-formed call returned "Decision … not found".
So an uncredentialed caller could ratify or hard-delete any decision by id, naming any victim's email in a **query** parameter.

Two things had to change together.
`require_path_identity_owner` reads `path_params` and raises 500 for a route naming no user in its path.
It cannot cover a `user_email` that arrives in the query string.
`require_query_identity_owner` is its sibling in the same module, with the same 401/403 semantics, reading `request.query_params`.
And `batch-id` had been left open because of one uncredentialed server-to-server caller in `swe_team/orchestrator.py`.
That caller now sends its API key, so the route could be gated.

Warning: **`acknowledge` carries no owner check, and that is a residue rather than a completed fix**.
It takes no identity parameter anywhere.
`_proxy_batch_state` is one process-global counter, not a per-user record, so nothing in the request can be owned.
Any credentialed caller can still retire another user's displayed batch.
Making the batch per-user is a design change.

Warning: **the `ratified_by` and `deleted_by` columns were writing a claim, not a fact**.
The ownership check alone does not repair that.
The guard accepts the caller's bare user id and compares email without regard to case.
So one person could write three different strings into the same column, and into the trust-state key.
A counter split across two spellings of one user is a wrong answer, not a cosmetic one.
Both handlers now take the audit identity from the credential.

## 19. Mock Job (`/api/mock-job/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/mock-job/submit` | — | 🪦 **Gone (410)**. Use `/api/v2/submit` with `"agent router go to mock job"` (args in `args`; `scheduled_at` / `monopolize` top-level; config comes back in `submit_details.config`). Remove by end of 2026. |
| GET | `/api/mock-job/health` | Public | Mock job subsystem health |

## 20. I/O Files (`/api/io/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/io/file` | Public | Serve file from io/ directory |
| GET | `/api/io/health` | Public | I/O subsystem health |
| GET | `/api/docs/file` | JWT | Serve a file or folder listing from a registered scope (`?path=<project>/<rel>`) |
| GET | `/api/docs/scopes` | JWT | List registered doc-viewer scopes and their allowed prefixes |
| POST | `/api/docs/upload` | Admin | Upload one file into a browsable folder. Multipart `dir` (`<project>/<rel-dir>` or `io/<rel-dir>`), `file`, `on_conflict` = refuse\|replace\|rename. 201 `{path, name, size, replaced, view_url}` · 400 bad name/type/credential content · 403 folder not writable · 404 no folder · 409 name taken (`detail.suggested_name`) · 413 over 100 MB |

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
| `/app/console?seat=<full cc session id>&title=<url-encoded title>` | One seat's live CC console, full-page in its own tab. Stands alone: reload- and bookmark-safe, needs no multiplexer tab. A missing or malformed `seat` (e.g. an 8-hex chip prefix) shows an error on the page. Opened by the multiplexer reading pane's bust-out while the pane shows a console. Bundle: `src/scripts/build-console.sh` (part of `npm run build`) |

## 24. Multiplexer (`/api/multiplexer/*`)

> Front-end client-config exposer. Returns display-tuning values fetched once at boot by `/static/js/multiplexer/boot.ts`. No auth required (display tuning, no PII or state).

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/multiplexer/config` | None | Multiplexer client-config (boot-time tuning values) |

---

## 25. FCM Wake Push (`/api/fcm/*`)

Mobile silent-relay wake channel. The mobile app registers its FCM device token.
The parent fires a content-free, data-only `ws_wake` push when a notification is enqueued for a user with no live WebSocket session marked `client_type: "mobile"`.
Web sessions never suppress the wake. Tokens persist in the `fcm_tokens` table.
Spec: `src/lupin-mobile/src/rnd/2026.06.11-focus-mode-voice-chat/15-section-s6-fcm-backend-interface.md`.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/fcm/register-token` | JWT | Register device token. Body `{ token, platform, user_email }` → `{ "status": "ok" }`. Upsert keyed on token; multiple devices per user. |
| POST | `/api/fcm/unregister-token` | JWT | Unregister device token (best-effort logout). Body `{ token }` → `{ "status": "ok" }`, idempotent. |
| POST | `/api/fcm/push-pause` | Admin JWT | Pause or resume all mobile wake pushes, globally. Body `{ paused, minutes? }`. `paused: true` sets `fcm wake push enabled` False **in memory only, never the INI**. With `minutes` (1–1440, else 400) a timer restores the boot-time value, and a second pause replaces the first timer. `paused: false` resumes now. Returns the pause state. 403 for a non-admin, 422 for a body without `paused`. A server restart clears the pause. |
| GET | `/api/fcm/push-pause` | Admin JWT | Read the pause state: `{ paused, resumes_at, set_by, set_at, push_enabled }`. `push_enabled` is the live key. |

---

## 25a. Heartbeat Stop Poke Switch (`/api/heartbeat/*`)

The fleet-wide on/off switch for the Stop-hook poke. It is a plain switch with no timer: it stays as set until an admin flips it.
The state is one small file that the Stop hook reads on every stop (`hooks/lib/heartbeat_poke_mute.py`).
A flip therefore takes effect on each seat's next stop, with no restart.
`heartbeat.poke_output_enabled = false` in `~/.claude/settings.json` still mutes on its own.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/heartbeat/poke-mute` | API key or JWT | Read the switch: `{ muted, set_by, set_at }`. A missing or unreadable switch file reads as not muted. |
| PUT | `/api/heartbeat/poke-mute` | Admin JWT | Body `{ muted }` (a JSON boolean, else 422). Returns the state as read back. 403 for a signed-in user without the admin role, 403 for a caller presenting only `X-API-Key` (a Claude session may read the switch and may not flip it), 401 with no credentials. Each flip appends one line to `heartbeat-poke-mute.log` beside the switch file. |

## 25b. Podcast Proxy (`/api/podcast-proxy/*`)

A seat asks for a podcast of a document on the operator's behalf.
The server judges the file and writes the yes/no card itself. It starts the job only after the operator's own yes.
Every refusal is `{ detail: { code, message } }`.
The card binds to the seat's stable session id, and the actor is `<persona> <first 8 hex of the stable id>`.
That check is a courtesy. The lock is the operator's yes bound to the file's hash, plus one spent-card row per card.
Auth for all three: X-API-Key or Bearer JWT.

| Method | Path | Summary |
|--------|------|---------|
| POST | `/api/podcast-proxy/ask` | Body `{ path, actor }`, `path` in doc-viewer form `<scope>/<path>`. Judges the file, files a yes/no card whose default is no, returns `{ card_id, name, size, sha256, asked_by, expires_at, pushed }`. 400 `bad_actor` or a door code (`bad_path`, `not_found`, `viewer_refused`, `wrong_kind`, `too_large`, `credential`, `unreadable`); 404 `no_operator`. 409 `waiting_card` with `card_id` beside the code when a live card for the same bytes exists. |
| POST | `/api/podcast-proxy/start` | Body `{ card_id, actor }`. Re-checks the stored card and the file, spends the card once, queues the job from a copy of the judged bytes, returns `{ card_id, job_id, status, name, queue_position }`. 404 `no_card`, `no_operator`; 400 `bad_actor`; 403 `bad_card`, `not_answered`, `default_answer`, `not_yes`, `wrong_login`, `wrong_session`, `too_old`; 409 `file_refused`, `hash_mismatch`, `spent`, `claimed_no_job` (a start is under way or one did not finish: read the card status before asking again). 502 `queue_failed` (fixed sentence, cause in the server log; the same card may retry). With INI `podcast proxy dry run = true` (default false) the checks and the claim run, the spent row takes a `dry-run-` job id, nothing is copied or queued. And the answer's `status` is `dry run`. |
| GET | `/api/podcast-proxy/card/{card_id}` | Where a card stands: `{ card_id, scope_path, name, size, sha256, asked_by_session, state, expires_at, spent, job_id }`, with `state` one of `waiting`, `yes`, `no`, `default_answer`, `expired`, `wrong_login`, `claimed_no_job`. 404 `no_card`. |
| GET | `/api/podcast-proxy/from-viewer/check` | Query `path` in doc-viewer form. Runs the start's whole file judgement without keeping content, so the doc viewer shows its "Make a podcast" button only for a file that can be podcast. Returns `{ ok, name, size }`. 403 `not_a_person` (API key, or a token with no email); 400 with a door code. Bearer JWT of a signed-in person. |
| POST | `/api/podcast-proxy/from-viewer` | Body `{ path }`. The in-page confirmation is the yes, so there is no card. Judges the file, claims one job per person, file and bytes inside `podcast proxy card max age seconds` (a derived id in the spent-card table; a click after the window starts a new job), queues the job for the caller, returns `{ job_id, status, name, queue_position, size }`. 403 `not_a_person`; 400 with a door code; 409 `spent` with `job_id` beside the code, or `claimed_no_job`; 502 `queue_failed`. Each click writes its copy under its own folder. Dry run applies as for start. |

---

## 26. Task Store — Promote/Demote Requests (`/api/tasks/*`)

Managers ask Rick to move a row, and only Rick answers.

**Sword of Damocles**: while `sword_of_damocles_active` is on, an admit must pledge one live ticket the requester owns.
Rick's approval drops the pledge in the same transaction as the admit.
Ownership is checked against the persona the server resolves (approver account, else the session bridge), never the typed actor.
Plan: `src/rnd/v0.2.1/2026.09.14-sword-of-damocles-enforcement-plan.md`. Full schemas: `/docs`.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/tasks/{task_id}/request` | API Key / JWT (managers) | File a request. Body `{ move: admit\|demote, reason, actor, deletion_task_id? }`. 422 an admit with no pledge while the switch is on, a pledge on a demote, or a self/nonexistent pledge · 403 not a manager or not your ticket · 409 pledge finished or already pledged on another pending admit. A pending admit whose pledge died may be re-filed. |
| POST | `/api/tasks/{task_id}/unpark-ask` | API Key / JWT (managers) | Ask the operator to approve un-parking a parked row. Body `{ actor }`. The server makes the card (bound to this row and the move parked to queued) and returns `{ card_id, task_id, expires_at, pushed }` (`pushed` false means the card is saved but the push to the operator failed). After a yes the manager cites the id as the `approval_card` receipt on the `parked -> queued` transition. 403 not a manager · 404 unknown row or operator account · 409 the row is not parked, has no recorded park time, or an unanswered card for this row and park already exists (its id is in the message). |
| POST | `/api/tasks/{task_id}/request-verdict` | JWT (operator account) | Rick's verdict. `approved` performs the move and drops the pledge, both or neither. A dead pledge is 409 and the request stays pending. `denied` touches neither row. |
| GET | `/api/tasks/request-badges` | API Key / JWT | Pending counts `{ task_area, holding_area }` — never summed. |
| PATCH | `/api/tasks/approval-settings` | JWT (operator account) | Rick flips `{"sword_of_damocles_active": true\|false}`. Lands on the next request, no bounce. `GET` shows the value and its source. |

---

## 27. CC Transcript Console (`/api/cc-transcript/*`)

A read-only live window onto what a Claude Code seat is printing.
The source is the seat's **transcript JSONL file**, tailed by byte offset.
The live channel is the existing `/ws/queue` socket, not a new one.
Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`.
Deep-dive: [`websocket-events.md`](websocket-events.md) § "CC Transcript Console Events".

**Status**: the contract is documented, and the routes land in the first build phase.

**Why `cc-transcript` and not `transcript`**: "transcript" already means speech-to-text on this API.
That covers `/api/v2/transcribe`, `/upload-and-transcribe-{mp3,wav}` and the `transcript` line of an STT NDJSON stream.
The `cc-` prefix cannot be read as speech.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/cc-transcript/{cc_session_id}` | **Admin** | Backlog and gap repair. Returns `{ file_epoch, offset, next_offset, blocks[] }`. A `tool_call` block carries the tool's `name`, as on the WebSocket frame. A `tool_result` carries its call's `name` when that call is inside the same page, else no `name`. |
| GET | `/api/cc-transcript-roster` | **Admin** | Watchable-seat roster — a **projection** of `/api/arbiter/fleet-state` plus `project`, `last_ts` and `transcript_watchable`. |

**Why the roster is a sibling path and not `/api/cc-transcript/roster`**.
A literal segment under the same prefix collides with `{cc_session_id}`.
`/api/cc-transcript/roster` matches the parameterised route too, and which route wins depends on declaration order.
That resolves correctly today and breaks silently the first time someone reorders the decorators.
The symptom would be a roster request answered as a lookup for a seat literally named "roster".
A sibling path cannot collide at all.

**`cc_session_id` is the seat's `stable_session_id`** — the full id that survives a `/clear`, never the 8-character form used by `sender_id` or a DM's `recipient_session_hash8`.

### Reading the backlog — three query shapes, and one of them reads backwards

The backlog contract is "since the last `/clear`, capped near 64 KB, with load-earlier".
**A forward-only contract cannot express that**.
`?since_offset=0&max_bytes=65536` returns the **first** 64 KB of a file. And the contract wants the **last** 64 KB.
Hence an explicit tail mode and a backward page.

| Query | Direction | Use |
|---|---|---|
| `?tail_bytes=N` | **backward from EOF** | the open — the last N bytes |
| `?before_offset=N&max_bytes=M` | **backward from N** | "load earlier" |
| `?since_offset=N&max_bytes=M` | forward from N | gap repair after a dropped frame |

Every response lands on **complete-line boundaries**, and `next_offset` is always the end of a complete line.

**Every page makes progress; the byte cap is a target, not a hard limit**.
When a window holds no complete record because the record at its edge is larger than the cap, that one record is returned whole.
This holds for all three verbs.
Before that, a backward page came back empty at the same offset, and "load earlier" stayed stuck behind any record over 64 KB.
An empty `( [], 0, 0 )` from `before_offset` now means only one thing: the top of the file.

### The roster is a projection, and its gate is its own

`/api/arbiter/fleet-state` is guarded by `require_api_key_or_jwt`, which is **looser than admin**.
The console is admin-only, so the roster projection carries **its own `require_admin` gate** rather than inheriting fleet-state's.
Assert against the projection, never against `/arbiter/fleet-state`.

`transcript_watchable` is **false** for a seat with no live transcript, and false for a non-admin caller.

**An unreachable arbiter is not an empty fleet**.
`/arbiter/fleet-state` answers **HTTP 200** with `{ "status": "unreachable", … }` when `:8001` is down: the proxy is up and the upstream is not.
The projection must report *unreachable*, not an empty roster.
The two must be distinguishable in the response.

### Access, and what the stream carries

**Admin only, with no redaction in v1**.
Both surfaces enforce it, with **two different gates**.
`require_admin` guards these REST routes, and `websocket_manager.session_is_admin[ session_id ]` guards the WS verbs.
Both gates matter: a test that exercises one proves nothing about the other.

The stream carries everything the seat read — file contents, tool output, possibly secrets from a `.env` or a log. A hidden UI entry point is a courtesy, not a gate. Revisit before mobile goes off-LAN.

Warning: **The positive admin arm is proved at the override tier, not against the live auth stack**.
The only admin accounts are `admin@lupin.deepily.ai` and Rick's own, and **the fleet holds neither password**.
So no test in this repo has ever watched an admin *succeed*, only a non-admin fail.
Rick ruled that v1 ships on the `dependency_overrides[ require_admin ]` positive arm, with a dev-only test admin account as a separate follow-up.
That proves the route **wiring**, not the live gate. It is stated here, not rounded down to "tested".

### Configuration

Six INI keys, all in `src/conf/lupin-app.ini`.
Three carry Rick's ruled values. Three are defaults chosen by the implementer, to be moved without a code change.

| Key | Default | Source |
|---|---|---|
| `cc transcript poll interval seconds` | `0.25` | implementer default |
| `cc transcript watcher grace seconds` | `30` | implementer default |
| `cc transcript coalesce window ms` | `300` | **ruled** |
| `cc transcript backlog tail bytes` | `65536` | **ruled** (about 64 KB) |
| `cc transcript block budget bytes` | `8192` | implementer default; **`0` means unbounded**, not zero |
| `cc transcript ring buffer bytes` | `262144` | implementer default |

**The ring is bounded in bytes, not in records**.
`arbiter_state.FleetEventAccumulator` has the right *shape*: session id to a bounded per-session tail.
But it is bounded in records (`DEFAULT_TAIL_MAXLEN = 50`), and a record-count ring cannot answer a byte-offset question.
The server could not say which `from_offset` values it is able to serve.
The ring therefore carries the offset span it holds, and a `from_offset` outside that span is answered by pointing the client at REST.

---

## Job ID Prefixes

| Prefix | Job Type | Submit Endpoint |
|--------|----------|-----------------|
| `dr-` | Deep Research | `/api/v2/submit` with `"agent router go to deep research"` (`/api/deep-research/submit` is now 410) |
| `pg-` | Podcast Generator | `/api/v2/ask` with `"agent router go to podcast generator"` (`/api/podcast-generator/submit` is now 410) |
| `rp-` | Research-to-Podcast | `/api/v2/submit` with `"agent router go to research to podcast"` (`/api/deep-research-to-podcast/submit` is now 410) |
| `cc-` | Claude Code | `/api/v2/submit` with `"agent router go to claude code"` (both `/api/claude-code/*` doors are now 410) |
| `swe-` | SWE Team | `/api/v2/submit` with `"agent router go to swe team"` (`/api/swe-team/submit` is now 410) |
| `ts-` | Test Suite | `/api/v2/submit` with `"agent router go to test suite"` (`/api/test-suite/submit` is now 410) |
| `bfe-` | Bug Fix Expediter | `/api/v2/ask` with `"agent router go to bug fix expediter"` (`/api/push` is now 410) |
| `tfe-` | Test Fix Expediter | `/api/v2/ask` with `"agent router go to test fix expediter"` (`/api/push` is now 410) |
| `mock-` | Mock Job | `/api/v2/submit` with `"agent router go to mock job"` (`/api/mock-job/submit` is now 410) |

---

## Cross-Reference: Deep-Dive Documentation

| Topic | Document |
|-------|----------|
| Notification system | [`notification-api.md`](notification-api.md) |
| Decision proxy | [`proxy-admin-guide.md`](proxy-admin-guide.md) |
| WebSocket architecture | [`websocket-architecture.md`](websocket-architecture.md) |
| WebSocket events | [`websocket-events.md`](websocket-events.md) |
| CC transcript console | [`websocket-events.md`](websocket-events.md) § CC Transcript Console Events |
| WebSocket troubleshooting | [`websocket-troubleshooting.md`](websocket-troubleshooting.md) |
| Interactive testing | [`automated-interactive-testing.md`](automated-interactive-testing.md) |
| Frontend architecture | [`lupin-mpa-frontend-architecture.md`](lupin-mpa-frontend-architecture.md) |
