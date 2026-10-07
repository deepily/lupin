---
capability: web-client-transport-and-auth
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.boot.bootMultiplexer@4c0e14dae4
  - src.lupin_app.static.js.multiplexer.transport.QueueTransport.BaseTransportImpl@65b2a06f2b
  - src.lupin_app.static.js.multiplexer.transport.AudioTransport.AudioTransportImpl@fd6e89149c
  - src.lupin_app.static.js.multiplexer.transport.ConnectionStateMachine.ConnectionStateMachineImpl@87cd2fa536
  - src.lupin_app.static.js.multiplexer.auth.AuthManager.AuthManagerImpl.getToken@03b219faa7
  - src.lupin_app.static.js.multiplexer.auth.authGuard.bounceToLoginOnDeadSession@2062c3d504
  - src.lupin_app.static.js.multiplexer.shared.transportSessionIds.resolveTransportSessionIds@f730806063
---
# Web client: transport and auth

The multiplexer page opens two WebSockets, keeps a refreshable login token, and republishes every frame on one in-page event bus. `bootMultiplexer` wires it. Stores are in [[web-client-stores]]; the server side is [[websocket-events]] and [[auth-and-accounts]].

## What it does
- `bootMultiplexer` sends a visitor with no access token to `/app/auth/login`. Otherwise it builds the transports with `createTransports` and starts them last, queue first.
- Each transport extends `BaseTransportImpl`. It opens `/ws/queue/<id>` or `/ws/audio/<id>` and sends `auth_request` with the access token and its fixed event list.
- A JSON frame goes on the bus under its `type`, with the frame minus `type` and `timestamp` as payload. Binary frames go to the handler given to `AudioTransportImpl.start`.
- `ConnectionStateMachineImpl` gives each transport its own states: connecting, connected, reconnecting, backoff, offline, failed. Backoff is full jitter up to `min(1000 * 2^n, 30000)` ms, and 20 attempts end in failed.
- A close within 100 ms of `auth_success` retries at once. Close codes 4001, 4002 and 4003 go straight to failed. A `restart` from failed opens a fresh socket with a full retry budget and clears the old reason and code.
- `attachLifecycleListeners` emits `page_hidden`, `page_visible` (also on a bfcache restore), `network_online` and `network_offline`. Only `page_visible` and `network_online` cut a backoff short.
- `AuthManagerImpl` hydrates from storage. `getToken` returns the token unless it expires within 30 s. Otherwise it refreshes under the lock `lupin-token-refresh`, with a POST to `/auth/refresh` and a 10 s timeout.
- The client from `createApiClient` adds the bearer token, takes a 10 s default timeout from `bootMultiplexer` and returns `null` for a 204. A 401 marks the in-memory token expired and throws `ApiError`.
- `StorageServiceImpl` keeps JSON under `lupin:` keys and the two tokens raw. A bad payload emits `storage_corrupt` and reads as `null`. `resolveTransportSessionIds` stores a queue id and a different audio id.

## Don't
- Don't mark a socket connected on the raw open. Only `auth_success` resets the retry count, so a server that rejects auth still trips the limit.
- Don't share one session id between the sockets. The server keeps one socket and one subscription list per id.
- Don't log out with `AuthManager.invalidate`. `logout` must call `StorageService.clearTokens`, which removes the persisted tokens.
- Don't pass `Authorization` in `ApiCallOptions.headers`. The client sets its own header after the caller's, so it wins.
- Don't expect `failed` to recover on its own. Only the Retry-now button in the System Status pane sends the machine's `restart` event, for each transport in `failed`. Not run in a browser; bug row 5a8bd0c6-6a18-4283-9722-bba10064ff5f.

## Invariants
- A drop on one socket does not reset the other's backoff.
- A socket that opens but never sends `auth_success` is force-closed after 10 s and counts as a failed attempt.
- `bounceToLoginOnDeadSession` acts only on "no refresh token available" or "refresh failed: HTTP 401", and clears tokens only if storage holds the failed one or none.
- After a 401 on refresh, `AuthManagerImpl` retries once with a successor token another tab stored, checked at once and after 1 s.
