---
capability: rest-routers-commons-broadcast
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.commons.init_commons_state@5ce4446f77
  - cosa.rest.routers.commons.BroadcastRequestBody@136f15c48d
  - cosa.rest.routers.commons.validate_broadcast_body@bdf549ac0b
  - cosa.rest.routers.commons.validate_broadcast_id@2cd3e4730f
  - cosa.rest.routers.commons.build_pseudo_sender_id@ba5e98b92b
  - cosa.rest.routers.commons.perform_fanout@41bb7776cb
  - cosa.rest.routers.commons.post_broadcast_to_cc_sessions@cb98586934
  - cosa.rest.routers.commons.get_notification_queue@419a0b0054
---
# Commons broadcast door

The pieces of `routers/commons.py` that send one message to every live Claude Code seat the caller owns. Routes sit under `/api/commons` and take an API key or a JWT. See [[commons-and-dm]] for the store and the listener side.

## What it does
- `init_commons_state` hands the router its commons store, rate limiter, ack watcher and the active-session age limit at startup. It can be called again, and the routes answer 503 until it has run.
- `BroadcastRequestBody` is the body of `POST /api/commons/broadcast-to-cc-sessions`: `message`, optional `broadcast_id`, `require_ack` (default true) and `include_originator` (default true, no effect: the route passes no originator seat).
- `validate_broadcast_body` refuses an empty message and one holding a system-reminder tag. `validate_broadcast_id` accepts `None` or a UUIDv4. Both return `( valid, error_detail )`.
- `build_pseudo_sender_id` makes `broadcast-<8 hex of sha256( user_id )>` for the `broadcasts` topic. It has no `@`, so the store can read the header back.
- `perform_fanout` writes one `broadcasts` entry per recipient, then pushes that recipient's `action:broadcast_received` notification. It returns the success count and the failed session ids. One failure does not stop the rest.
- `post_broadcast_to_cc_sessions` runs the whole broadcast off the event loop. It answers 400 for a bad body or id and 409 for a repeated `broadcast_id`, but only when `require_ack` is true. It answers 429 with `Retry-After` when rate limited.
- `get_notification_queue` fetches the notification queue the fan-out pushes onto.

## Don't
- Don't put `<system-reminder>` tags in a message. The body check refuses them.
- Don't send a hand-made `broadcast_id` that is not a UUIDv4.

## Invariants
- A failed recipient is reported in the result and never hides the others.
