---
capability: arbiter-live-notify
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_arbiter_app.arbiter_live_notify.build_notify_request@6b690f1bb8
  - lupin_arbiter_app.arbiter_live_notify.parse_notify_outcome@af1b027bc1
  - lupin_arbiter_app.arbiter_live_notify.make_notify_transport@47f1c4762d
  - lupin_arbiter_app.arbiter_live_notify.make_live_notify_fn@b67db99dcf
  - lupin_arbiter_app.arbiter_live_notify.validate_live_notify_target@3e3affea5e
  - lupin_arbiter_app.arbiter_live_notify.resolve_arbiter_api_key@9100dd7eff
  - lupin_arbiter_app.arbiter_live_notify.build_dm_send_payload@90ef259a07
  - lupin_arbiter_app.arbiter_live_notify.make_dm_push_fn@6159ab1f0f
  - lupin_arbiter_app.arbiter_live_notify.make_tmux_push_fn@94466a129c
---
# Arbiter live notify

These are the best-effort pushes the 8001 arbiter makes when it escalates. They are a live notify to the operator, a DM to a manager and a tmux wake. Every hop returns an outcome dict and never raises.

## What it does
- Escalations always land on the durable `fleet-escalations` commons topic. These hops run on the escalation path only, never per poll.
- `build_notify_request` builds the URL and headers for `POST /api/notify`. Every field rides the query string, and the key rides `X-API-Key`.
- `parse_notify_outcome` maps the response to an outcome. The body status carries the real state, because "queued", "delivered_via_listener" and "user_not_available" all arrive as HTTP 200.
- `make_notify_transport` returns the live transport. Any transport error becomes an `http_error` outcome. With `persist` false it re-announces without writing a second database row.
- `make_live_notify_fn` wraps a transport in a dedup window. Only a delivered outcome enters the window, so an offline operator's miss never blocks a retry.
- `validate_live_notify_target` returns an error string for an empty target, a surviving `${` skeleton, or a missing `@`.
- `resolve_arbiter_api_key` reads the key from `~/.lupin/config`. On a missing file or bad field it logs `live_notify_disabled` and returns None.
- `build_dm_send_payload` and `make_dm_push_fn` send the body inline to `/api/dm/send`. A 201 is "dispatched". Any failure is "push_unavailable".
- `make_tmux_push_fn` wakes a dormant pane from the host with no idle gate. It frames the body as a one-way peer DM reminder.

## Don't
- Don't treat HTTP 200 from `/api/notify` as delivered. Read the outcome.
- Don't send a DM payload without `sender_project`. The server answers 422.
- Don't add a reply line to a tmux poke. The arbiter has no inbox.

## Invariants
- No hop fails silently. Every failure is an outcome value that the caller journals.
- The durable `dm-<persona>` board write stays the substrate for presence and receipt polling. The DM push does not replace it.
