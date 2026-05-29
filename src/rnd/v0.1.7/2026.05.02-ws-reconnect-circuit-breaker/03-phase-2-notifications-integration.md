# Phase 2 — Wire `WSChannel` into `NotificationsUI`

**Goal**: Replace the existing reconnect machinery in `notifications.js`
with two `WSChannel` instances. Rip out the shared `connectionRetries`,
`scheduleReconnect`, `isConnecting`, the counter-zeroing in
`checkWebSocketHealth`, and the in-line `onclose` reconnect calls.
Health monitor becomes a watchdog (not a scheduler).

## Files Modified

| Path | Change |
|------|--------|
| `src/fastapi_app/static/js/notifications.js` | See "Diff Map" below |
| `src/fastapi_app/templates/notifications.html` | Add ES module import for `ws-channel.js`; verify cache-bust query string is bumped |

## Files Deleted

None. The `scheduleReconnect`, `connectWebSockets` body, and
`checkWebSocketHealth` reset block are excised in place; we don't
delete the surrounding methods because they have other responsibilities
(session ID lookup, status pill updates, etc.).

## Diff Map (intent — exact diff at PR review time)

| Site | Current | After Phase 2 |
|------|---------|---------------|
| `notifications.js:38-39` | `this.queueWS = null; this.audioWS = null;` | unchanged (channel.ws is internal; NotificationsUI keeps facade refs to channels, not raw sockets) |
| `notifications.js:96-97` | `this.isConnecting = false; this.connectionRetries = 0;` | DELETED |
| `notifications.js:2142-2167` (`connectWebSockets`) | Manually calls `connectQueueWebSocket`/`connectAudioWebSocket`, catches and calls `scheduleReconnect` | Calls `this.queueChannel.connect()` and `this.audioChannel.connect()`; no try/catch needed (channel handles its own backoff) |
| `notifications.js:2169-2270` (`connectQueueWebSocket`/`connectAudioWebSocket`) | Construct WS, attach handlers, schedule reconnect on close | DELETED — replaced by `this.queueChannel`/`this.audioChannel` constructed once in init |
| `notifications.js:2189-2194` and `:2239-2244` (close handlers) | Call `scheduleReconnect` | DELETED — channel handles |
| `notifications.js:2334-2346` (queue auth_success branch) | Sets `connectionRetries = 0` and updates UI | Keeps the UI updates; the counter reset is now triggered by the channel via `onAuthSuccess` callback (which the channel calls AFTER its own counter reset) |
| `notifications.js:2458-2461` (audio auth_success branch) | Updates UI | Same — UI updates remain; channel handles counter |
| `notifications.js:5637-5655` (`scheduleReconnect`) | Schedules with shared counter | DELETED |
| `notifications.js:878-927` (`checkWebSocketHealth`) | Resets counter, schedules reconnect, AND skips entirely outside the 8 AM–Midnight off-hours gate | Becomes a watchdog: iterates `[queueChannel, audioChannel]`, asks each `channel.checkLiveness()`. Channel internally decides whether to no-op or schedule. NotificationsUI no longer touches counters or schedules. **The 8 AM–Midnight off-hours gate is REMOVED**; watchdog runs always. The off-hours gate was a workaround for unbounded reconnect spam during overnight server restarts. With the per-channel circuit breaker, the spam is bounded at MAX_ATTEMPTS (default 20) regardless of clock time. See §Risks "Off-hours gate removal." |
| Init site (around `notifications.js:396`) | `await this.connectWebSockets()` | Construct `this.queueChannel = createChannel({...})` and `this.audioChannel = createChannel({...})` BEFORE first `connect()`; then `await Promise.all([queueChannel.connect(), audioChannel.connect()])` |

## Channel Construction (new code in init)

```js
import { createChannel } from "/static/js/ws-channel.js?v=<cache-bust>";

// inside init(), AFTER session IDs are known:
const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const queueUrl = `${protocol}//${window.location.host}/ws/queue/${this.queueSessionId}`;
const audioUrl = `${protocol}//${window.location.host}/ws/audio/${this.audioSessionId}`;

this.queueChannel = createChannel( {
  url            : queueUrl,
  name           : "queue",
  authMessage    : () => this._buildQueueAuthMessage(),  // returns the auth_request JSON
  onMessage      : ( envelope, evt ) => this.handleQueueMessage( evt ),
  onAuthSuccess  : ( envelope ) => this._onQueueAuthSuccess( envelope ),
  onCircuitOpen  : ( detail ) => this._showCircuitBanner( detail ),
} );

this.audioChannel = createChannel( {
  url            : audioUrl,
  name           : "audio",
  authMessage    : () => this._buildAudioAuthMessage(),
  onMessage      : ( envelope, evt ) => this.handleAudioMessage( evt ),
  onAuthSuccess  : ( envelope ) => this._onAudioAuthSuccess( envelope ),
  onCircuitOpen  : ( detail ) => this._showCircuitBanner( detail ),
} );

await Promise.all( [ this.queueChannel.connect(), this.audioChannel.connect() ] );
```

The channel sends the auth message itself when `state === AUTHENTICATING`,
so `authenticateQueueWebSocket()` and `authenticateAudioWebSocket()` are
extracted into pure builders (`_buildQueueAuthMessage`, `_buildAudioAuthMessage`)
that return the JSON object — the channel does the `ws.send(JSON.stringify(...))`.

## Phase 2 Verification

| # | Step | EXECUTOR |
|---|------|----------|
| 1 | `grep -n "scheduleReconnect\\|connectionRetries\\|isConnecting" src/fastapi_app/static/js/notifications.js` returns ZERO hits | EXECUTOR: AI |
| 2 | `grep -n "this.queueChannel\\|this.audioChannel" src/fastapi_app/static/js/notifications.js` returns at least one construction site + at least one `.connect()` call per channel | EXECUTOR: AI |
| 3 | `python -c "import py_compile; ..."` for any Python file edited in this phase (none expected) — N/A unless server-side touch surfaces | EXECUTOR: AI |
| 4 | All Layer-1 unit tests still green (regression check) | EXECUTOR: AI |
| 5 | All Layer-2 Python WS smoke tests green: `bash src/scripts/run-websocket-smoke-tests.sh` | EXECUTOR: AI |
| 6 | All Layer-3 in-page Playwright tests green | EXECUTOR: AI |
| 7 | Hot-reload `:7999`, load `https://localhost:7999/notifications` (or via tunnel), confirm `auth_success` for both channels in browser console — driven via Layer-4 Playwright probe (`test_websocket_circuit_recovery.py::test_happy_path_smoke`) | EXECUTOR: AI |
| 8 | Layer-3 Playwright "happy-path with intermittent flap" test confirms counter resets on auth_success and channel survives 3 disconnect/reconnect cycles within MAX_ATTEMPTS budget | EXECUTOR: AI |

## Phase 2 Exit Criteria

All eight verification rows green. Browser console after Phase 2 must
NOT show "Scheduling reconnect attempt #N" log lines (the wsDiag string
is moved to the channel module with new wording: `[queue] backoff Xms attempt N reason=...`).

## Phase 2 Risks

- **Risk**: Health monitor's "off-hours" gate (8 AM–Midnight) is removed
  alongside the counter reset; channel watchdog runs always. This means
  reconnect attempts at 3 AM during a server restart will count against
  the 20-attempt budget instead of being skipped.
  **Mitigation**: For v1 we accept this. The 8-hour off-hours window was
  a workaround for a different problem (overnight server restarts
  triggering a long error log). With circuit breaker, the breaker will
  trip at 20 attempts (~6–10 min) and the user sees a banner the next
  time they look at the tab. That's strictly better than today.
  **Documented in**: `08-rollout-and-rollback.md` §Behavior Changes for User
- **Risk**: Authentication retry path at `notifications.js:2358-2367`
  calls `this.connectWebSockets()` after token refresh — needs to be
  redirected to `this.queueChannel.manualRetry(); this.audioChannel.manualRetry()`.
  Same for the audio auth-error path at `:2474-2483`.
  **Mitigation**: Explicit step in Diff Map; covered by Layer-3 test
  `test_token_refresh_resets_channels`.
- **Risk**: `getOrCreateSessionId()` is still called from
  `connectWebSockets()`-equivalent path; if it throws, channels never
  connect. Must keep the existing try/catch around session-ID acquisition.
  **Mitigation**: Init wrapper retains try/catch around session-ID
  resolution; channel construction is post-resolution.

## Phase 2 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Wire WSChannel into NotificationsUI; remove shared retry counter and counter-zeroing health monitor` | (sha) |
