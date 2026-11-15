---
capability: multiplexer-cron-jobs-pane
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.jobs.cronFormat.cronFlipPath@5e9b58965a
  - src.lupin_app.static.js.multiplexer.jobs.cronFormat.cronStateText@07332344b6
  - src.lupin_app.static.js.multiplexer.jobs.cronFormat.cronReadsText@7ed455436b
  - src.lupin_app.static.js.multiplexer.jobs.cronFormat.cronInsideText@353dbb9fae
  - src.lupin_app.static.js.multiplexer.jobs.cronFormat.cronChangedText@a85f1e3b0b
  - src.lupin_app.static.js.multiplexer.jobs.cronFormat.refusalDetail@5a9e6a97f7
  - src.lupin_app.static.js.multiplexer.jobs.cronFormat.cronFlipFailureText@e66046b8ff
---
# Job switch text (the Scheduled Jobs pane, merged into the jobs list)

The words a job's on/off switch shows in the multiplexer's jobs list. The Scheduled Jobs pane was merged into the jobs list, so there is no pane of its own. The switch is on line 2 of the job's row ([[web-client-jobs-render]]), fetched and flipped by [[web-client-jobs-pane]]. The legacy client carries its own copy (static/js/cron-jobs.js). The two share no runtime code, by Rick's no-shared-code ruling. The server side is in [[rest-cron-job-switches]].

## The text of a switch
- `cronFlipPath` is the flip door of one job.
- `cronStateText` is the word on, off or unknown.
- `cronReadsText` says when the job reads its switch, at each run or every tick.
- `cronInsideText` notes a job that runs inside another job's tick, when that other job is off.
- `cronChangedText` is who flipped the switch and when, or `not reported`.
- `cronFlipFailureText` turns a refused flip into one sentence for the row. It uses `refusalDetail` to take the server's `detail`; the Run now refusal text in [[web-client-jobs-pane]] uses it too.

## Turning a job off
- Turning off an alarm job takes a second, confirming click, and any redraw cancels a half-finished confirmation.
- A switch the server could not read shows as a red unreadable note.
