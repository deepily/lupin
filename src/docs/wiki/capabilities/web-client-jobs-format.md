---
capability: web-client-jobs-format
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.formatWhen@ef6b79b0f6
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.formatCount@51c572cbe9
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.trendArrow@0909cb7091
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.attemptTime@4777664e07
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.defaultCompare@14965513b5
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.nextSort@24a42c7258
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.sortJobs@8367d37386
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.headerLine@f355279ed1
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.badgeText@39447abf00
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.lastRunText@a7c9f3c90b
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.lastFinishedText@cadb0c83f2
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.scanText@061839f550
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.freshnessText@46d3834855
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.fixText@1b537b9f3d
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.clearsText@01853fb7c2
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.notReportedNames@3326ea6e31
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.graceText@5723508a9d
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.notifyIntervalText@677d9d4b85
  - src.lupin_app.static.js.multiplexer.jobs.jobsFormat.isSafeHref@c15de278e8
---
# Web client: jobs text rules

The pure text rules behind the Background Jobs pane. The DOM that uses them is [[web-client-jobs-render]]; the pane itself is [[web-client-jobs-pane]].

## What it does
- None of these functions touches the page or the clock. Times are read off the ISO text, so a page in another time zone shows the same wall time as the log.
- `formatWhen` shows HH:MM for today and MM-DD HH:MM for any other day. A null gives "not reported"; text that is not a time comes back unchanged. `formatCount` adds thousands commas and also prints "not reported" for null. `trendArrow` gives ▲ grew, ▼ shrank, = held.
- With no pick `sortJobs` uses `defaultCompare`: running first, then healthy, behind, failing, silent, never reported. A pick uses an entry of `SORT_ORDERS` (`name`, `health`, `last-run`), reversed for "desc".
- `health` runs by `HEALTH_URGENCY`: healthy, behind, silent, unknown, failing. `last-run` ascending is oldest first. `nextSort` gives the next click: ascend, descend, then default.
- `headerLine` reads like "5 jobs: 1 healthy, 3 failing" and leaves out empty states. `badgeText` joins the state with any other state a reason names.
- `lastRunText` explains the collapsed line. It shows unit up or down for a liveness job and "SILENT, due ..." for a silent one. Otherwise it shows the last attempt and its outcome. `lastFinishedText` adds the last finished time.
- `scanText`, `freshnessText`, `fixText` and `clearsText` fill the debt columns. Each is empty when that debt does not apply to the job, and says "not reported" for a null figure. `notReportedNames` lists every missing figure the panel must name. A debt that does not apply is skipped, not listed. `graceText` prefers seconds over minutes.
- `notifyIntervalText` prints "every 1 h", "every 10 min" or seconds. `isSafeHref` accepts only a path on this server.

## Don't
- Don't print a null figure as zero. Use "not reported".

