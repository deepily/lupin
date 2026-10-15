---
capability: web-client-render-task-list-model
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.taskListModel.isOpenStatus@d7628b5450
  - src.lupin_app.static.js.multiplexer.render.taskListModel.statusRank@0f5de23457
  - src.lupin_app.static.js.multiplexer.render.taskListModel.priorityRank@175c62707b
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskOwnerLabel@665ec781eb
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskTitleLabel@3e0307b090
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskIdLabel@67278acc2c
  - src.lupin_app.static.js.multiplexer.render.taskListModel.truncateTaskTitle@d919cea055
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskBodyIsEmpty@07768a8e4e
  - src.lupin_app.static.js.multiplexer.render.taskListModel.asRows@709bdedc7a
  - src.lupin_app.static.js.multiplexer.render.taskListModel.groupTasksByOwner@a71b8b95b7
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskCellOrDash@9f97737767
---
# Web client: task list model

The DOM-free half of the task list: status and priority ranking, labels and the owner grouping.

The formatters and the parked count are in [[web-client-render-task-list-formatters]]. The table that paints this model is [[web-client-render-task-list-table]].

## What it does
- `isOpenStatus` is false only for `done`, `dropped` and `wont_fix`. A missing or empty status counts as open.
- `statusRank` orders blocked 0, in_progress 1, claimed 2, review 3, queued 4, parked 5 and not_approved 6. Unknown or missing is 7, then done 8, wont_fix 9, dropped 10.
- `priorityRank` turns `P<n>` into `n`. Anything else, including null, is 99 and sorts last.
- `taskOwnerLabel` falls back to "Unassigned", `taskTitleLabel` to "(untitled)". `taskIdLabel` returns the first 8 characters of the id, or "—".
- `truncateTaskTitle` cuts a label to 60 characters plus "…". Only tests call it; the row template shows the whole title.
- `taskBodyIsEmpty` is true for a missing, null or whitespace-only `body`.
- `asRows` returns the input when it is an array, and an empty array otherwise.
- `taskCellOrDash` returns "—" for a falsy value or the word "none", and the value otherwise.
- `groupTasksByOwner( tasks )` returns `{ totalCount, groups }`. Owners sort alphabetically and the Unassigned group comes last. Rows sort by priority, then status rank, then title.

## How the parts work together
`groupTasksByOwner` is the entry point. It uses `priorityRank`, `statusRank` and `taskTitleLabel` as its three sort keys, and `totalCount` counts every input row. It does not drop terminal rows: the caller filters with `isOpenStatus` first. The epic board reuses both ranks, and the holding area reuses `priorityRank`.

## Don't
- Don't "resync" the 60-character title cap to the store's 120. The two caps answer different questions.
