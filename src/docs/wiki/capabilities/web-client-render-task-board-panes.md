---
capability: web-client-render-task-board-panes
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.EpicBoardRenderer.createEpicBoardRenderer@a8dffca240
  - src.lupin_app.static.js.multiplexer.render.FinishedTasksRenderer.readShown@2cba06ca43
  - src.lupin_app.static.js.multiplexer.render.FinishedTasksRenderer.writeShown@9496fa6ce3
  - src.lupin_app.static.js.multiplexer.render.FinishedTasksRenderer.createFinishedTasksRenderer@b3c5cc478a
  - src.lupin_app.static.js.multiplexer.render.FleetStatusRenderer.buildSizeCapControls@74f4b01894
  - src.lupin_app.static.js.multiplexer.render.FleetStatusRenderer.createFleetStatusRenderer@abb281e0d6
  - src.lupin_app.static.js.multiplexer.render.HoldingAreaRenderer.planButtonId@e10e89d967
  - src.lupin_app.static.js.multiplexer.render.HoldingAreaRenderer.createHoldingAreaRenderer@1d5f9a6644
  - src.lupin_app.static.js.multiplexer.render.TaskListRenderer.createTaskListRenderer@f4640f460f
  - src.lupin_app.static.js.multiplexer.render.JobsPaneRenderer.JobsPaneRendererImpl@fafff4b6c6
  - src.lupin_app.static.js.multiplexer.render.JobsPaneRenderer.historyWindowLabel@9fc5b246a7
  - src.lupin_app.static.js.multiplexer.render.JobsPaneRenderer.deriveErrorMessage@58879229f0
---
# Task board pane renderers

These six renderers paint the Epic Board, Finished Tasks, Fleet Status, Holding Area, Task List and Jobs panes; see [[web-client-task-board-panes]].

- `createTaskListRenderer` builds the Task List pane. It repaints on `store_task_list_changed`, keeps only open rows, except a looked-up ticket that is shown alone. It shows "Sign-in required", "No open tasks" or "Store unreachable" when needed.
- `createEpicBoardRenderer` builds the Epic Board. It reads the Task List's store and owns no timer, but its refresh button and row writes ask that store to refetch. Its count is epics, not rows; the unreachable state leaves the count untouched.
- `createHoldingAreaRenderer` builds the Holding Area, repainting on `store_holding_area_changed`. Its count is the total of held rows across filer groups, and `—` when the store is signed out, unavailable or unreachable.
- `HoldingAreaRenderer.planButtonId` turns a plan button's `data-filer` and `data-plan` attributes into the plan id used by approve and arm-then-confirm.
- Each pane builds its status paragraph with the shared `messageEl` of [[web-client-render-dom-and-doc-links]], passing its own message class stem.
- `createFleetStatusRenderer` builds the Fleet Status pane. It shows live sessions only until the offline toggle is on, grouped by manager, with sign-in and arbiter-offline states.
- `buildSizeCapControls` builds the fleet cap slider and skeleton crew switch once. Each stays hidden until its own values arrive and re-hides on a bad payload.
- `createFinishedTasksRenderer` builds the Finished Tasks pane from `store_finished_tasks_changed`, with pills for statuses. Only `done` is shown by default.
- `readShown` and `writeShown` load and save the shown statuses in storage. A `null` storage means no persistence, and a throwing storage falls back to the default or is ignored.
- `JobsPaneRendererImpl` paints the Jobs pane from `store_jobs_changed`. Deleting a card removes it at once, calls the history or queue endpoint by bucket, and treats a 404 as success.
- `deriveErrorMessage` turns a failed delete into "Delete failed (HTTP n)", "Delete failed: message" or plain "Delete failed". `historyWindowLabel` returns "all time" or "last N day(s)" for confirmation text.

## How the parts work together

Each `create...Renderer` factory returns a renderer that paints nothing until `mount` is called. It then repaints whenever its store emits a change event on the bus. The Task List and Epic Board share one store, so they read the same rows. Each pane handles an unreachable store differently.
