---
capability: web-client-render-task-row-controller
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.taskRowController.reasonMicContextId@c81468f4d4
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController@16e5a78be9
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController.constructor@774aeb6e6d
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController.operatorStateHandlers@150ce9c1ca
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController.dispose@0e59932ce0
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController.handleClick@7e0c1f6f7a
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController.handleKeydown@848bf2b3e3
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController.handleChange@320e292dd5
  - src.lupin_app.static.js.multiplexer.render.taskRowController.TaskRowController.renderRowError@52a66df123
  - src.lupin_app.static.js.multiplexer.render.taskRowController.deriveEditErrorMessage@997b63b391
---
# Web client: task row controller

The click, change and key handling for the shared task row, one controller per pane.

The row it drives is in [[web-client-render-task-row-cells]]; the verb table is in [[web-client-render-task-verbs]].

## What it does
- The options are `container`, `writer` (`patchTask`, `transitionTask`), `logLabel` and optional recorder, token, timer and `onTransitionSettled` hooks. The constructor ensures the drop-reason datalist exists.
- `handleClick` returns true when a control consumed the click. It tries the 📄, the mic, Update, Submit, the toggle, then the id cell. `handleKeydown` sends Enter and Space on the 📄 or the id cell the same way.
- `handleChange` re-shapes the row for a new verb, re-arms Update for a new priority, and PATCHes `owner_persona` at once for a new owner.
- A new verb sets the reason placeholder and disarms Submit. It disables and clears the reason box when the verb takes none. It offers the datalist only for drop and adds a date input only when needed.
- Submit refuses with the verb's own complaint when a reason or date is missing. A terminal verb arms on the first click ("Confirm …") and posts on the second, through `transitionExtras`.
- Update PATCHes only `priority`, and only when it differs from `data-original`.
- `reasonMicContextId( id )` is `task-reason-<id>`. The mic records into its own row's reason box; a second click stops it.
- A 404 on a write counts as success with `gone` true. Any other failure restores the optimistic state and shows `deriveEditErrorMessage`: "Edit failed (HTTP n)" or "Edit failed: <message>". A non-Error throw gets a bare "Edit failed".
- `renderRowError( id, message )` paints or clears the stripe. `operatorStateHandlers` returns the verb, priority and error handlers. `dispose` closes the 📄 overlay.

## Don't
- Don't look a control up by task id across the pane. The epic board paints a row twice, so lookups use the pressed control's own group.
