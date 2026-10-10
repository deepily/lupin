> Part 6 of 6 of the [WebSocket Event System Documentation](../websocket-events.md): close code semantics and related documentation.

## Close Code Semantics

The server uses RFC 6455 application close codes (4000–4999) to signal
auth-failure outcomes that the browser-side state machine
(`src/lupin_app/static/js/ws-channel.js`) treats as permanent. The
channel goes straight to `OPEN_CIRCUIT` and does `NOT` auto-retry.

Codes were introduced in the WS reconnect circuit-breaker work
milestone (`src/rnd/v0.1.7/2026.05.02-ws-reconnect-circuit-breaker/06-phase-5-server-side-hardening.md`).
Constants live in `src/cosa/rest/routers/websocket.py`.

| Code | Constant | Meaning | Server emits when… | Client behavior |
|------|----------|---------|---------------------|------------------|
| 4001 | `CLOSE_CODE_AUTH_INVALID_TOKEN`       | Invalid / expired / malformed token. Bad `auth_request` envelope | Auth flow on `/ws/queue/{session}` rejects the supplied token (any of: malformed JSON, missing `token` field, empty token, signature failure, `TokenExpiredException`) | `notifications.js` attempts a single `refreshAccessToken()` call first. On refresh-success, `manualRetry()` runs on both channels (no banner shown). On refresh-failure, the auth-permanent banner is shown ("Authentication failed — please log in again."). |
| 4002 | `CLOSE_CODE_AUTH_SESSION_CONFLICT`    | Single-session-per-user policy displaced this connection | A second connection arrives for a user already connected, `AND` `websocket enforce single session per user = True`. The old session receives 4002. | Banner: "Another session has taken over. Refresh to reclaim." Channel does `NOT` auto-retry. |
| 4003 | `CLOSE_CODE_AUTH_SUBSCRIPTION_DENIED` | RBAC reject on one or more `subscribed_events` | Reserved — no current branch emits 4003. The audio path filters denied events silently today. Reserved for future RBAC enforcement. | Banner: "Permission denied for one or more notification streams." Channel does `NOT` auto-retry. |
| 4004 | `CLOSE_CODE_SUPERSEDED` | **Superseded**, reason `"superseded"` | A newer `/ws/queue` connection claimed this socket's `( user_id, device_id )` slot. The old socket is closed `AND` fully deregistered. A half-dead socket left registered would make the device read as connected and silently suppress its FCM wake. Emitted only for mobile sessions, the only ones holding a slot; a mobile client that sent no `device_id` holds none and is never superseded. | Permanent: the client must `NOT` reconnect this socket. Warning: **A new code on purpose.** 4001 is auth failure, which the browser answers with a meaningless token refresh. 4003 is reserved server-side but live on the client — `QueueTransport.ts` lists it in `PERMANENT_CLOSE_CODES` and `notifications.js` renders it "Permission denied…". A reserved server code can still be a spoken-for client one. Browsers do not yet list 4004, so it falls to their default close handling; they cannot receive it today because they hold no slot. |

For comparison, the standard close codes the server still uses unchanged:

| Code | Meaning | Client behavior |
|------|---------|------------------|
| 1000 | Normal client-initiated close | No reconnect. State → `DISCONNECTED`. |
| 1001 | Going away (server shutdown) | Reconnect per normal full-jitter backoff. |
| 1006 / no-code | Abnormal closure (transport-level fault) | Reconnect per normal backoff. |
| 1008 | Policy violation (e.g. invalid session ID format at the URL) | Reconnect per normal backoff. |
| 1011 | Internal error: the **resume replay failed** after auth succeeded, reason `resume_failed`. No `auth_error` frame precedes it | Reconnect per normal backoff. **Not** an auth failure: do not refresh the token or sign out. |

### Browser-side reaction

The full reaction logic lives in `ws-channel.js` (`PERMANENT_CLOSE_CODES` set + `socket.onclose` handler) and `notifications.js` (`_showCircuitBanner` / `_renderCircuitBanner`):

- queue WS `onclose` with `event.code` in {4001, 4002, 4003} → `openCircuit("auth-permanent", code)`.
  That raises a `ws-circuit-open` event with `detail.reason="auth-permanent"` and `detail.code`.
  NotificationsUI tries a token refresh on 4001, and otherwise renders the auth-permanent banner.
- queue WS `onclose` with any other code (1000 / 1001 / 1006 / …) → `handleClose()`, then `scheduleReconnect()`.
  The backoff is full-jitter, capped at 20 attempts before the breaker trips for transport reasons.

---

## Related Documentation

- [WebSocket Architecture](../websocket-architecture.md) — System design and WebSocketManager API
- [WebSocket Configuration](../websocket-configuration.md) — Config keys and tuning
- [WebSocket Troubleshooting](../websocket-troubleshooting.md) — Diagnostic procedures
