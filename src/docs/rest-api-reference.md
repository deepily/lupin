# Lupin REST API Quick Reference

> **Last Updated**: 2026.09.28
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

## 🪦 Retired queue doors — GONE (410), REMOVE BY 2026-12-31

Rick ruled 2026-08-21: **one entry point, and it is v2.** Eighteen routes used to put work
on the queue; sixteen die. Each retired route stays registered on purpose and answers
**410 Gone** with a body naming its replacement — a deleted route is invisible, and nothing
would stop someone re-adding it next year because the product needs it. **These stubs are
themselves dead by the end of 2026.**

**The survivors**: `POST /api/v2/ask` (a bare question — route it), `POST /api/v2/submit`
(work whose command is already decided), `POST /api/v2/resume` (resume a parked question).
`POST /api/v2/ask-audio` (2026-09-14) is `/api/v2/ask` with the question spoken — it transcribes, then
asks through the same flow, so it is not a separate way onto the queue (§6).

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

The two question-shaped doors went first, when `/api/v2/ask` was the only live
replacement. The submit-shaped ones could not follow until `/api/v2/submit` both existed
and could build an agentic job — a 410 naming a route that answers "I do not understand"
teaches a caller less than the error it replaced.

`/api/podcast-generator/submit` is the one job-queueing door that retires into `ask`
rather than `submit`: its description flow asked the user which document they meant and
what languages and audience they wanted, and could answer "cancelled" — a conversation,
which is what `ask` does and what `submit` refuses to do by design.

**Still live, retiring next** — all four are held for a stated reason rather than left
over, and the reason is a blocker in each case, not a queue position. The in-repo caller
counts were re-measured 2026-09-28.

| door | held because | in-repo callers |
|---|---|---|
| `/api/mock-job/submit` | its command exists nowhere — no `JOB_ARG_CONTRACTS` entry and no branch in `create_agentic_job`, so `submit` cannot build one. Retiring it would point a refusal at a door that refuses back. | **0** |
| `/api/test-suite/submit` | it is how the gate rig schedules a `:8000` run, so it lands only once that gate is green — and CLAUDE.md names it the *only* sanctioned way to submit one, so retiring it is a policy change as much as a code change. | 3 |
| `/api/jobs/{id_hash}/resume-from-checkpoint` | rebuilds a job from server-side state. A `SubmitRequest` can say command and args but never "resume job X", and `/api/v2/resume` resumes a *parked question*, not a stalled job. | 1 |
| `/api/test-fix-expediter/resume-from` | same: server-side state, no `SubmitRequest` shape expresses it. | 2 |

**The Claude Code pair retired on 2026-08-21, and the upgrade is what made it possible.**
`/api/claude-code/submit` and its alias `/api/claude-code/queue/submit` (one handler) both
answer 410 naming `/api/v2/submit`. Rick's ruling was that the Claude Code job be *upgraded*
to the front door rather than left to die on the vine — the tombstone is the second half of
that, not a contradiction of it: the work still runs, through
`{"command": "agent router go to claude code", "args": {…}}`.

**One more is a PERMANENT SURVIVOR, not a door awaiting its turn.**
`/api/upload-and-transcribe-mp3` was in the retirement table on 2026-08-21 and came back
out the same day. It is not a queue door: it accepts base64 MP3, transcribes with Whisper,
runs the result through `MultiModalMunger`, and queues only on the `munger.is_agent()`
branch — the other branch returns the transcription to the caller and queues nothing.
`/api/v2/ask` takes text and cannot accept audio, so retiring the route would take browser
dictation, the admin snapshot search and the multiplexer's insert-at-cursor down with it
and offer them nothing in exchange.

Its enqueue branch **has already moved** (2026-08-21): the `is_agent()` path calls
`ask_flow.ask(...)` in-process and refuses without a signed-in user (`routers/speech.py`),
so there is no `push_job` left on this route. Rick's framing: there are two ways to ask —
post your text, or speak it — and both end at the same flow. **Nothing further is owed
here, and the route is not scheduled for removal.** Verified 2026-09-28 against
`RETIRED_DOORS`, which does not list it.

**Two separately-managed repos still call the retired doors** — `src/lupin-mobile` and
`src/lupin-plugin-firefox`. Neither can be edited from this repo; their cutover is owed
work resident in each repo. The 410 body names the replacement, so the fix is discoverable
from the failure — that is the mitigation, and it is the whole of it.

⚠️ **`/api/v2/ask` is not a drop-in for `/api/push`.** `push` queued the job and returned
`{status: "queued", job_id, …}` for the WebSocket to follow up on; `ask` answers
synchronously and returns an `AskResponse`. It also validates with a Pydantic model, so a
malformed body comes back **422, not 400**. A caller cutting over changes how it reads the
result, not only where it posts.

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
| GET | `/api/code-identity` | Public | Which code the RUNNING PROCESS holds — captured at module import, never re-read (row `ce89669e`) |
| GET | `/api/init` | Admin | Hot-reload config; `?config_block_id=` also swaps the running DB connection. Admin-only since 2026-09-23 (row `977eaaf2`) — it was `Public` before, which is what made it a P1 |
| POST | `/api/prediction-engine/reset` | Auth | Reset the PredictionEngine singleton; `?drop_table=true` clears the decision rows. Was an **unauthenticated GET whose `drop_table` defaulted to true** — hardened 2026-09-25 (row `2d6f2221`) to POST + credential + default false |
| GET | `/api/get-session-id` | Public | Generate new session ID. ⚠️ NOT read-only: it grows `TwoWordIdGenerator.generated_ids`, a process-lifetime set that is never pruned (row `977eaaf2`) |
| GET | `/api/auth-test` | JWT | Verify token validity |
| GET | `/api/config/client` | JWT | Get client configuration values |
| GET | `/api/config/similarity-confirmation` | JWT | Get similarity confirmation setting |
| POST | `/api/config/similarity-confirmation` | JWT | Toggle similarity confirmation |
| GET | `/api/debug/websocket-state` | Public | Full WebSocket diagnostic state |

## 4. Queue Management

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/push` | — | 🪦 **GONE (410)** — use `/api/v2/ask`. REMOVE BY 2026-12-31. |
| POST | `/api/push-agentic` | — | 🪦 **GONE (410)** — use `/api/v2/submit`. REMOVE BY 2026-12-31. It was the closest thing to `submit` that already existed: `routing_command` becomes `command`, `websocket_id` becomes optional, and `args` / `question` / `scheduled_at` / `monopolize` keep their names. |
| GET | `/api/get-queue/{queue_name}` | JWT | Get queue contents (user-filtered) |
| GET | `/api/queue/pool-status` | JWT | CJ Flow agentic-pool state + per-provider API contention (Phase 2 core + Phase 3 `api_resource_manager` enrichment) |
| POST | `/api/reset-queues` | JWT | Clear all queues for current user |
| GET | `/api/get-job-interactions/{job_id}` | JWT | Get interaction history for a job |
| POST | `/api/jobs/{job_id}/message` | JWT | Send message to running job |
| GET | `/api/job-history` | JWT | Paginated job history (days, status, job_type, exclude_ids filters) |
| GET | `/api/job-history/{job_id}` | JWT | Single job detail by ID hash |
| DELETE | `/api/job-history/{job_id}` | JWT | Delete job from history (admin or owner) |
| POST | `/api/job-history/{job_id}/retry` | — | 🪦 **GONE (410)** — use `/api/v2/ask`. REMOVE BY 2026-12-31. |

## 5. Notifications (`/api/notify/*`)

> **Deep-dive**: See [`notification-api.md`](notification-api.md)

> 🔴 **Every row's `Auth` below was re-derived from the router on 2026-09-26, not copied forward.**
> Fifteen of them read `Public` and none of them was: twelve are owner-gated by
> `require_path_identity_owner` (row `d90baf3d`, 2026-09-16) and three take any valid credential.
> Eight routes were missing from the table altogether. Walking `router.routes` and following each
> route's dependency tree, **24 of 24 notification routes are gated and 0 are open** — measured on
> the dependency tree, which reads the DEFINITION; row `2d6f2221` is the standing reminder that a
> definition read is the weaker instrument and a path measurement can disagree with it.
>
> ⚠️ **A wrong reassurance costs more than a wrong instruction.** A reader who follows a bad
> instruction finds out; a reader told these are `Public` simply believes the hole is already
> known and does not look. The row that sent this pass named twelve; three more were wrong and
> eight were absent, which is why the population was re-derived rather than patched.

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
| POST | `/api/notifications/undelivered/dismiss` | Credential | Dismiss an undelivered notification |
| GET | `/api/notifications/broadcast-acks/{broadcast_id}` | Credential | Acks collected for one broadcast |

**Reading the `Auth` column here.** `Owner` = `require_path_identity_owner`: 401 with no valid
credential, then 403 unless the user named in the path is the caller (owner-only, no admin bypass).
`Credential` = `require_api_key_or_jwt`: any valid API key or Bearer token, no second check.
`JWT` = a Bearer token specifically.

## 6. Speech I/O

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/upload-and-transcribe-mp3` | Public | Transcribe base64 MP3 via Whisper |
| POST | `/api/get-speech` | JWT | Generate TTS via OpenAI and stream to WebSocket |
| POST | `/api/get-speech-elevenlabs` | JWT | Generate TTS via ElevenLabs and stream to WebSocket |
| POST | `/api/upload-and-transcribe-wav` | Public | Transcribe WAV file upload via Whisper |
| POST | `/api/v2/ask-audio` | JWT | Spoken `/api/v2/ask`: multipart `file` (any audio; the filename's extension picks the decoder), query `websocket_id`, `speak`, `interactive`. Streams `application/x-ndjson`: a `transcript` line, then an `ask` line holding the full AskResponse, or an `error` line if the ask fails after the transcript. Contract fixture: `src/tests/fixtures/ask_audio_ndjson_contract.json` |
| POST | `/api/v2/transcribe` | JWT | Transcribe only, nothing asked (2026-09-16): multipart `file`, its extension (`.ogg`, `.wav`) picks the decoder. Returns JSON `{ transcription, trace: { stt_ms, upload_bytes } }`. 401 identity · 422 missing file part, empty upload, or no speech · 503 + `Retry-After: 5` on GPU OOM · 500 `Could not transcribe the audio.` Not behind `v2 flow enabled`. Replaces the phone's use of `/api/upload-and-transcribe-wav` |
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
| POST | `/api/deep-research/submit` | — | 🪦 **GONE (410)** — use `/api/v2/submit` with `"agent router go to deep research"`. REMOVE BY 2026-12-31. |
| GET | `/api/deep-research/report` | Public | Retrieve research report (local or GCS) |
| GET | `/api/deep-research/health` | Public | Deep research subsystem health |

## 12. Podcast Generator (`/api/podcast-generator/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/podcast-generator/submit` | — | 🪦 **GONE (410)** — use `/api/v2/ask` (it retires into `ask`, not `submit`: its description path held a conversation). REMOVE BY 2026-12-31. |

## 12a. Presentation Generator (`/api/presentation-generator/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/presentation-generator/submit` | — | 🪦 **GONE (410)** — use `/api/v2/submit` with `"agent router go to presentation generator"`. REMOVE BY 2026-12-31. |

It carried a path-escape check that nothing downstream repeated, so the guard moved onto
the job (`presentation_generator/job.py`) in its own earlier commit and the retirement
waited for it — retiring the door first would have left a window with no check at all.

## 13. Research-to-Podcast

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research-to-podcast/submit` | — | 🪦 **GONE (410)** — use `/api/v2/submit` with `"agent router go to research to podcast"`. REMOVE BY 2026-12-31. |

## 13a. Research-to-Presentation

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/deep-research-to-presentation/submit` | — | 🪦 **GONE (410)** — use `/api/v2/submit` with `"agent router go to research to presentation"`. REMOVE BY 2026-12-31. |

## 14. Claude Code (`/api/claude-code/*`) — RETIRED 2026-05-05

> **Retired endpoints.** The legacy direct-dispatch + interactive-control cluster was eliminated on 2026-05-05 due to four catalogued structural defects (URL contract mismatch, no auth, module-level state, parallel pre-cj-flow path). Use **`/api/v2/submit`** instead (Section 15 records the two `/api/claude-code/*` tombstones that replaced it and were themselves retired on 2026-08-21) — it is JWT-authenticated and rides the standard CJ Flow + WebSocketManager dispatch plane. See `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md`.

| Method | Path | Status |
|--------|------|--------|
| POST | `/api/claude-code/dispatch` | ❌ Retired 2026-05-05 → use `/api/v2/submit` (the `/api/claude-code/queue/submit` it originally named is itself 410 as of 2026-08-21) |
| POST | `/api/claude-code/{task_id}/inject` | ❌ Retired 2026-05-05 → INTERACTIVE control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/interrupt` | ❌ Retired 2026-05-05 → INTERACTIVE control parity pending on cj-flow path |
| POST | `/api/claude-code/{task_id}/end` | ❌ Retired 2026-05-05 → INTERACTIVE control parity pending on cj-flow path |
| GET | `/api/claude-code/{task_id}/status` | ❌ Retired 2026-05-05 → use job-card status via CJ Flow accordion |
| WebSocket | `/api/claude-code/ws/{task_id}` | ❌ Retired 2026-05-05 → progress now arrives via `/ws/queue/{session_id}` notifications keyed by `cc-*` job_id |

## 15. Claude Code Queue (retired — use `/api/v2/submit`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/claude-code/submit` | none | ❌ Retired 2026-08-21 → 410 Gone, use `/api/v2/submit` (REMOVE BY 2026-12-31) |
| POST | `/api/claude-code/queue/submit` | none | ❌ Retired 2026-08-21 → 410 Gone, use `/api/v2/submit` (REMOVE BY 2026-12-31) |

A tombstone carries no auth dependency on purpose: an unauthenticated caller must learn the
same thing an authenticated one does, and a 401 teaches nobody anything.

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

`prompt` / `project` / `task_type` / `max_turns` / `dry_run` are arguments to the job, so
they go in `args`. `websocket_id` / `scheduled_at` / `monopolize` are directives to the
queue and stay top-level. `task_type` must be `BOUNDED` or `INTERACTIVE` — anything else is
refused when the job is built.

## 16. SWE Team (`/api/swe-team/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/swe-team/submit` | — | 🪦 **GONE (410)** — use `/api/v2/submit` with `"agent router go to swe team"`; `parent_id_hash` is top-level there. REMOVE BY 2026-12-31. |

## 17. Test Suite (`/api/test-suite/*`)

> **Deep-dive**: See [`agents/test-suite-scheduling-guide.md`](agents/test-suite-scheduling-guide.md)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/test-suite/submit` | JWT | Submit test suite job to queue (always monopolize). Accepts `test_types` (comma-separated or list), `pytest_args`, `scheduled_at` (ISO datetime), `dry_run`. Returns `{ job_id, status, scheduled_at, test_types, monopolize }`. Produces a remediation snapshot JSON + Markdown report at completion. |

## 17a. Bug Fix Expediter (`/api/v2/ask` with BFE command)

> **Deep-dive**: See [`agents/bug-fix-expediter-guide.md`](agents/bug-fix-expediter-guide.md)

BFE is submitted via the generic `/api/v2/ask` endpoint using the agent router command string (`/api/push` was retired 2026-08-21 and answers 410). Used manually when curating which dead jobs get auto-recovery; automatic dispatch happens via the `DeadQueueWatchdog` when `bug fix expediter enabled = true` in INI.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/v2/ask` | JWT | Submit BFE job with `question = "agent router go to bug fix expediter"` and `args = { dead_job_id, extra_context (optional), dry_run (optional) }`. Returns `{ job_id }` with `bfe-` prefix. |
| POST | `/api/bug-fix-expediter/submit` | — | 🪦 **GONE (410)** — REMOVE BY 2026-12-31. Its refusal names `/api/v2/submit`, which accepts the decided command; the row above is the same job asked as a question through `/api/v2/ask`. Both reach BFE. |

Watchdog auto-dispatch: requires `bug fix expediter enabled = true` in `lupin-app.ini`. See the BFE guide for full INI reference, trust-to-git mapping, and Phase 6 automated repair loop configuration.

## 17b. Test Fix Expediter (`/api/v2/ask` with TFE command)

> **Deep-dive**: See [`agents/test-fix-expediter-guide.md`](agents/test-fix-expediter-guide.md)

TFE is submitted via the generic `/api/v2/ask` endpoint using the agent router command string (`/api/push` was retired 2026-08-21 and answers 410). Normally invoked automatically by `TestSuiteCompletionWatchdog` when a `TestSuiteJob` completes with failures; manual submission is supported for curated fix runs.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/v2/ask` | JWT | Submit TFE job with `question = "agent router go to test fix expediter"` and `args = { remediation_snapshot_path, source_test_suite_job_id, original_test_types (comma-separated), original_pytest_args (optional), dry_run (optional) }`. Returns `{ job_id }` with `tfe-` prefix. |

Watchdog auto-dispatch: requires `test fix expediter auto fix enabled = true` in `lupin-app.ini`. See the TFE guide for full INI reference (16 keys), six-phase pipeline, and the `TestSuiteCompletionWatchdog` eligibility gates.

## 17c. Inter-Session Commons (`/api/commons/*`)

> **Deep-dive**: See [`../rnd/v0.1.7/2026.05.09-inter-session-commons/`](../rnd/v0.1.7/2026.05.09-inter-session-commons/) (design + execution log) and [`notification-types.md`](notification-types.md) §`commons_broadcast_ack` for the ack notification contract.

The commons subsystem layers two related capabilities on the same file-backed transport (`<LUPIN_ROOT>/io/commons/*.md`):

1. **Session ↔ Session commons** — Claude Code instances post / read from a shared blackboard via the 5 cosa-voice MCP tools (`commons_post`, `commons_read`, `commons_who`, `commons_ask_sync`, `commons_ask_async`).
2. **User → All Sessions broadcast** — single message from the notifications UI fans out to every active CC session belonging to the authenticated user, with persona-aware directive parsing (`@PersonaName:` lines).

The endpoints below cover surface #2. The MCP tools are surface #1 and are not REST endpoints.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET    | `/api/commons/active-sessions`           | JWT | Returns same-user-scoped active CC sessions for the broadcast recipient preview. Same-user filter (per `user_id` on each bridge file) + freshness filter (`commons broadcast active session threshold seconds`, default 600). Response: `{ sessions: [{ session_id, sender_id, persona_name, persona_icon, persona_color, last_seen_iso, speakerphone_on }] }`. Never leaks bridge filesystem paths. `sender_id` (**added 2026-09-17**) is the notification routing key `claude.code@<project>.deepily.ai#<hash8>`, derived from the bridge's `cwd` via `detect_project_for_path` — a client cannot rebuild it from `session_id` alone because the project segment differs per seat (`@lupin`, `@lupin-mobile`, `@plan`). It is `null` when the bridge carries no usable `cwd`, never a guess. Consumer: the phone seeds its focus rail from this roster so a live seat appears before it has ever notified the user. |
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
| POST | `/api/proxy/acknowledge` | Credential | Retire current batch, start new one. Gated 2026-09-26 (row `44d8e89c`); no owner check — see the note below |
| GET | `/api/proxy/batch-id` | Credential | Get current proxy batch ID. Gated 2026-09-26 (row `44d8e89c`) |
| GET | `/api/proxy/pending/{user_email}` | Owner | Get pending decisions. Owner-only since 2026-09-25 (row `2d6f2221`) — 401 without a credential, 403 if the path names another user. It was `Public`, and an uncredentialed call really did return 200 |
| POST | `/api/proxy/ratify/{decision_id}` | Owner (query) | Approve or reject decision. Owner-only since 2026-09-26 (row `44d8e89c`) — 401 without a credential, 403 if `?user_email=` names another user. `ratified_by` is taken from the credential, not from that parameter |
| DELETE | `/api/proxy/decision/{decision_id}` | Owner (query) | Hard-delete decision. Same gate as `/ratify`; `deleted_by` likewise comes from the credential |
| GET | `/api/proxy/trust/{user_email}` | Owner | Get trust state for user. Owner-only since 2026-09-25 (row `2d6f2221`) — same gate as `/pending` |
| GET | `/api/proxy/decisions/{domain}/{category}` | Credential | Decision history by domain/category. Gated 2026-09-26 (row `44d8e89c`) |
| GET | `/api/proxy/mode` | JWT | Get current trust mode |
| PUT | `/api/proxy/mode` | JWT | Update trust mode |

> ✅ **All nine rows are gated as of 2026-09-26 (row `44d8e89c`), measured at the PATH.** Driving the
> real router with no credential, every one of the nine now answers **401** — `batch-id`,
> `acknowledge`, `ratify`, `decision` and `decisions/{domain}/{category}` were the five that did not.
> Two of those five had reached the **database**: a bare call to `ratify` or `decision` answered 422
> for the missing `user_email`, which reads like a refusal and is not one, and a well-formed call
> returned "Decision … not found", so an uncredentialed caller could ratify or hard-delete any
> decision by id while naming any victim's email in a **query** parameter.
>
> Two things had to change together. `require_path_identity_owner` reads `path_params` and raises 500
> for a route naming no user in its path, so it cannot cover a `user_email` that arrives in the query
> string: `require_query_identity_owner` is its sibling in the same module, with the same 401/403
> semantics, reading `request.query_params`. And `batch-id` was left open in row `2d6f2221` *because*
> of its one uncredentialed server-to-server caller in `swe_team/orchestrator.py`; that caller now
> sends its API key, so the route could be gated at all.
>
> 🔴 **`acknowledge` carries no owner check, and that is a residue rather than a completed fix.** It
> takes no identity parameter anywhere, and `_proxy_batch_state` is one process-global counter rather
> than a per-user record, so there is nothing in the request to own. Any credentialed caller can
> still retire another user's displayed batch. Making the batch per-user is a design change.
>
> ⚠️ **The `ratified_by` / `deleted_by` columns were writing a claim, not a fact**, and the ownership
> check alone does not repair that: the guard accepts the caller's bare user id and compares email
> without regard to case, so one person could write three different strings into the same column —
> and into the trust-state key, where a counter split across two spellings of one user is a wrong
> answer rather than a cosmetic one. Both handlers now take the audit identity from the credential.

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
| GET | `/api/docs/file` | JWT | Serve a file or folder listing from a registered scope (`?path=<project>/<rel>`) |
| GET | `/api/docs/scopes` | JWT | List registered doc-viewer scopes and their allowed prefixes |
| POST | `/api/docs/upload` | Admin | Upload one file into a browsable folder. Multipart `dir` (`<project>/<rel-dir>` or `io/<rel-dir>`), `file`, `on_conflict` = refuse\|replace\|rename. 201 `{path, name, size, replaced, view_url}` · 400 bad name/type/credential content · 403 folder not writable · 404 no folder · 409 name taken (`detail.suggested_name`) · 413 over 100 MB (ticket 416d4b00) |

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
| `/app/console?seat=<full cc session id>&title=<url-encoded title>` | One seat's live CC console, full-page in its own tab (row 27760534). Stands alone: reload- and bookmark-safe, needs no multiplexer tab. A missing or malformed `seat` (e.g. an 8-hex chip prefix) shows an error on the page. Opened by the multiplexer reading pane's bust-out while the pane shows a console. Bundle: `src/scripts/build-console.sh` (part of `npm run build`) |

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

## 26. Task Store — Promote/Demote Requests (`/api/tasks/*`)

> Managers ASK Rick to move a row; only Rick answers (row c9fafb9d). **Sword of Damocles** (row ab8c5728): while `sword_of_damocles_active` is on, an admit must pledge one live ticket the requester owns, and Rick's approval drops it in the same transaction as the admit. Ownership is checked against the persona the server resolves (approver account, else the session bridge), never the typed actor. Plan: `src/rnd/v0.2.1/2026.09.14-sword-of-damocles-enforcement-plan.md`. Full schemas: `/docs`.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/tasks/{task_id}/request` | API Key / JWT (managers) | File a request. Body `{ move: admit\|demote, reason, actor, deletion_task_id? }`. 422 an admit with no pledge while the switch is on, a pledge on a demote, or a self/nonexistent pledge · 403 not a manager or not your ticket · 409 pledge finished or already pledged on another pending admit. A pending admit whose pledge died may be re-filed. |
| POST | `/api/tasks/{task_id}/request-verdict` | JWT (operator account) | Rick's verdict. `approved` performs the move and drops the pledge, both or neither; a dead pledge is 409 and the request stays pending. `denied` touches neither row. |
| GET | `/api/tasks/request-badges` | API Key / JWT | Pending counts `{ task_area, holding_area }` — never summed. |
| PATCH | `/api/tasks/approval-settings` | JWT (operator account) | Rick flips `{"sword_of_damocles_active": true\|false}`; lands on the next request, no bounce. `GET` shows the value and its source. |

---

## 27. CC Transcript Console (`/api/cc-transcript/*`)

> A read-only live window onto what a Claude Code seat is printing. The source is the seat's **transcript JSONL file** (ruling Q1), tailed by byte offset; the live channel is the existing `/ws/queue` socket, not a new one. Event names and this path are per ruling **OSQ-6**. Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`. Deep-dive: [`websocket-events.md`](websocket-events.md) § "CC Transcript Console Events".
>
> **Status**: contract documented at phase 0; the routes land at **phase 1**.
>
> **Why `cc-transcript` and not `transcript`**: "transcript" already means speech-to-text on this API — `/api/v2/transcribe`, `/upload-and-transcribe-{mp3,wav}`, and `transcript` as the name of an STT NDJSON line. The `cc-` prefix cannot be read as speech.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/cc-transcript/{cc_session_id}` | **Admin** | Backlog and gap repair. Returns `{ file_epoch, offset, next_offset, blocks[] }`. |
| GET | `/api/cc-transcript-roster` | **Admin** | Watchable-seat roster — a **projection** of `/api/arbiter/fleet-state` plus `project`, `last_ts` and `transcript_watchable`. |

> **Why the roster is a sibling path and not `/api/cc-transcript/roster`.** A literal segment under the same prefix collides with `{cc_session_id}`: `/api/cc-transcript/roster` matches the parameterised route too, and which one wins depends on declaration order. That resolves correctly today and breaks silently the first time someone reorders the decorators, with the symptom being a roster request answered as a lookup for a seat literally named "roster". A sibling path cannot collide at all.

**`cc_session_id` is the seat's `stable_session_id`** — the full id that survives a `/clear`, never the 8-character form used by `sender_id` or a DM's `recipient_session_hash8`.

### Reading the backlog — three query shapes, and one of them reads backwards

Ruling Q6 is "since the last `/clear`, capped ~64 KB, with load-earlier", and **a forward-only contract cannot express that**: `?since_offset=0&max_bytes=65536` returns the **first** 64 KB of a file, while Q6 wants the **last** 64 KB. Hence an explicit tail mode and a backward page.

| Query | Direction | Use |
|---|---|---|
| `?tail_bytes=N` | **backward from EOF** | the open — the last N bytes |
| `?before_offset=N&max_bytes=M` | **backward from N** | "load earlier" |
| `?since_offset=N&max_bytes=M` | forward from N | gap repair after a dropped frame |

Every response lands on **complete-line boundaries**, and `next_offset` is always the end of a complete line.

### The roster is a projection, and its gate is its own

`/api/arbiter/fleet-state` is guarded by `require_api_key_or_jwt`, which is **looser than admin**. The console is admin-only (ruling Q5), so the roster projection carries **its own `require_admin` gate** rather than inheriting fleet-state's. Assert against the projection, never against `/arbiter/fleet-state`.

`transcript_watchable` is **false** for a seat with no live transcript, and false for a non-admin caller.

**An unreachable arbiter is not an empty fleet.** `/arbiter/fleet-state` answers **HTTP 200** with `{ "status": "unreachable", … }` when `:8001` is down — the proxy is up, the upstream is not. The projection must report *unreachable*, not an empty roster; the two must be distinguishable in the response.

### Access, and what the stream carries

**Admin only, no redaction in v1** (ruling Q5), enforced on **both** surfaces and with **two different gates**: `require_admin` on these REST routes, and `websocket_manager.session_is_admin[ session_id ]` on the WS verbs. Both are load-bearing; a test that exercises one proves nothing about the other.

The stream carries everything the seat read — file contents, tool output, possibly secrets from a `.env` or a log. A hidden UI entry point is a courtesy, not a gate. Revisit before mobile goes off-LAN.

> ⚠️ **The positive admin arm is proved at the override tier, not against the live auth stack.** The only admin accounts are `admin@lupin.deepily.ai` and Rick's own, and **the fleet holds neither password** — so no test in this repo has ever watched an admin *succeed*, only a non-admin fail. Rick ruled 2026-09-27 that v1 ships on the `dependency_overrides[ require_admin ]` positive arm, with a dev-only test admin account as a separate follow-up. That proves the route **wiring**, not the live gate. Stated, not rounded down to "tested".

### Configuration

Six INI keys, all in `src/conf/lupin-app.ini`, **added in phase 1**. Three carry Rick's ruled values; three are defaults chosen by the implementer and are meant to be moved without a code change.

| Key | Default | Source |
|---|---|---|
| `cc transcript poll interval seconds` | `0.25` | implementer default (OSQ-1) |
| `cc transcript watcher grace seconds` | `30` | implementer default (OSQ-1) |
| `cc transcript coalesce window ms` | `300` | **ruled** — Q7 |
| `cc transcript backlog tail bytes` | `65536` | **ruled** — Q6 (~64 KB) |
| `cc transcript block budget bytes` | `8192` | implementer default (OSQ-2); **`0` means unbounded**, not zero |
| `cc transcript ring buffer bytes` | `262144` | implementer default (OSQ-3) |

**The ring is bounded in BYTES, not in records.** `arbiter_state.FleetEventAccumulator` is the right *shape* — session id → bounded per-session tail — but it is bounded in records (`DEFAULT_TAIL_MAXLEN = 50`), and a record-count ring cannot answer a byte-offset question: the server could not say which `from_offset` values it is able to serve. The ring therefore carries the offset span it holds, and a `from_offset` outside that span is answered by pointing the client at REST.

---

## Job ID Prefixes

| Prefix | Job Type | Submit Endpoint |
|--------|----------|-----------------|
| `dr-` | Deep Research | `/api/v2/submit` with `"agent router go to deep research"` (`/api/deep-research/submit` is now 410) |
| `pg-` | Podcast Generator | `/api/v2/ask` with `"agent router go to podcast generator"` (`/api/podcast-generator/submit` is now 410) |
| `rp-` | Research-to-Podcast | `/api/v2/submit` with `"agent router go to research to podcast"` (`/api/deep-research-to-podcast/submit` is now 410) |
| `cc-` | Claude Code | `/api/v2/submit` with `"agent router go to claude code"` (both `/api/claude-code/*` doors are now 410) |
| `swe-` | SWE Team | `/api/v2/submit` with `"agent router go to swe team"` (`/api/swe-team/submit` is now 410) |
| `ts-` | Test Suite | `/api/test-suite/submit` |
| `bfe-` | Bug Fix Expediter | `/api/v2/ask` with `"agent router go to bug fix expediter"` (`/api/push` is now 410) |
| `tfe-` | Test Fix Expediter | `/api/v2/ask` with `"agent router go to test fix expediter"` (`/api/push` is now 410) |
| `mock-` | Mock Job | `/api/mock-job/submit` |

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
