---
capability: web-client-jobs-pane
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.BackgroundJobsRendererImpl@8b596ba627
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.createBackgroundJobsRenderer@5fb9926bb5
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.runNowPath@911df302b4
  - src.lupin_app.static.js.multiplexer.render.BackgroundJobsRenderer.runNowFailureText@fea4d99968
  - src.lupin_app.static.js.shared.approve-link.publishOnWindow@0042bf3332
---
# Web client: Background Jobs pane

The collapsible section in the multiplexer that shows the jobs accordion, and the bridge that exposes approve links to old scripts. Related: [[web-client-jobs-render]], [[web-client-jobs-format]], [[web-client-transport-and-auth]], [[task-approve-link]].

## What it does
- `createBackgroundJobsRenderer` returns the pane. It paints nothing until `mount` is called on a root element.
- `mount` throws if the pane is already mounted. It draws a header with the 🔁 icon, a count and a refresh button, then an error line and the accordion. It starts a 60 second poll and asks at once.
- `refresh` fetches `/api/jobs/summary`, redraws, sets the count, hides the error and puts the headline on the header title. It never rejects: a failure shows "Could not load the jobs" with the status.
- A refresh that returns after `unmount` is dropped.
- `unmount` stops the poll, removes the collapse listener and clears the root. Calling it twice is safe.
- The pane works out no health itself. The server's summary decides the states, and the operator flag decides whether Run now shows.
- `runNowPath` is `/api/jobs/<job>/run`, with `?target=` for a target. The Run now action posts there and reports the start time and process id.
- `runNowFailureText` turns 403, 404, 409 and 422 into plain sentences and shows the status for anything else.
- `publishOnWindow` copies the approve-link helpers onto `LUPIN_APPROVE_LINK` on a window, because the notification script is a classic script that cannot import. It runs once at load on the global object.

## Don't
- Don't share code with the legacy page's own jobs copy. The two are kept separate.
