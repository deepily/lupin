---
capability: web-client-render-broadcast-and-sender-cards
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.BroadcastAckTallyRenderer.shortId@496494d756
  - src.lupin_app.static.js.multiplexer.render.BroadcastAckTallyRenderer.el@7a8435acf6
  - src.lupin_app.static.js.multiplexer.render.BroadcastAckTallyRenderer.createBroadcastAckTallyRenderer@afaa1e2a85
  - src.lupin_app.static.js.multiplexer.render.BroadcastCardRenderer.chipButton@a61a8ffa04
  - src.lupin_app.static.js.multiplexer.render.BroadcastCardRenderer.buildStatusChip@77632a393e
  - src.lupin_app.static.js.multiplexer.render.BroadcastCardRenderer.formatSendStatus@39e97d8092
  - src.lupin_app.static.js.multiplexer.render.BroadcastCardRenderer.errorMessage@13770bd245
  - src.lupin_app.static.js.multiplexer.render.BroadcastCardRenderer.createBroadcastCardRenderer@c45d229648
  - src.lupin_app.static.js.multiplexer.render.CommonsActivityRenderer.createCommonsActivityRenderer@1d865313ce
  - src.lupin_app.static.js.multiplexer.render.SenderCardConsoleButtons.SenderCardConsoleButtonsImpl@99d87b1068
  - src.lupin_app.static.js.multiplexer.render.SenderCardConsoleButtons.setPressed@9f879b1d2f
  - src.lupin_app.static.js.multiplexer.render.SenderCardConsoleButtons.createSenderCardConsoleButtons@fd3b0632ec
  - src.lupin_app.static.js.multiplexer.render.SenderCardRecorderRenderer.SenderCardRecorderRendererImpl@5152aba6c2
  - src.lupin_app.static.js.multiplexer.render.SenderCardRecorderRenderer.createSenderCardRecorderRenderer@934910110c
  - src.lupin_app.static.js.multiplexer.render.SessionStripRenderer.SessionStripRendererImpl@5e1f17ed44
  - src.lupin_app.static.js.multiplexer.render.SessionStripRenderer.defaultStorage@4b08cf64c8
---
# Broadcast and sender card renderers

These six render modules draw the broadcast card and tally, the commons activity pane, the sender card controls and the session strip; see [[web-client-notification-panes]].

- `createBroadcastCardRenderer` builds the compose card. It throws when `store` is missing, and an optional `ackTally` is mounted into `#broadcast-aggregate-panel` when that panel exists.
- `chipButton` makes a recipient chip: a button, or a static span when not clickable. `buildStatusChip` makes the pills for "loading…", "failed to load: <message>" and "no active sessions". The last two carry the `no-recipients` class.
- `formatSendStatus` writes the post-send line: recipient count, the first 8 characters of the broadcast id, and any filtered-out sessions. `errorMessage` returns an Error's message, or the string form of anything else.
- A confirmed send posts with `require_ack` and `include_originator` true, then calls `track` on the tally with the returned id. Recipient refreshes after session changes wait 250 ms by default.
- `createBroadcastAckTallyRenderer` builds the tally. `shortId` returns the first 8 characters of a session id, or "unknown" for null. `el` makes an element of a given tag and sets its text through `textContent`.
- The tally times out after 5 minutes by default. A complete tally is dismissed quietly, and an unknown roster defers the deadline. With `storage` given it saves the tracked id and restores it on mount if under 10 minutes old; restoring starts no timer.
- Until the recipient list has loaded, the summary shows only the acknowledged count, with no total or "waiting on" row. A failed load says it could not load the list.
- `createCommonsActivityRenderer` throws without `stores.commons`, and `mount` throws if `#commons-activity-entries` is missing. It follows `store_commons_changed`, loads history without blocking, and saves collapse state only when `viewState` is passed.
- `SenderCardConsoleButtonsImpl` watches the card container with a MutationObserver. Each card whose seat resolves gets one `▤` button, left of the persona badge or at the header's end. `setPressed` writes `aria-pressed` only when the value changes.
- `SenderCardRecorderRendererImpl` wires the mic, send and conversation-mode controls on rows `senderCard.ts` already drew. `createSenderCardRecorderRenderer` needs the current user's email; send posts to `/api/notify`, and the mode toggle makes no optimistic flip.
- `SessionStripRendererImpl` merges one icon per session, sorted by `assigned_at`, and runs the focus and hide-inactive toggles. `defaultStorage` returns `localStorage`, or null when reading it throws.

## How the parts work together

The card sends a broadcast and hands its id to the tally, which counts acknowledgements and reports who is still pending. The strip's focus mode and the sender card controls act on the same cards the notification list draws. Each renderer is created by its factory, painted at `mount`, and torn down at `unmount`.
