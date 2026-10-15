---
capability: rest-routers-peer-queue-watch
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.peer.PeerQueueResponse@d7d9fa7fcd
  - cosa.rest.routers.peer.WatchStartRequest@c1b519b855
  - cosa.rest.routers.peer.WatchStatusResponse@73b62981e5
  - cosa.rest.routers.peer.WatchActionResponse@29f950a45b
  - cosa.rest.routers.peer.get_peer_queue@c2ee85d3c3
  - cosa.rest.routers.peer.start_watcher@1f37d5f9ed
  - cosa.rest.routers.peer.stop_watcher@48cad3e28b
  - cosa.rest.routers.peer.get_watcher_status@9109c6facb
  - cosa.rest.routers.peer.cancel_all_watchers_on_shutdown@e7211e32d0
---
# Peer queue read and drain watcher

Admin routes that let the dev server read and watch the queues of a peer Lupin server, usually the test server. All of them need the admin role.

## What it does
- `get_peer_queue` serves `GET /api/admin/peer-queue/{queue_name}?host=<host:port>` for `todo`, `run`, `done` or `dead`. The `host` query is required. It returns `PeerQueueResponse` (`peer_host`, `queue_name`, `fetched_at`, `total_jobs`, `upstream`).
- `start_watcher` is `POST /api/admin/peer-queue-watch/start` and takes `WatchStartRequest`. `host` is required. `signal` is `run` or `run+todo` (default `run+todo`). `interval_seconds` is 10 to 600 (default 60), `stable_for` is 1 to 10 (default 2) and `priority` defaults to `high`. It starts one background task per admin, replaces a prior one and answers `started`.
- `stop_watcher` is `POST /api/admin/peer-queue-watch/stop`. It cancels the caller's watcher and answers `stopped`, or `not_active` when none was running.
- `get_watcher_status` is `GET /api/admin/peer-queue-watch/status` and returns `WatchStatusResponse`. A caller with no watcher gets `active: false`.
- `WatchActionResponse` is the `{ status, message }` answer of start and stop.
- The watcher notifies once, after `stable_for` consecutive empty polls, then ends.
- `cancel_all_watchers_on_shutdown` cancels every watcher. The main module calls it at shutdown.

## Don't
- Don't use a host outside `peer queue allowed hosts`, a queue name other than the four above, or a `signal` other than the two above. Each answers 400.
- Don't expect the caller's JWT to reach the peer, whatever the route description says. A service-account login is used.

## Invariants
- `get_peer_queue` answers 502 when the peer rejects the login, is unreachable or answers badly.
- It answers 500 when `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL` or `_PASSWORD` is missing.
- A failed poll inside the watcher does not end it. It is written to `last_error` and the next poll runs.
