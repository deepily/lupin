---
capability: web-client-jobs-pane
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.BackgroundJobsRendererImpl@7a0338432f
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.createBackgroundJobsRenderer@5fb9926bb5
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.runNowPath@911df302b4
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.runNowFailureText@52db6c247f
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.failureText@ea519b8072
  - src.lupin_app.static.js.shared.approve-link.publishOnWindow@0042bf3332
---
# Web client: Background Jobs pane

The collapsible section in the multiplexer that shows the one jobs list. The Scheduled Jobs pane was merged into it. This page also covers the bridge that exposes approve links to old scripts. Related: [[web-client-jobs-render]], [[web-client-jobs-format]], [[web-client-transport-and-auth]], [[task-approve-link]].

## What it does
- `createBackgroundJobsRenderer` returns the pane. It paints nothing until `mount` is called on a root element.
- `mount` throws if the pane is already mounted. It draws a header with the 🔁 icon, a count and a refresh button, then an error line and the accordion. It starts a 60 second poll and asks at once.
- `refresh` fetches `/api/jobs/summary` and `/api/cron-jobs` together and joins them (`mergeJobs`). It redraws, sets the count with how many switches are off, and puts the headline on the header title. It never rejects.
- Before the summary has loaded once, every switch is drawn as a row of its own, marked "not reporting", so no switch disappears. If neither door has answered, only the banner shows.
- A failed door shows "Could not load the jobs" or "Could not load the scheduled jobs", with the reason from `failureText`. The last good answer of each door stays on screen.
- A `cron_job_switch_changed` frame on the event bus swaps one switch row and redraws. `requestFlip` sends the flip, and an alarm job's turn-off waits for a second click. A redraw drops a half-finished confirmation and keeps open rows open.
- A refresh that returns after `unmount` is dropped.
- `unmount` stops the poll, then calls `teardownScaffold` ([[web-client-render-dom-and-doc-links]]) to remove the collapse listener and clear the root. Calling it twice is safe.
- The pane works out no health itself. The server's summary decides the states, and the operator flag decides whether Run now shows.
- `runNowPath` is `/api/jobs/<job>/run`, with `?target=` for a target. The Run now action posts there and reports the start time and process id.
- `runNowFailureText` turns 403, 404, 409 and 422 into plain sentences and shows the status for anything else.
- `publishOnWindow` copies the approve-link helpers onto `LUPIN_APPROVE_LINK` on a window, because the notification script is a classic script that cannot import. It runs once at load on the global object.

## Don't
- Don't share code with the legacy page's own jobs copy. The two are kept separate.
