# Phase 4 — Page Lifecycle Integration

**Goal**: Wire the browser Page Lifecycle events into the channel state
machines so that hidden tabs don't burn the 20-attempt budget, BFCache
restoration recovers without user action, and `pagehide` releases sockets
cleanly.

## Files Modified

| Path | Change |
|------|--------|
| `src/fastapi_app/static/js/notifications.js` | Add `_attachPageLifecycle()` method invoked once during init AFTER channels are constructed |

## Lifecycle Wiring

```js
_attachPageLifecycle() {
  // visibility — pause connect attempts while hidden, resume on return
  document.addEventListener( "visibilitychange", () => {
    if ( document.visibilityState === "visible" ) {
      // Channels' internal connect() guards on visibilityState === "hidden"
      // and no-ops; calling .connect() here re-arms them.
      this.queueChannel.connect();
      this.audioChannel.connect();
    }
  } );

  // BFCache restore — old WS objects are invalid; full reset
  window.addEventListener( "pageshow", ( ev ) => {
    if ( ev.persisted ) {
      this.queueChannel.manualRetry();
      this.audioChannel.manualRetry();
    }
  } );

  // pagehide — release sockets so this page is BFCache-eligible
  window.addEventListener( "pagehide", () => {
    this.queueChannel.close();
    this.audioChannel.close();
  } );

  // Chrome-only freeze/resume (PageLifecycleAPI)
  document.addEventListener( "freeze", () => {
    this.queueChannel.close();
    this.audioChannel.close();
  } );
  document.addEventListener( "resume", () => {
    this.queueChannel.connect();
    this.audioChannel.connect();
  } );

  // Network-aware
  window.addEventListener( "online", () => {
    this.queueChannel.manualRetry();
    this.audioChannel.manualRetry();
  } );
  window.addEventListener( "offline", () => {
    // Don't manualRetry — close to release slots while offline
    this.queueChannel.close();
    this.audioChannel.close();
  } );
}
```

The internal `connect()` guard inside `ws-channel.js` (per Phase 1 spec)
checks `document.visibilityState === "hidden"` and no-ops. This means
`visibilitychange → hidden` doesn't actively close the socket; it just
prevents new connect attempts while hidden. The watchdog also no-ops while
hidden. Existing OPEN sockets stay open; any failure that occurs while
hidden waits for the visibility-restore moment to reconnect.

`offline` is the exception: we explicitly `close()` to release renderer
slots, on the theory that an offline event is a strong signal that
reconnect attempts are pointless. `online` then `manualRetry()`s.

## Initialization Order

```
1. Constructor — class fields initialize
2. init() — auth tokens read, session IDs resolved
3. createChannel() x2 — channels constructed (start in DISCONNECTED)
4. _attachPageLifecycle() — listeners attached
5. queueChannel.connect() / audioChannel.connect() — initial connect
6. health monitor watchdog started (now reconciling, not scheduling)
```

The order matters: lifecycle listeners are attached AFTER channels exist,
so an early `online` event can't hit `this.queueChannel.manualRetry`
before `this.queueChannel` is defined.

## Phase 4 Verification

| # | Step | EXECUTOR |
|---|------|----------|
| 1 | `grep -n "_attachPageLifecycle\\|visibilitychange\\|pageshow\\|pagehide\\|online\\|offline" src/fastapi_app/static/js/notifications.js` shows the new wiring | EXECUTOR: AI |
| 2 | Layer-3 in-page test `test_visibility_hidden_pauses_connect` simulates `visibilitychange → hidden`, drives 5 close events, asserts no new `WebSocket` constructed during hidden window | EXECUTOR: AI |
| 3 | Layer-3 in-page test `test_visibility_visible_resumes_connect` simulates the visible transition and asserts `connect()` is called | EXECUTOR: AI |
| 4 | Layer-3 in-page test `test_pageshow_persisted_full_reset` dispatches `pageshow` with `persisted=true` and asserts both channels' `manualRetry()` runs | EXECUTOR: AI |
| 5 | Layer-3 in-page test `test_offline_closes_sockets` dispatches `offline` and asserts both channels reach DISCONNECTED state | EXECUTOR: AI |
| 6 | Layer-3 in-page test `test_online_triggers_retry` dispatches `online` after the offline test and asserts both channels return to CONNECTING | EXECUTOR: AI |
| 7 | Layer-3 in-page test `test_pagehide_closes_for_bfcache` dispatches `pagehide` and asserts sockets are closed (allowing BFCache eligibility) | EXECUTOR: AI |
| 8 | All earlier-phase tests still green (regression) | EXECUTOR: AI |

## Phase 4 Exit Criteria

All eight rows green.

## Phase 4 Risks

- **Risk**: Some browsers (Safari) may not fire `freeze`/`resume`. Code
  that listens for them must not assume they're guaranteed.
  **Mitigation**: `freeze`/`resume` are additive belt-and-suspenders; the
  page works without them via `visibilitychange` + `pageshow`/`pagehide`.
  Layer-3 tests cover both code paths but don't require both to fire on
  every browser.
- **Risk**: A hidden tab that holds the breaker open at MAX_ATTEMPTS
  won't auto-recover when it becomes visible — `manualRetry()` is only
  fired on `pageshow.persisted`, not on every visibility-restore.
  **Mitigation**: Acceptable. If the breaker tripped while hidden, the
  user opening the tab will see the banner and click Retry-now. We do
  NOT want a hidden-tab return to silently re-open a tripped breaker;
  that would defeat the purpose.
- **Risk**: `online` event firing on a flaky network mid-session triggers
  unnecessary `manualRetry()` on already-OPEN channels.
  **Mitigation**: `manualRetry()` checks state internally; if state is
  CONNECTED, it's a no-op (resets nothing, opens no new socket).

## Phase 4 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Wire Page Lifecycle events into WS channels (visibility, BFCache, online/offline)` | (sha) |
