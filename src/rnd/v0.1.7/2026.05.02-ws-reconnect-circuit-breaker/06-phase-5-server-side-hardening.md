# Phase 5 — Server-Side Hardening

**Goal**: Make WebSocket close codes from the server semantically
distinguishable, so the client can tell "permanent failure, do not retry"
apart from "transient network failure, retry per backoff." This is the
server-side counterpart to the per-channel state machine: the client
already has the right structure to react to close codes, but today the
server closes everything as a generic 1006 (or with no code) and the
client can't differentiate.

## Application Close Codes (added)

| Code | Meaning | Client behavior |
|------|---------|-----------------|
| 4001 | Auth failed: invalid or expired token | Channel goes to OPEN_CIRCUIT immediately (do NOT retry — user must re-authenticate). Banner triggers token-refresh attempt path that already exists in `notifications.js:2354-2372`. |
| 4002 | Auth failed: session conflict (single-session-per-user denied this connection) | Channel goes to OPEN_CIRCUIT immediately with a different banner: "Another session has taken over. Refresh to reclaim." |
| 4003 | Auth failed: subscription denied (event subscription RBAC failure) | Channel goes to OPEN_CIRCUIT immediately. Banner: "Permission denied for one or more notification streams." |
| 1000 | Normal client-initiated close | No reconnect. State → DISCONNECTED. |
| 1001 | Going away (server shutdown) | Reconnect per normal backoff. |
| 1006 / no-code | Abnormal closure (current default) | Reconnect per normal backoff. This is the current behavior; only 4001/4002/4003 are NEW. |

## Files Modified

| Path | Change |
|------|--------|
| `src/cosa/rest/routers/websocket.py` | Replace generic `await websocket.close()` calls in auth-failure branches with `await websocket.close(code=4001, reason="invalid_token")` (and 4002/4003 for the other branches) |
| `src/fastapi_app/static/js/ws-channel.js` | In the `onclose` handler: if `event.code` ∈ {4001, 4002, 4003}, set state to OPEN_CIRCUIT immediately with `reason: "auth-permanent"` instead of scheduling reconnect |
| `src/fastapi_app/static/js/notifications.js` | Wire `ws-circuit-open` event detail to differentiate banner text by `reason` (already supported by `_showCircuitBanner(detail)` per Phase 3) |
| `src/docs/websocket-events.md` | Document the new close codes |
| `src/docs/websocket-architecture.md` | Add a "Close Code Semantics" subsection |

## Existing `routers/websocket.py` Auth-Failure Sites

Per the survey at `notifications.js:374-385` and `:396-405` and `:444-462`,
the server has these reject branches:

- `auth_message.get("type") != "auth_request"` → currently sends `{"type":"auth_error", "message":"First message must be auth_request"}` then closes; close code becomes 4002 (protocol violation, client will not retry).
  Wait — re-check at impl time. This is an auth-flow protocol violation, not a session conflict. Re-classify as 4001.
- Token validation fails → currently sends auth_error and closes; close code becomes 4001.
- Single-session-per-user reject → currently sends auth_error and closes; close code becomes 4002.
- Subscription RBAC reject → currently sends auth_error and closes; close code becomes 4003.

The exact site count and decoration is determined during implementation
by re-reading `routers/websocket.py` lines around the verification points.

## Optional: uvicorn protocol-level pings

**Decision Q11**: NOT included in v1. Server-side `WebSocketManager.send_heartbeat_to_all`
already issues an app-level `sys_ping` every 30s (see `lupin-app.ini:619`).
Adding `--ws-ping-interval 20 --ws-ping-timeout 20` to uvicorn would add
a parallel protocol-level ping (Pong is automatic and not surfaced to JS),
which the server can use to detect dead clients. Useful but not blocking
on the user-facing bug. Re-evaluate if dead-client detection becomes a
measured problem.

## Phase 5 Verification

| # | Step | EXECUTOR |
|---|------|----------|
| 0 | `grep -rnE "close.*code=4\|close.*code = 4" src/` returns no existing 4xxx close codes; if hits exist, renumber the Lupin auth block (4001–4003) to a non-colliding range BEFORE writing the patch | EXECUTOR: AI |
| 1 | `python -c "import py_compile; py_compile.compile('src/cosa/rest/routers/websocket.py', doraise=True)"` exits 0 | EXECUTOR: AI |
| 2 | `PYTHONPATH=src:$PYTHONPATH python -c "from cosa.rest.routers import websocket; print('OK')"` exits 0 | EXECUTOR: AI |
| 3 | Layer-2 Python WS smoke test `test_authentication_flow.py::test_invalid_token_close_code` (NEW) connects with a junk token and asserts the close frame's code is 4001 | EXECUTOR: AI |
| 4 | Layer-2 Python WS smoke test `test_authentication_flow.py::test_session_conflict_close_code` (NEW, only runs when `enforce_single_session_per_user` is enabled in the test config) connects two clients with the same user, asserts second's close code is 4002 | EXECUTOR: AI |
| 5 | Layer-3 in-page test `test_close_4001_opens_circuit_immediately` injects a 4001 close on a mock WS, asserts state goes to OPEN_CIRCUIT in one tick, attempts counter is at 1 (not 20) | EXECUTOR: AI |
| 6 | Layer-3 in-page test `test_close_4001_banner_message` asserts the banner text reflects the auth-permanent reason (different from the network-failure copy) | EXECUTOR: AI |
| 7 | `src/docs/websocket-events.md` contains a section listing 4001/4002/4003 with semantics | EXECUTOR: AI |
| 8 | `src/docs/websocket-architecture.md` references the new close-code section | EXECUTOR: AI |
| 9 | Token-refresh path in `notifications.js:2354-2372` still triggers on 4001 (refresh attempt + retry) — Layer-3 test `test_4001_triggers_token_refresh_path` asserts the refresh code branch fires | EXECUTOR: AI |

## Phase 5 Exit Criteria

All nine rows green. Doc touchpoints (per project CLAUDE.md
§DOCUMENTATION TOUCHPOINTS) updated.

## Phase 5 Risks

- **Risk**: Existing clients (older tabs that haven't refreshed) won't
  understand 4001/4002/4003 codes. They'll treat them as generic close
  events and continue retrying.
  **Mitigation**: Acceptable. Old behavior is "reconnect on any close,"
  and the close codes are new but harmless to ignore. Old tabs exhibit
  pre-fix behavior (now bounded by the renderer cap, but at least the
  server isn't actively making it worse).
- **Risk**: 4001 immediate-trip + token-refresh path racing produces a
  visible banner flash before the refresh succeeds.
  **Mitigation**: Order the wiring: 4001 close → token refresh attempt →
  if refresh succeeds, `manualRetry()` (which closes the banner). Banner
  shown only if refresh ALSO fails. Layer-3 test
  `test_4001_refresh_success_no_banner_flash` asserts banner is never
  shown when refresh succeeds.
- **Risk**: WebSocket close codes 4000–4999 are reserved for application
  use per RFC 6455. We must avoid colliding with codes already used
  elsewhere in the codebase.
  **Mitigation**: `grep -rn "websocket.close.*code=4" src/` before
  picking codes; if any exist, renumber to avoid collision. Add a
  comment in `routers/websocket.py` reserving the 4001–4003 block for
  Lupin auth semantics.

## CoSA Edit, No CoSA Git

`src/cosa/rest/routers/websocket.py` lives inside the CoSA submodule
(`/src/cosa/` is `git@github.com:deepily/cosa.git`). Per memory
`feedback_cosa_edit_vs_manage_git`: editing CoSA files from this Lupin
context is fine; running `git add`/`git commit`/`git push` against the
CoSA submodule from this context is forbidden. This Phase will edit
the file. Git ops on the CoSA submodule are out of scope for this
milestone — the CoSA-side commit (if separately required) is the user's
responsibility in a CoSA-context session, NOT this AI's job from the
parent Lupin context.

## Phase 5 Commits

| Commit | Description | SHA |
|--------|-------------|-----|
| (filled at phase close) | `[LUPIN] Server-side WS auth-failure close codes (4001/4002/4003) + client-side immediate-trip handling + docs` | (sha) |
