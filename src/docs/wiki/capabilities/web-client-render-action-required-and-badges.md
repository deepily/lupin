---
capability: web-client-render-action-required-and-badges
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.ActionRequiredRenderer.arProgressPercent@86000ebf24
  - src.lupin_app.static.js.multiplexer.render.ActionRequiredRenderer.paintProgress@9facf19afc
  - src.lupin_app.static.js.multiplexer.render.ActionRequiredRenderer.applyPausedUi@6261041709
  - src.lupin_app.static.js.multiplexer.render.ActionRequiredRenderer.formatResponse@847a151bc5
  - src.lupin_app.static.js.multiplexer.render.ActionRequiredRenderer.cssEscape@6428b04fa5
  - src.lupin_app.static.js.multiplexer.render.ActionRequiredRenderer.createActionRequiredRenderer@65cd4059bf
  - src.lupin_app.static.js.multiplexer.render.ListenerErrorRenderer.ListenerErrorRendererImpl@8c278622e5
  - src.lupin_app.static.js.multiplexer.render.ListenerErrorRenderer.createListenerErrorRenderer@ad4b74ff6d
  - src.lupin_app.static.js.multiplexer.render.MissedBadgeRenderer.MissedBadgeRendererImpl@233607d9f7
  - src.lupin_app.static.js.multiplexer.render.MissedBadgeRenderer.createMissedBadgeRenderer@7d844c9c4c
  - src.lupin_app.static.js.multiplexer.render.PersonaModalRenderer.PersonaModalRendererImpl@e32fc502f0
---
# Action-required pane and small badge renderers

Four render modules draw the Action Required pane, two badges and the persona popovers; see [[web-client-notification-panes]].

- `createActionRequiredRenderer` builds the pane renderer from an event bus and an action-required store. It paints and subscribes to nothing until `mount()`; a second `mount()` without `unmount()` throws.
- `ActionRequiredRenderer.arProgressPercent` returns remaining time as a percent of the timeout, clamped to 0..100, and 0 when the timeout is not positive.
- `ActionRequiredRenderer.paintProgress` sets the progress fill width from `arProgressPercent`. The fill gets `danger` at 25% or less, `warning` above 25% up to 50%, else neither.
- `ActionRequiredRenderer.applyPausedUi` toggles `paused` on the card, countdown, fill and pause button. It swaps the button glyph and title, and, on a card that has a header, adds or removes one grace-period message after it.
- `ActionRequiredRenderer.formatResponse` turns a recorded response into text. A string is kept as is, and a missing response reads "(no response recorded)". An answers map becomes `header: value` pairs joined by a semicolon and a space.
- `ActionRequiredRenderer.cssEscape` escapes an id for a selector. It uses `CSS.escape` when present, else backslash-escapes every character outside letters, digits, underscore and dash.
- `ListenerErrorRendererImpl` (made by `createListenerErrorRenderer`) subscribes to `listener_error` on `mount()`. Each event goes to a sink, which defaults to the debug error writer, and the badge count rises by one.
- The `ListenerErrorRendererImpl` handler catches its own failures and falls back to `console.error`. Repeated errors replace one badge, and dismissing it clears the root and resets the count.
- `MissedBadgeRendererImpl` (made by `createMissedBadgeRenderer`) paints the badge on `mount()` and again on every `store_missed_changed` event. At a count of zero or less the root is empty. Its Reset button calls the store's `reset()` and ignores a rejection, so the badge stays for a retry.
- `PersonaModalRendererImpl` keeps one popover per sender that has a voice persona inside `#persona-modal-portal`. `mount()` throws if that element is missing under the root, and builds popovers for senders already in the store.
- On `store_senders_changed`, `PersonaModalRendererImpl` reconciles everything for `hydrated` or a missing sender id. It removes the popover on `removed` or when the persona is gone. An update replaces content in place.

## How the parts work together

Each renderer is created with an event bus, and all but the listener-error one also with a store. It is then mounted on a root element. It repaints only when an event arrives. The action-required renderer also repaints the active card on timer ticks and pause changes without a full rebuild. Unmounting detaches the listeners and clears what the renderer drew. The action-required renderer also drops its keyboard shortcuts and leaves a placeholder when its list is empty.

## Don't

- Don't mount any of these twice without unmounting first; each throws on the second mount.
