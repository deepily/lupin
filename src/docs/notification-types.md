# Notification Types Reference

> Catalogue of the custom `type` values accepted by `POST /api/notify/*` and emitted
> through the `notification_queue_update` WebSocket envelope.
>
> **Last verified**: 2026-05-12 — `valid_types` mirror at `src/cosa/rest/routers/notifications.py:359-363`.
>
> For the full notification system (architecture, queues, persistence, CLI clients),
> see [`notification-api.md`](notification-api.md). For the WebSocket event catalog,
> see [`websocket-events.md`](websocket-events.md). This document is a focused
> reference for **what the `type` field means** and how the UI handles each value.

---

## Overview

Every notification envelope carries a `type` field (alias `notification_type`). The
server validates it against an allowlist in `src/cosa/rest/routers/notifications.py`.
Three categories exist:

| Category | Values | UI behavior |
|---|---|---|
| **User-facing messages** | `task`, `progress`, `alert`, `custom`, `user_initiated_message` | Render as a notification card; may speak via TTS |
| **Session-scoped control** | `session_topic` | Header span update only — no notification card |
| **Custom state-update** | `voice_persona_assigned`, `voice_persona_released`, `conversation_mode_changed`, `commons_broadcast_ack` | Dispatch through a `switch` in `notifications.js:5332` that handles the state mutation and returns BEFORE the message-render path |

The **custom state-update** category exists because the multiplexer / notifications-UI
needs out-of-band state changes (persona allocation, conversation-mode toggles,
broadcast acks) but the team agreed in
[`src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md`](../rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md)
that the notification envelope is the canonical transport — NOT new top-level
WebSocket events. New control signals MUST extend this category, not invent new
`notification_queue_update`-adjacent events.

---

## Catalogue

### `task` / `progress` / `alert` / `custom`

User-facing notification cards. Differ only in priority defaults and the icon
rendered in the card chrome. `custom` is the catch-all for ad-hoc messages from
agentic jobs or MCP shims.

### `user_initiated_message`

Notification envelope carrying an **action directive** for a CC session listener.
The `title` field encodes the action verb (e.g., `"action:conversation_mode_enter"`,
`"action:broadcast_received"`). The listener's `_handle_action()` dispatcher reads
the verb after `action:` and routes to the appropriate handler. UI does NOT render
these as visible notifications — they are consumed by the listener and produce
side effects (tmux injection, ack post).

Producers: `cosa/rest/routers/conversation_mode.py`, `cosa/rest/routers/commons.py`.

### `session_topic`

Session-scoped control message. The `session_name` field updates the per-session
header span in the notifications UI. Skipped by the message-render path entirely.

### `voice_persona_assigned`

Fires when a CC session is allocated a voice persona. Payload includes
`voice_persona = {name, voice_id, icon, color, ...}` and `sender_id`. UI cache
(`senderPersonaMap`) records the assignment so subsequent notification cards
render with the persona badge. See `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md`.

### `voice_persona_released`

Fires when a CC session's persona is released (session ended or `/clear`). UI
removes the persona from `senderPersonaMap` and from any visible card headers.

### `conversation_mode_changed`

Fires when a CC session enters or exits conversation mode. Payload includes
`session_id`, `active`, `displaced`, `displaced_by`. UI updates the strip-icon
mic overlay + monopoly-pin state. See
[`src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md`](../rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md)
for the full lifecycle.

### `commons_broadcast_ack` (Phase 2)

Fires when a CC session listener processes an inter-session-commons broadcast and
posts its ack. Originated by `CommonsAckWatcher` daemon in
`src/cosa/rest/commons_ack_watcher.py`, which tails the `broadcast-acks` reserved
topic in `<LUPIN_ROOT>/io/commons/broadcast-acks.md` and dispatches one
`commons_broadcast_ack` notification per matching ack.

#### When it fires

- A user submits a broadcast via `POST /api/commons/broadcast-to-cc-sessions`
  with `require_ack=true` (the default).
- The server registers the `broadcast_id` in `commons_in_flight_broadcasts` and
  fans out one `action:broadcast_received` notification per recipient session.
- Each recipient listener processes the directive and posts an ack to
  `broadcast-acks` via `CommonsStore.post(topic="broadcast-acks", ...)`.
- The watcher daemon tails the topic every `commons broadcast ack watch interval seconds`
  (INI key, default 1) and dispatches one `commons_broadcast_ack` notification
  per new ack whose `metadata.broadcast_id` matches a tracked in-flight broadcast.

#### Payload shape

```jsonc
{
  "type"          : "commons_broadcast_ack",
  "user_id"       : "ricardo.felipe.ruiz@gmail.com",     // originating user — same-user routing
  "message"       : "",                                   // empty by convention
  "suppress_ding" : true,
  "payload": {
    "broadcast_id"  : "5e7cafe1-2b3d-4567-89ab-cdef01234567",
    "session_id"    : "sess-maria-aaa12345",
    "persona_name"  : "Maria",
    "persona_icon"  : "🌸",
    "persona_color" : "#A040A0",
    "status"        : "completed",                        // or "skipped" / "rejected-malformed"
    "body_summary"  : "regenerated visual baselines"       // server-controlled summary (≤200 chars)
  }
}
```

#### UI handling

`notifications.js:5370` switch case `"commons_broadcast_ack"` delegates to
`window.broadcastPanel.handleAck(notification)` (defined in
`src/fastapi_app/static/js/broadcast-panel.js`). The panel updates its in-page
aggregate (`N/Total complete`) and renders the per-session row with the
listener-side persona stamp.

Defense-in-depth (Pass 2 T10): `body_summary` is rendered via `.textContent`
**only** — never `.innerHTML` — even though the field is composed server-side
from the broadcast body. Test coverage at
`src/tests/e2e_ui/test_broadcast_panel.py::TestBroadcastAggregate::test_body_summary_xss_lands_as_text_not_html`.

#### TTL semantics

The in-flight broadcast is tracked by `CommonsAckWatcher` for 5 minutes from
registration (matches the UI's auto-dismiss timer). Acks arriving after the
window are ignored silently. Unknown `broadcast_id` values (e.g., from a
different user's broadcast that somehow landed in this user's stream) are
silently dropped — the watcher requires the broadcast to be registered in its
local `_in_flight` dict for the user-routing payload field to be safe.

#### Cross-references

- Architecture: [`src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md`](../rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md) AC7 + AC9
- Producer: `src/cosa/rest/commons_ack_watcher.py:223-249` `_push_ack_event()`
- Consumer: `src/fastapi_app/static/js/broadcast-panel.js` `handleAck()`
- E2E coverage: `src/tests/smoke/test_broadcast_two_session_e2e.py` (backend) +
  `src/tests/e2e_ui/test_broadcast_panel.py` (UI)

---

## Adding a new custom notification type

1. Append the string to `valid_types` in `src/cosa/rest/routers/notifications.py:359-363`.
2. Add a `case "your_new_type":` branch in the switch at
   `src/fastapi_app/static/js/notifications.js:5332` that handles the state
   update and `return`s BEFORE the message-render path. The branch should never
   produce a visible notification card unless it's user-facing.
3. Document the trigger, payload shape, and UI handler here.
4. Reference the originating design doc.
5. Land unit tests for both the producer (server-side `_push_*_event`) and the
   consumer (UI switch branch — DOM-mocked or Playwright E2E).

The team agreed (Phase 1 of the WS event cleanup) that NEW transport-level WS
events are an anti-pattern; the canonical envelope is `notification_queue_update`
and the type discriminator does the routing.
