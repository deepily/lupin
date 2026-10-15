---
capability: web-client-render-notifications-list
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.DEFAULT_SENDER_SORT@8a10989f41
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.defaultReportFailure@b2faad76d3
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.defaultProxyRatifyOpener@7608551fa4
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.cardSignature@ea206aa28a
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.paintVolatileHeader@2b2a1eba34
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.paintVolatileState@a5ee21e139
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.canPatchCard@5390a9d460
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.patchCard@239e4366dc
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.captureCardFocus@5ecec79f63
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.restoreCardFocus@88a5ea7b84
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.mergeInFreshOrder@744be04ed5
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.sameCardInputs@2522f954c9
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.cssEscape@6428b04fa5
  - src.lupin_app.static.js.multiplexer.render.NotificationsListRenderer.createNotificationsListRenderer@d8eeb73627
  - src.lupin_app.static.js.multiplexer.render.NotificationsHeaderRenderer.clearConfirmMessage@92a9c1b77f
  - src.lupin_app.static.js.multiplexer.render.NotificationsHeaderRenderer.NotificationsHeaderRendererImpl@303a1aaf8e
  - src.lupin_app.static.js.multiplexer.render.NotificationsHeaderRenderer.createNotificationsHeaderRenderer@34bdd8065e
---
# Notifications list and header renderers
These two renderers draw the sender cards and the section header controls of the notifications pane.

- `DEFAULT_SENDER_SORT` orders sender cards by newest activity first. A boot-time comparator option replaces it.
- `defaultReportFailure` logs the message to the console and raises an alert. `defaultProxyRatifyOpener` opens `/app/admin/proxy-ratify` in the tab named `lupin-proxy-ratify`.
- `createNotificationsListRenderer` needs `eventBus` and `stores`. Timezone, sort, API and confirm hooks are optional. It returns the renderer.
- `cardSignature` returns the card's HTML with the active class, active dot and status glyph blanked, then restores them.
- `paintVolatileHeader` copies those three parts from a fresh card. `paintVolatileState` sets them from an active flag and the last-active time.
- `sameCardInputs` is true when sender, vote text and every notification object match the last render.
- `canPatchCard` is true only for an append-only change. Earlier rows and the sender, apart from unread count, last-active time and session name, are unchanged. The vote text only extends, and no new row has a progress group id.
- `patchCard` swaps in the fresh header, toggles the active class, updates day counts and merges in new day accordions and rows.
- `mergeInFreshOrder` inserts missing children by `data-id-hash`, anchored on kept nodes. It never moves or removes a live child.
- `captureCardFocus` records which element holds focus inside the cards. `restoreCardFocus` refocuses it, or its replacement, without scrolling.
- `cssEscape` uses `CSS.escape` when present and otherwise backslash-escapes characters outside letters, digits, underscore and dash. `clearConfirmMessage` builds "Clear all N notification(s) (window)? This cannot be undone." with the plural only when N is not 1.
- `NotificationsHeaderRendererImpl` builds the count, history panel, window picker, Clear All and bounce button. The Mine, Not Mine and All Users switch is hidden unless `isAdmin` is true when the header mounts. `createNotificationsHeaderRenderer` throws without a store.

## How the parts work together
On each store change the list renderer first compares card inputs, then the signature, then tries an append-only patch, and only then replaces a card. Cheaper paths keep the live node, so scroll and focus survive. The header renderer is separate. It shows the total count. Clear All deletes visible entries one by one and removes only the successes from the store.
