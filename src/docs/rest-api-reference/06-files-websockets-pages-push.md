> Part 6 of 8 of the [Lupin REST API Quick Reference](../rest-api-reference.md): routes 20 to 25b: files, WebSockets, pages, push.

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

> **Deep-dive**: See [`websocket-architecture.md`](../websocket-architecture.md)

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
