---
capability: websocket-events
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.websocket_manager.WebSocketManager@c998a46631
  - cosa.rest.websocket_manager.WebSocketManager.connect@5ecea24bab
  - cosa.rest.websocket_manager.WebSocketManager.disconnect@e929df41f2
  - cosa.rest.websocket_manager.WebSocketManager.emit_to_user@a15c34054b
  - cosa.rest.websocket_manager.WebSocketManager.emit_to_user_and_admins_sync@d18f15ffd3
  - cosa.rest.websocket_manager.WebSocketManager.replay_and_resume@4e1de083ec
  - cosa.rest.routers.websocket.websocket_queue_endpoint@b162c1d868
  - cosa.rest.routers.websocket.is_valid_session_id@a201f51c51
  - src.lupin_app.static.js.multiplexer.transport.ConnectionStateMachine.backoffDelayMs@9176d68c5b
---
# WebSocket events

`WebSocketManager` tracks every WebSocket session and fans events out to them. The queues call it as if it were Socket.IO. The browser side is the multiplexer's `transport` folder.

## What it does
- `/ws/queue/{session_id}` carries queue, notification and system events. `/ws/audio/{session_id}` carries audio. `/ws/queue` must start with an `auth_request`. `/ws/audio` accepts the socket first and authenticates only if the client sends one.
- `connect` records the session, its user and its subscriptions. A `/ws/queue` client that names no events gets `*`. A `/ws/audio` client defaults to its three audio events. Names missing from the INI `websocket available events` are dropped.
- `emit_to_user` sends to one user's sessions that subscribe to the event. `emit_to_user_and_admins_sync` also reaches admin sessions.
- The `*_sync` methods run from any thread by scheduling on the main loop, so `set_event_loop` must be called at startup.
- A mobile session (`client_type` `mobile`) with a `device_id` holds a slot per device. Its frames get a sequence number and a buffer, and `replay_and_resume` replays the missed ones.
- The browser holds one `ConnectionStateMachine` per transport. Reconnect waits `min(1000·2^n, 30000)` ms with full jitter.

## Don't
- Don't reuse a close code. 4001, 4002 and 4003 are permanent for `QueueTransport` and 4004 means superseded. 4003 is never sent by the server, but the clients already read it.
- Don't close a displaced socket yourself. `disconnect` sends the one close with the right code, and a second close races it.
- Don't send a job-state event with `emit_to_user_sync` if admins must see it. Use `emit_to_user_and_admins_sync`.
- Don't read a "not subscribed" decline as a failed delivery. It is the subscription filter working.

## Invariants
- A client that asks only for unknown events stores `[]` and receives nothing, and the server logs a warning. A client that asks for none gets `*`.
- The `WebSocketManager` constructor raises `ValueError` when `websocket available events` is empty.
- Only mobile sessions hold a device slot. A newer connection for the same user and device closes the older one with 4004.
- Frame buffers are keyed by slot and survive `disconnect`. When over the cap, the least recently emitted-to slot without a live holder is evicted first.
- `disconnect` drops that session's transcript watches. `emit_to_session` applies no subscription check, so the watcher set is the only filter on console frames.
- A session id is `adjective noun` or a `prefix-hash` form, checked by `is_valid_session_id`.
