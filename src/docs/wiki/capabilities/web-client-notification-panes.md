---
capability: web-client-notification-panes
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.NotificationsListRendererImpl@3c9f4e9b98
  - src.lupin_app.static.js.multiplexer.render.ActionRequiredRenderer.ActionRequiredRendererImpl@3c2970d261
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.ActionRequiredStoreImpl.respondAndAwait@5bf13c5c25
  - src.lupin_app.static.js.multiplexer.render.BroadcastCardRenderer.BroadcastCardRendererImpl@ed8b9679ab
  - src.lupin_app.static.js.multiplexer.render.BroadcastAckTallyRenderer.BroadcastAckTallyRendererImpl@5e1b01b204
  - src.lupin_app.static.js.multiplexer.render.CommonsActivityRenderer.CommonsActivityRendererImpl@3c39de597e
  - src.lupin_app.static.js.multiplexer.render.FleetStatusRenderer.FleetStatusRendererImpl@c62b8d8f91
---
# Web client: notification panes

Each pane renderer owns one mount node and repaints from store events on the bus. Stores are in [[web-client-stores]]; frames are in [[websocket-events]].

## What it does
- `NotificationsListRendererImpl` paints sender cards and throws on mount without `#sender-cards-container`. Notification, sender and vote events only schedule one microtask render.
- Action-required rows are filtered out of the cards. A card keeps its node when its inputs or rendered signature are unchanged. Appended rows are patched in only under `canPatchCard`; otherwise the card is replaced.
- Card controls: ✨ POSTs `/api/notifications/generate-gist`; × DELETEs `/api/notifications/conversation/<sender>/<email>`; a date × DELETEs `/api/notifications/date/...`.
- `SenderCardRecorderRenderer` wires mic, send (POST `/api/notify`) and conversation mode (POST `/api/cosa-voice/speakerphone/<hash>`). `SenderCardConsoleButtons` adds a console button to a card only when a seat resolves.
- `NotificationsHeaderRenderer` counts `list()`. Clear All sends one `DELETE /api/notifications/<id>` per visible entry. The Mine / Not Mine / All Users switch is hidden unless `isAdmin()`.
- `ActionRequiredRendererImpl` paints the store's first item as the full card and the rest as queue rows, unless the first awaits activation. A change to a queued item repaints only the rows.
- Submit and ✕ call `respondAndAwait`, which POSTs `/api/notify/response`. P and Esc click the first card's own controls, and Y, N, C do on a yes/no card, unless focus is in an input.
- `BroadcastCardRendererImpl` loads `/api/commons/active-sessions`. After a confirm modal it POSTs `/api/commons/broadcast-to-cc-sessions` and hands the returned id to the tally.
- `CommonsActivityRendererImpl` inserts a `prepended` row alone when it matches the filter. `hydrated` and `filter-changed` redraw all rows.
- `FleetStatusRendererImpl` repaints on `store_fleet_status_changed`. The store polls `/api/arbiter/fleet-state` every 60000 ms once boot calls `startPolling`.

## Don't
- Don't add a card input without adding it to `inputsFor` or dropping the caches, as `setAppTimezone` does. Don't mutate a `Notification` row in place; rows are compared by identity.
- Don't answer a card by another route. This tree's `.ts` files POST `/api/notify/response` only from `respondAndAwait`, which refuses states other than pending or failed.
- Don't wait for a `BroadcastStore` event; it emits none. `BroadcastCardRenderer` must call `recipientsChanged` on the tally after the latest fetch settles, success or failure.

## Invariants
- A finished card stays 600 ms (responded, expired) or 1500 ms (cancelled), then the store removes it. A card never started is removed at once.
- `togglePause` returns true only when it pauses; it returns false on resume or when the card is not first, pending and started. The header count includes only pending, submitting and failed cards.
- `AckStore` keeps the latest ack per session id; acks without one are kept apart. `hydrate` replaces the fold rather than merging.
- Until `recipientsChanged` runs the tally shows "loading the recipient list…", and its deadline does nothing. Restore skips a tally older than ten minutes.
- `FleetStatusStore` maps a 401 to `auth_required` and any other failure to `unreachable`. The cap slider writes on `change`, not `input`.
- Once hydration has started, the empty list does not read "No notifications yet" while history loads or fails.
