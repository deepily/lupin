---
capability: web-client-render-broadcast-and-commons-cards
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.broadcastCard.renderBroadcastCard@fc592bffb8
  - src.lupin_app.static.js.multiplexer.render.templates.commonsActivityEntry.renderCommonsActivityEntry@e1411f995b
---
# Broadcast card and commons activity entry

The markup of the broadcast compose card and of one row in its Recent Activity list.

## What it does
- `renderBroadcastCard( cardOpen )` returns a fresh fragment holding `#broadcast-submit-card`.
- The card carries `data-card-open` as `"true"` or `"false"`, and the toggle glyph is ▼ when open and ▶ when closed.
- It holds a recipients row with a refresh button, a mic, a textarea and a Send button that starts disabled.
- It also holds a status line, an empty `#broadcast-aggregate-panel` for the ack tally, and the Recent Activity chrome with its window and filter selects.
- `renderCommonsActivityEntry( entry, opts )` returns one `.commons-activity-entry` row with the persona icon, name, topic chip, markdown body and time.
- The row sets `--persona-color` when the entry has a colour. A missing persona name reads "—" and a missing icon reads "·".
- The topic chip is hidden for reserved topics, and a `dm-<x>` topic reads `@<x>`.
- On the `broadcast-acks` topic a body of `completed`, `skipped` or `rejected-malformed` is rewritten as a sentence. Other bodies pass through.
- The time is `HH:MM` in `opts.appTimezone`, or `--:--` when the timestamp is missing or invalid.

## How the parts work together
`BroadcastCardRenderer` appends the card with the store's open state and wires its controls. `CommonsActivityRenderer` mounts onto the activity section and calls the entry builder for each row.

## Invariants
- The Show more toggle starts hidden. The renderer reveals it on overflow.
