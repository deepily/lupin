---
capability: web-client-render-task-list-formatters
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.taskListModel.formatTaskBlockedBy@d51ef3cb0a
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskStatusClass@35350efe92
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskPriorityClass@662a785067
  - src.lupin_app.static.js.multiplexer.render.taskListModel.formatChaseTime@82b9cca988
  - src.lupin_app.static.js.multiplexer.render.taskListModel.deriveTaskActor@a9ec73cc0b
  - src.lupin_app.static.js.multiplexer.render.taskListModel.activeReassignTargets@fd05f0ed1a
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskIsParked@39b3654792
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskClassSlug@5aebda4b68
  - src.lupin_app.static.js.multiplexer.render.taskListModel.formatTaskListCount@a103197a3a
  - src.lupin_app.static.js.multiplexer.render.taskListModel.taskListCountText@d088d4e255
---
# Web client: task list formatters

The pure formatters behind a task row and the task list header: classes, chase time, parked state and counts.

Ranking, labels and grouping are in [[web-client-render-task-list-model]].

## What it does
- `formatTaskBlockedBy` turns a typed-ref array into "kind:id" items, or the bare id when kind is absent, joined by ", ". A string or null passes through unchanged.
- `taskStatusClass` maps the trimmed, lower-cased status to a class. Blocked, review, queued, done, dropped and parked get `task-status-` plus the word. Wont_fix and not_approved get `task-status-wont-fix` and `task-status-not-approved`. In_progress and claimed share `task-status-active`. Anything else is `task-status-unknown`.
- `taskPriorityClass` gives `task-prio-high` for P0 and P1, `task-prio-mid` for P2 and `task-prio-low` for P3 and up. Anything else is "".
- `formatChaseTime( iso, zone )` shows month, day, hour and minute in 24-hour form, in the IANA zone. The separators follow the browser locale. Empty or unparseable input gives "—", and an invalid zone falls back to browser-local time.
- `deriveTaskActor` returns "<email> (multiplexer)", or "anonymous (multiplexer)" for a blank email.
- `activeReassignTargets( fleet )` lists the personas of live fleet sessions, de-duplicated, blanks dropped, sorted. A missing fleet or session list gives an empty array.
- `taskIsParked( task, now )` is true only when `status` is `parked` and `next_chase_ts` parses to a time after `now`. A timestamp with no zone is read as UTC.
- `taskClassSlug` returns `item_class` (default "task") with every character outside letters, digits, `_` and `-` removed.
- `formatTaskListCount` returns "Live: L", or "Live: L · Parked: P · Total: T" when parked is above 0. `taskListCountText` counts parked rows with `taskIsParked` and calls it.

## How the parts work together
The header count and the row's parked badge share `taskIsParked`. A parked row whose chase time has passed counts as live and loses its badge together.
The count can change between polls with no row changing. `taskListCountText` expects rows already filtered to open.
