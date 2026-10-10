> Part 6 of 9 of the [Lupin REST API Quick Reference](../rest-api-reference.md): routes 20 to 25a: files, WebSockets, pages, push.

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
| GET | `/api/heartbeat/poke-mute` | API key or JWT | Read the switch: `{ muted, set_by, set_at, source }`. `muted` is true when the switch file says muted or skeleton crew is on. `source` is `file`, `skeleton_crew`, `both` or `none`. A missing or unreadable switch file reads as not muted. |
| PUT | `/api/heartbeat/poke-mute` | Admin JWT | Body `{ muted }` (a JSON boolean, else 422). Returns the state as read back, in the same shape as the GET. The file changes only when this route is called, so turning skeleton crew off does not clear a mute set here. 403 for a signed-in user without the admin role, 403 for a caller presenting only `X-API-Key` (a Claude session may read the switch and may not flip it), 401 with no credentials. Each flip appends one line to `heartbeat-poke-mute.log` beside the switch file. |
