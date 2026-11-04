---
capability: web-client-task-status-filter
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.shared.task-status-filter.activeChips@ffabf47e0a
  - src.lupin_app.static.js.shared.task-status-filter.toggleChip@30c46e77e5
  - src.lupin_app.static.js.shared.task-status-filter.filterTasksByChips@0059751b34
  - src.lupin_app.static.js.shared.task-status-filter.publishOnWindow@c9235b67e8
---
# Task list status filter

The status chips on the live task list's bar. `shared/task-status-filter.js` holds the whole policy in one table, `TASK_STATUS_CHIPS`, so nothing else in the page or the tests names a status. The older page, `notifications.js`, reads it from `window.LUPIN_TASK_STATUS_FILTER`.

## What it does
- The bar has an All button, selected by default, and four additive chips: Parked, Blocked, In progress and Queued. Selected chips show the union of their statuses. The In progress chip also covers `claimed` and `review`, which All shows and no chip named; Rick ruled they count as In progress. Held `not_approved` rows are not in the table, because the board query never returns them.
- `activeChips( selected )` returns the chips that really filter, in table order. Unknown keys are ignored. An empty list means All: nothing selected, or every chip selected.
- `toggleChip( selected, key )` returns a new array after a click. A selected chip is removed and an unselected one added. Selecting the last unselected chip, or clearing the last selected one, gives `[]` (All), never an empty view. An unknown key leaves the selection as it was.
- `filterTasksByChips( tasks, selected )` returns every row for All, otherwise the rows whose status belongs to a selected chip, in order.
- `publishOnWindow( win )` puts the table and the three functions on `win.LUPIN_TASK_STATUS_FILTER`. The module calls it on `globalThis` when it loads. If the global is missing, `notifications.js` shows all rows and draws no chips.

## Don't
- Don't name a status anywhere else. Change the table.
