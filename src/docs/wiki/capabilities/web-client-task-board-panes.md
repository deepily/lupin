---
capability: web-client-task-board-panes
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.TaskListRenderer.TaskListRendererImpl@3df3eebbb2
  - src.lupin_app.static.js.multiplexer.render.HoldingAreaRenderer.HoldingAreaRendererImpl@d685c4431b
  - src.lupin_app.static.js.multiplexer.render.EpicBoardRenderer.EpicBoardRendererImpl@056b241644
  - src.lupin_app.static.js.multiplexer.render.FinishedTasksRenderer.FinishedTasksRendererImpl@0cd95df941
  - src.lupin_app.static.js.multiplexer.render.taskVerbs.verbLegality@8816df8745
  - src.lupin_app.static.js.multiplexer.render.taskVerbs.transitionExtras@cbed0f71fd
  - src.lupin_app.static.js.multiplexer.render.epicBoardModel.groupTasksByEpic@c0346bfd19
---
# Web client: task board panes

Four panes show the task store: the task list, the epic board, the holding area and the finished tasks. Each repaints on its store's change event. State lives in [[web-client-stores]]; the transport is [[web-client-transport-and-auth]].

## What it does
- `TaskListRenderer` has four states: sign-in banner, unreachable (last-known rows kept after one good fetch), empty, and a table of open rows grouped by owner.
- The task list and epic board keep their collapse state in raw `localStorage` keys, not `StorageService`. Owners start expanded; epics start collapsed except the group waiting on Rick.
- `taskVerbs` offers park, drop, demote, wont_fix, fixed, unpark and approve. `verbLegality` offers nothing on a terminal row, and approve only on `not_approved`.
- `transitionExtras` sends the park reason as `park_reason` and other reasons as `reason`. Fixed sends the attestation "operator (multiplexer)", which the server replaces with the login identity.
- `wont_fix` and `fixed` need two clicks. Task-list writes are optimistic and roll back on failure, and on a 202 awaiting-approval answer.
- Holding-area writes are not optimistic. The row changes after the refresh, and a failure or a 202 shows an error stripe.
- `HoldingAreaRenderer` groups `not_approved` rows by filer, then plan. Batch buttons are per filer and act on the rows whose Approve is enabled; wont_fix needs one reason for all.
- Each plan has an Approve all button. Its first press arms it and opens the plan. Closing the plan disarms it; a repaint keeps it armed only while the plan holds the same rows.
- A batch button arms on the first press and posts on the second. Rows go one at a time, every row is tried, and one refresh follows the last.
- `EpicBoardRenderer` groups rows by a `correlation_key` starting `epic:`. `groupTasksByEpic` sends rows with no epic key to a drift group, never drops them.
- The epic board marks rows blocked on Rick as a highlight; the rows stay under their epic. Rows sort by priority, then status, then title.
- `FinishedTasksRenderer` reads the task event stream, not the task list, because the list has no terminal timestamp. It polls every 60 s, with a 1 to 14 day window.
- The holding-area header shows the flow ratio. The gate reads open only below the threshold; at the threshold it reads closed.
- A manager's promote or demote request shows as a chip on the row. Every viewer sees Approve and Deny; the server refuses anyone but Rick.

## Don't
- Don't trust the `holdingAreaBatch.ts` header that says approve needs no confirm. `runBatch` arms both batch buttons.
- Don't read an em dash in the finished pane's counts as zero. It means the count was never measured.
- Don't expect a park or demote to go through without a reason and a date. The row refuses before any request is sent.

## Invariants
- Finished tasks fetch done, dropped and wont_fix but show only done until the other pills are toggled; `not_approved` is absent.
- The `epic:unassigned` group sorts last; the others sort biggest first, then by key.
