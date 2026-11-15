---
capability: multiplexer-cron-jobs-pane
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.cronFlipPath@5e9b58965a
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.cronStateText@07332344b6
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.cronReadsText@7ed455436b
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.cronInsideText@353dbb9fae
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.cronChangedText@a85f1e3b0b
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.refusalDetail@3bcfce3888
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.cronFlipFailureText@e66046b8ff
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.CronJobsRendererImpl@ac414551e6
  - src.lupin_app.static.js.multiplexer.render.CronJobsRenderer.createCronJobsRenderer@372dd0e4f2
---
# Scheduled Jobs pane

The multiplexer section that shows each cron job's on/off switch and lets an administrator flip it. It is the multiplexer's copy of the legacy client's Scheduled Jobs section. The two share no runtime code, by Rick's no-shared-code ruling. The server side is in [[rest-cron-job-switches]].

## The pane
- `createCronJobsRenderer` builds the pane and paints nothing until `mount` is called. `CronJobsRendererImpl` is the pane. It polls the list door every 60 seconds and repaints a row when the `cron_job_switch_changed` frame arrives.
- `unmount` stops the polling and drops the listeners. `refresh` asks the list door again and never rejects.

## The text of a row
- `cronFlipPath` is the flip door of one job.
- `cronStateText` is the word on, off or unknown.
- `cronReadsText` says when the job reads its switch, at each run or every tick.
- `cronInsideText` notes a job that runs inside another job's tick, when that other job is off.
- `cronChangedText` is who flipped the switch and when, or `not reported`.
- `cronFlipFailureText` turns a refused flip into one sentence for the row. It uses `refusalDetail` to take the server's `detail`.

## Turning a job off
- Turning off an alarm job takes a second, confirming click, and any redraw cancels a half-finished confirmation.
- A switch the server could not read shows as a red unreadable row.
