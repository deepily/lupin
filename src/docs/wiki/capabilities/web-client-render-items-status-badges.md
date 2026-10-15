---
capability: web-client-render-items-status-badges
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.pokeMuteSwitch.isState@d754253c90
  - src.lupin_app.static.js.multiplexer.render.pokeMuteSwitch.createPokeMuteSwitch@51aec365d9
  - src.lupin_app.static.js.multiplexer.render.templates.listenerErrorBadge.renderListenerErrorBadge@c9ffa6a3c2
  - src.lupin_app.static.js.multiplexer.render.templates.missedBadge.renderMissedBadge@d33c9d4b8d
  - src.lupin_app.static.js.multiplexer.render.templates.truncationBanner.line@5982b81ec6
  - src.lupin_app.static.js.multiplexer.render.templates.truncationBanner.queryLimit@a28c39b137
  - src.lupin_app.static.js.multiplexer.render.templates.truncationBanner.heldWarningCount@2b3ac47ab7
  - src.lupin_app.static.js.multiplexer.render.templates.truncationBanner.renderTruncationBanner@4232bceec4
---
# Status badges and banners

Small pieces that tell the operator something is off: poke mute, display errors, missed items and truncated boards.

## Poke mute
- `createPokeMuteSwitch( opts )` returns `{ element, refresh, toggle }`. The button is created hidden, since the Fleet Status toggle now covers it.
- `refresh()` reads `/api/heartbeat/poke-mute` and paints the answer, or an "unknown" face on failure. `toggle()` does nothing while the state is unknown; otherwise it puts the opposite state and paints what the server returns, or re-reads on failure.
- The button is disabled for non-admins, while the state is unknown, and during a flip. `isState( value )` checks for an object with a boolean `muted`. `boot.ts` calls the factory.

## Badges
- `renderListenerErrorBadge( opts, handlers )` returns a status div. It shows the error count and last event type, and the last message is its title. A Dismiss button calls `onDismiss`. `ListenerErrorRenderer.ts` calls it.
- `renderMissedBadge( opts, handlers )` returns a div reading "N missed while away" with a Reset button for `onReset`. `MissedBadgeRenderer.ts` calls it.

## Truncation banner
- `renderTruncationBanner( composite, queryString, headerCount )` returns paragraph elements, possibly none. It adds a cut-off line in three cases. Those are `has_more` set, a total above the count, or a full page with no total.
- Server warnings follow in one line. A holding-area warning becomes "N waiting for your approval" and is dropped when N equals `headerCount`.
- `queryLimit( queryString )` returns the `limit=` value or NaN. `heldWarningCount( warning )` returns the held count or null. `line( text, extraClass )` builds one paragraph.

Each template returns elements and leaves placement to its renderer. The truncation banner is called by the task list and holding area panes with their own query strings.
