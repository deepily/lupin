# Phase 3 — Circuit-Open UI Banner + Retry-Now Button

**Goal**: When either channel emits `ws-circuit-open`, show a non-dismissable
banner at the top of the notifications UI with a "Retry now" button that
invokes `manualRetry()` on both channels (clearing breaker state on both).

## Files Modified

| Path | Change |
|------|--------|
| `src/fastapi_app/templates/notifications.html` | Add `<div id="ws-circuit-banner" hidden>...</div>` markup just inside the main page header |
| `src/fastapi_app/static/css/notifications.css` (or wherever the page CSS lives — confirmed at impl time via grep) | Add styling for `#ws-circuit-banner` (red background, contrast text, retry button styling) |
| `src/fastapi_app/static/js/notifications.js` | Add `_showCircuitBanner(detail)` and `_hideCircuitBanner()` methods; wire `ws-circuit-open` listener; wire button `click` handler |

## Banner Markup

```html
<div id="ws-circuit-banner" class="ws-circuit-banner" hidden role="alert">
  <span class="ws-circuit-banner-text">
    Connection lost — server unreachable after repeated attempts. Check the
    network, then click Retry now.
  </span>
  <span class="ws-circuit-banner-dev-hint" hidden>
    (Dev tip: if you're using <code>ssh -L</code>, check whether the tunnel is
    still alive or has hit "Too many open files".)
  </span>
  <button type="button" id="ws-circuit-retry-btn" class="ws-circuit-retry-btn">
    Retry now
  </button>
</div>
```

Dev-hint visibility is controlled by `envLabel === "DEVELOPMENT"`
(the same flag NotificationsUI already toggles via the `[DEVELOPMENT]:`
clock prefix). Production banners hide the SSH-tunnel hint.

## Banner Behavior

- Hidden by default (`hidden` attribute set in HTML).
- `_showCircuitBanner(detail)` removes `hidden` and updates the dev-hint
  visibility based on `this.envLabel`.
- `_hideCircuitBanner()` re-adds `hidden`. Called on first `auth_success`
  after a Retry-now click.
- The Retry-now button:
  1. Disables itself (visual feedback during reconnect).
  2. Calls `this.queueChannel.manualRetry()` and `this.audioChannel.manualRetry()`.
  3. Re-enables on next `STATE_CHANGE_EVENT` regardless of which state was reached
     (CONNECTED hides the banner; OPEN_CIRCUIT keeps banner visible but re-enables button).
- Banner stays visible if BOTH channels are circuit-open. Banner disappears
  on the FIRST channel's `auth_success` (per Q10 — global banner, not
  per-channel). Acceptable trade-off: one channel succeeded, user can
  see queue/audio status pills for residual issues.

## CSS Sketch

```css
.ws-circuit-banner {
  background-color: var( --color-error-bg, #b00020 );
  color           : var( --color-error-fg, #ffffff );
  padding         : 12px 16px;
  display         : flex;
  align-items     : center;
  justify-content : space-between;
  gap             : 16px;
  font-weight     : 500;
  border-radius   : 4px;
  margin          : 8px;
}

.ws-circuit-banner[hidden] {
  display: none;
}

.ws-circuit-retry-btn {
  background-color : transparent;
  color            : inherit;
  border           : 1px solid currentColor;
  padding          : 6px 14px;
  border-radius    : 3px;
  cursor           : pointer;
  font-weight      : 600;
}

.ws-circuit-retry-btn:disabled {
  opacity : 0.6;
  cursor  : wait;
}
```

(Color tokens checked against the existing palette during implementation;
if the codebase uses a different token system, swap to its conventions.
The `feedback_no_green_in_persona_pool` rule does not apply — error red
is canonical for failure banners.)

## Phase 3 Verification

| # | Step | EXECUTOR |
|---|------|----------|
| 1 | `grep -n "ws-circuit-banner\\|ws-circuit-retry-btn" src/fastapi_app/templates/notifications.html` returns the new markup | EXECUTOR: AI |
| 2 | `grep -n "_showCircuitBanner\\|_hideCircuitBanner" src/fastapi_app/static/js/notifications.js` returns at least the wiring + the listener registration | EXECUTOR: AI |
| 3 | Layer-3 in-page test `test_circuit_open_shows_banner` asserts banner visible after MAX_ATTEMPTS exhausted | EXECUTOR: AI |
| 4 | Layer-3 in-page test `test_retry_now_clears_breaker_and_reconnects` asserts banner hides on `auth_success` post-click | EXECUTOR: AI |
| 5 | Layer-3 in-page test `test_retry_button_disables_during_reconnect` asserts button is `disabled` between click and next state change | EXECUTOR: AI |
| 6 | Layer-3 in-page test `test_dev_hint_visible_only_in_dev` asserts the SSH-tunnel suffix is shown when `envLabel === "DEVELOPMENT"` and hidden otherwise | EXECUTOR: AI |
| 7 | E2E UI visual snapshot updated for the new banner element (run via the existing visual regression harness) | EXECUTOR: AI |

## Phase 3 Exit Criteria

All seven rows green. Visual snapshot baseline regenerated and
committed.

## Phase 3 Risks

- **Risk**: Banner visual snapshot diff churn for unrelated UI changes
  in flight on the branch.
  **Mitigation**: Snapshot regeneration is scoped to `notifications.html` /
  `notifications.css`; spot-check by reading the diff before committing.
- **Risk**: Button's `disabled` state during reconnect is purely cosmetic;
  if `manualRetry()` synchronously throws (it shouldn't), button stays
  disabled forever.
  **Mitigation**: Layer-3 test `test_retry_button_recovers_after_throw`
  injects a synchronous throw from `manualRetry()` and asserts button
  re-enables (the wiring uses `try/finally`).
- **Risk**: Banner's `role="alert"` is announced loudly by screen readers;
  if the breaker trips and re-trips, the announcement repeats.
  **Mitigation**: Banner stays in DOM continuously while `hidden` toggles;
  `aria-live="polite"` on a child node, `role="alert"` on the container.
  Single announcement per state transition.

## Phase 3 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Add WS circuit-open banner + Retry-now button + Layer-3 tests` | (sha) |
