---
capability: web-client-render-finished-tasks
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.clampWindowDays@fc77028985
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.windowSinceIso@8dc30f271a
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.parseShownStatuses@103c866ade
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.relativeAge@480feb361c
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.actorPersona@545b5733fc
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.transitionTarget@b5f9dc2440
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.mergeShownEvents@2f6729b333
  - src.lupin_app.static.js.multiplexer.render.finishedTasksModel.finishedPaneState@4268bd7822
  - src.lupin_app.static.js.multiplexer.render.templates.finishedTasksTable.pillIdFor@dbc81bbb2c
  - src.lupin_app.static.js.multiplexer.render.templates.finishedTasksTable.statusFace@6ef9668fda
  - src.lupin_app.static.js.multiplexer.render.templates.finishedTasksTable.statusGlyph@7ba56bf160
  - src.lupin_app.static.js.multiplexer.render.templates.finishedTasksTable.renderFinishedControls@41ab4a0efd
  - src.lupin_app.static.js.multiplexer.render.templates.finishedTasksTable.renderFinishedTasksTable@12924b70a9
  - src.lupin_app.static.js.multiplexer.render.templates.finishedTasksTable.renderFinishedSentinel@3ec6c9f9a8
---
# Multiplexer finished-tasks render

The model helpers and the DOM builders of the finished-tasks pane: three status pills, a window slider and a four-column table of terminal events.

## Model (`finishedTasksModel`)
- `clampWindowDays( value )` returns an integer inside the declared day range. A non-finite value gives the default, never 0. `windowSinceIso( days, nowMs )` turns the clamped days into the API's ISO `since` instant.
- `parseShownStatuses( raw )` reads the persisted lit statuses. A missing, corrupt or empty result gives the default, which is done only. Unknown statuses are dropped and the order follows `FINISHED_STATUSES`.
- `relativeAge( iso, nowMs )` gives `14m`, `1h12m`, `19h` or `3d`. An absent or unparseable time gives the em dash, and a future time clamps to `0m`.
- `actorPersona( actor )` is the persona alone, with an em dash when absent. `transitionTarget( transition )` is the right side of `queued->done`, or an empty string for a missing or malformed value.
- `mergeShownEvents( eventsByStatus, shown )` merges only the lit statuses into one list, newest first with the event id as tiebreak. It never mutates its input.
- `finishedPaneState( opts )` picks one of six states in order: nothing measured, no pill lit, no visible rows, then whether a status failed. A total failure is never shown as zero.

## DOM (`finishedTasksTable`)
- `pillIdFor( status )` gives `finished-pill-` plus the status with `_` as `-`. `statusFace` and `statusGlyph` read a status's icon and label from `PILL_FACES` by own key only. The glyph is an `aria-hidden` prefix in the when cell.
- `renderFinishedControls( opts )` builds one pill per status in order, with `aria-pressed` meaning shown, and the slider. Every count starts as the em dash. `FinishedTasksRenderer` adds `finished-pill-zero` to a pill measured at zero, so it is dimmed and stays shown.
- `renderFinishedTasksTable( rows, nowMs )` renders the when, what, who and why columns, with `data-status` and a `task-status-` class on each row.
- `renderFinishedSentinel( variant, text )` is a one-line notice whose test id ends in the variant.
