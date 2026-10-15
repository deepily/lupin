---
capability: web-client-render-cards-sender
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.senderCard.renderSenderCard@1a5f253f50
  - src.lupin_app.static.js.multiplexer.render.templates.senderCard.renderVoiceInputRow@351c0ac188
  - src.lupin_app.static.js.multiplexer.render.templates.senderCard.activeIndicator@80151e6632
  - src.lupin_app.static.js.multiplexer.render.templates.senderCard.senderStatusGlyph@50f3a6f01c
  - src.lupin_app.static.js.multiplexer.render.templates.senderCard.groupByDateKey@d5aadb2e42
  - src.lupin_app.static.js.multiplexer.render.templates.senderCard.hexToRgbTriplet@02050a630d
  - src.lupin_app.static.js.multiplexer.render.senderProject.projectFromSenderId@4e879c12d5
  - src.lupin_app.static.js.multiplexer.render.templates.slugify.slugifySenderId@6aa73841ff
---
# Sender card

Builds the per-sender card of the multiplexer notification list, plus two small helpers that parse or slug a sender id.

## What it draws
- `renderSenderCard( sender, notifications, opts )` returns a detached card element. Options carry `appTimezone`, `ttsInteractionMode`, `now`, `predictionVote` and `isActive`. `NotificationsListRenderer` is the only production caller.
- It sets the sender id as both `data-id-hash` and `data-sender-id`, and marks worker senders. A voice persona sets the `--persona-color` variable and, when parseable, `--persona-color-rgb`.
- Notifications with a progress group id collapse to one row: the oldest in each group is kept. Rows are grouped by date and mounted through `keyedListMerge`.
- `renderVoiceInputRow( sender, sessionHash, mode )` is private. It builds the mode button, microphone button, text input and Send button for a session whose id has a hash suffix. Solo and chorus modes use different icons and titles.
- `activeIndicator( isActive )` returns a glyph and title pair. `senderStatusGlyph( lastActiveTs, now )` returns green under an hour, yellow under a day, otherwise white.
- `groupByDateKey` is private: it buckets rows by date key, newest row first and newest date first.
- `hexToRgbTriplet( hex )` turns a three or six digit hex color into a comma separated triplet, or null when it is not a color.

## Id helpers
- `projectFromSenderId( senderId )` returns the upper-cased project from a `claude.code@<project>.deepily.ai` id. It returns a fixed fallback label when the id does not match. The list renderer and the action required chrome call it.
- `slugifySenderId( senderId )` replaces every character outside letters, digits, underscore and dash with a dash. `personaModal` and the card's persona button use it for element ids.

The card is a pure template. The list renderer decides which senders are active and repaints a kept card's indicator itself, using the exported `activeIndicator` so the two never disagree.
