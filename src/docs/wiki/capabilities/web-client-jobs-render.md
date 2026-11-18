---
capability: web-client-jobs-render
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.el@b8269a10a4
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.runNowBlock@3c0553f301
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.itemId@e66f8d44b3
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.abstractIndicator@70e25c608a
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.switchCells@c92d6c920c
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.lineTwo@21ea9c9387
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.targetLine@d37c501af9
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.lineThree@723a69985f
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.renderJob@43957ed8e6
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.arrow@cd1868139e
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.headerRow@4a4e543a3f
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.renderAccordion@0d959d4ea1
---
# Web client: jobs list DOM

Builds the one jobs list from a merged summary. The wording comes from [[web-client-jobs-format]], the switch wording from [[multiplexer-cron-jobs-pane]], the abstract from [[web-client-jobs-abstract-and-merge]]; the pane that calls it is [[web-client-jobs-pane]].

## What it does
- All text goes in as text content, never as HTML. `el` is the small builder for an element with a class, text and test id.
- `renderJob` draws one job as a line plus a hidden panel. The line holds the state dot, title, badge, last run, last finished and the 📋. The ⋯ button is the last cell, on the right. It holds no Scan, Fix or Clears. The ⋯ button starts closed and tracks `aria-expanded`. Which rows are open is kept in `actions.open`, so a redraw keeps an open row open.
- `abstractIndicator` makes the 📋: an `abstract-indicator` span whose raw `data-abstract` is the job's markdown abstract. It calls the shared builder in `actionRequiredChrome.ts` with the `jobs-abstract` class, a title and a test id. The multiplexer's existing click handlers open it, in the Reading Pane or the tooltip by layout.
- The panel holds two lines. `lineTwo` has the Scan, Fix and Clears figures that apply, then the job's switch from `switchCells`. `lineThree` has Run now and the job's targets.
- `switchCells` draws the schedule, the on or off word, who changed it and when, and whether the job reads it. It adds the drift, unreadable and off-while-the-host-is-off notes. It ends with the flip button and its error span. A click on the button goes to `actions.requestFlip`.
- `targetLine` is one target as a compact line with its own status, last run and 📋.
- `runNowBlock` appears only for the operator and a runnable job. A click disables the button, shows "Starting...", then the message or the failure, and re-enables it.
- `itemId` makes a safe element id from the job and target.
- `renderAccordion` clears the mount and draws the switch note, a header row (`headerRow`) and then one item per job. The header names the seven columns. Service, Status and Last run are sort buttons (`arrow` marks the direction). The pick is kept per mount, so a poll redraws in the chosen order. It ends with the server's "switched off" line when there is one.
