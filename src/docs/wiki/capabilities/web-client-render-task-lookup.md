---
capability: web-client-render-task-lookup
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.taskLookupBox.describeLookupFailure@c7b5ede790
  - src.lupin_app.static.js.multiplexer.render.taskLookupBox.lookupFailureState@10cf2ae2c9
  - src.lupin_app.static.js.multiplexer.render.taskLookupBox.renderTaskLookupBox@e34512d73c
  - src.lupin_app.static.js.multiplexer.render.taskLookupBox.lookupKindFor@c4f2916a92
---
# Web client: task lookup box

The search box that finds one ticket by its id and hands the row up so the list can show only that row.

## What it does
- `renderTaskLookupBox( opts )` returns `{ root, input, result, submit, clear }`. It needs `opts.fetchTask( path )`; `onFound( task )` and `onCleared()` are optional.
- `submit` trims the input and asks `taskLookupPath` for a request path. An unusable reference shows the refusal, `data-state="refused"`, and sends nothing.
- Otherwise it shows "Looking up…" and sends one GET through `fetchTask`. On success it calls `onFound`, shows "Showing the one matching ticket — ✕ to see the whole list." and unhides ✕.
- On failure it shows `describeLookupFailure` and sets `data-state` from `lookupFailureState`. `submit` never throws.
- `clear` empties the input and the result, hides ✕ and calls `onCleared`. The 🔎 button and the Enter key both submit.
- `describeLookupFailure( typed, error )` answers 404 with `No ticket matches "<typed>".` and 422 with the server's `detail`. A 401 gets the shared signed-out sentence and anything else the shared unreachable one.
- `lookupFailureState` maps 404 to `missing`, 422 to `ambiguous`, 401 to `auth_required` and anything else to `unreachable`.
- `lookupKindFor( typed )` returns the kind `classifyTaskRef` gives: `full`, `prefix` or `invalid`.

## How the parts work together
The box does not filter anything itself. `onFound` hands the row up and the pane shows only it, and `clear` fires `onCleared` so the pane restores the whole list. `lookupFailureState` is what other code branches on, so each failure keeps its own token even when two share wording.

## Invariants
- A `full` reference is a canonical UUID or 32 hex characters. A `prefix` is at least 4 hex characters, hyphens allowed.
