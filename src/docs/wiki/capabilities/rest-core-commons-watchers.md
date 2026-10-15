---
capability: rest-core-commons-watchers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.commons_ack_watcher.CommonsAckWatcher@a06a007445
  - cosa.rest.commons_activity_watcher.CommonsActivityWatcher@5db7d5954c
  - cosa.rest.commons_rate_limiter.CommonsBroadcastRateLimiter@b7721b48be
---
# Commons watchers and broadcast limit

Daemons that tail the commons store and turn entries into notifications, and the limit on user broadcasts. The commons itself is on [[commons-and-dm]].

## Ack watcher
- `CommonsAckWatcher` tails `broadcast-acks` and pushes a `commons_broadcast_ack` notification to the user who sent each broadcast.
- `register_broadcast( id, user_id, expected )` starts tracking and raises `ValueError` on a repeat id; the endpoint turns that into 409. `unregister_broadcast` is silent for an unknown id. `is_in_flight` is false once the entry expires.
- `tick` reads entries newer than its cursor, pushes for those whose broadcast is in flight, prunes expired entries and returns the count dispatched.

## Activity watcher
- `CommonsActivityWatcher` tails every commons topic except an exclude list and fires a `commons_activity` notification for each new entry.
- The INI key `commons traffic visibility ws push enabled` gates the push. One cursor serves all topics. `tick` returns the count dispatched.

## Broadcast limit
- `CommonsBroadcastRateLimiter( window_seconds )` allows one broadcast per user per window. `check_and_record( user_id )` returns `(True, None)` and records, or `(False, retry_after)`.
- State is process-local, so with several server workers the limit is per worker. `reset( user_id )` is for tests.
