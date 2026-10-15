---
capability: web-client-render-items-request-chips
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.requestChips.button@3159a9fc35
  - src.lupin_app.static.js.multiplexer.render.requestChips.renderRequestChip@01294a057d
  - src.lupin_app.static.js.multiplexer.render.requestChips.renderRequestBadge@ec77876d04
  - src.lupin_app.static.js.multiplexer.render.requestChips.paintRequestBadge@21e85a9744
  - src.lupin_app.static.js.multiplexer.render.requestChips.triageDayToIso@7dd2bc22d5
  - src.lupin_app.static.js.multiplexer.render.requestChips.requestKey@fbb483a7d8
  - src.lupin_app.static.js.multiplexer.render.requestChips.RequestChipControllerImpl@ef6c320cb1
  - src.lupin_app.static.js.multiplexer.render.requestChips.wireRequestPane@8e08b0f57c
  - src.lupin_app.static.js.multiplexer.render.requestChips.createRequestChipController@59db166dd5
---
# Request chips

Shows a manager's pending promote or demote request on a board row, with Approve and Deny, and a count badge on the section header.

## Elements
- `renderRequestChip( task, nowMs )` returns a `.task-request-chip` or null when the row has no pending ruled move. It holds text with age, a detail span, Approve and Deny buttons, and a status span.
- A demote chip also carries a date input labelled `TRIAGE_DATE_LABEL`. `taskRowDisclosed.ts` calls `renderRequestChip` and passes no chip for the epic board, so only the task list and holding area show one.
- `button( cls, label, taskId )` builds one of those action buttons, and `requestKey( chip )` returns `taskId@requestTs`, the key for remembered state.
- `renderRequestBadge( testid )` returns a hidden span. `paintRequestBadge( badge, counts, key )` sets its text and hides it when the text is empty.
- `triageDayToIso( day )` turns a `YYYY-MM-DD` value into an ISO time at 09:00 local, or null when empty or unparseable.

## Behaviour
- `RequestChipControllerImpl( store )` handles clicks, keeps typed dates, and fills details. `handleClick` sends a verdict and returns true when the click hit Approve or Deny.
- It sends one verdict per task at a time, disables the buttons meanwhile, and keeps a refusal message for the next repaint.
- `hydrate( container )` restores refusals and dates, then fills the detail from the store cache or loads it.
- `createRequestChipController( store )` returns that controller. No production code outside the file calls it; only unit tests do.

## Wiring
- `wireRequestPane( opts )` places the badge after `countEl`, repaints it on `store_request_badges_changed`, and listens for date input. It returns `handleClick`, `hydrate` and `dispose`. The task list and holding area renderers call it.

The row template builds the chip, and the pane wiring owns the controller, the badge and the listeners.
