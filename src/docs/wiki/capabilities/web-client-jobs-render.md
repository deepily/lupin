---
capability: web-client-jobs-render
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.el@b8269a10a4
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.link@3ea4a2dcb1
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.sparkline@c3147ff401
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.addRow@b96bd7ad72
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.block@4c3525bfd4
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.reasonsBlock@10bc72da0d
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.stripBlock@55f74b3b70
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.scanBlock@72cb5560db
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.fixBlock@bb8780d322
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.scheduleBlock@f3a385797d
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.evidenceBlock@fe909d3e62
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.peopleBlock@e165e554b7
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.notReportedBlock@0c64a8d338
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.runNowBlock@3c0553f301
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.itemId@e66f8d44b3
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.renderJob@416c3c130d
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.renderAccordion@ddc4e1b574
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.arrow@cd1868139e
  - src.lupin_app.static.js.multiplexer.jobs.jobsRender.headerRow@4a4e543a3f
---
# Web client: jobs accordion DOM

Builds the accordion of jobs from a summary. The wording comes from [[web-client-jobs-format]]; the pane that calls it is [[web-client-jobs-pane]].

## What it does
- All text goes in as text content, never as HTML. A link is drawn only when `isSafeHref` accepts the address.
- `el`, `link`, `addRow` and `block` are small builders for an element, an anchor, a label and value pair, and a titled section. Each carries a test id.
- `renderJob` draws one job as a button line plus a hidden panel. The button starts collapsed, tracks `aria-expanded` and flips its caret on click. The line holds state dot, title, badge, last run, last finished and the scan, fix and clears columns.
- The panel holds blocks in this order: reasons, last attempts (not for a liveness job), scan debt and fix debt. Then come schedule, evidence, people, not reported and Run now. Targets of the job follow as nested items, sorted.
- `reasonsBlock` lists every reason, the unknown reason, and a note when the machine was off. With none it says no rule is true.
- `stripBlock` lists recent attempts and marks a missed one. `scanBlock` and `fixBlock` return nothing when the debt does not apply, and show sparklines and a task store link.
- `scheduleBlock` shows liveness, the unverified warning, runs, last and next due, grace and how often Rick is told. `evidenceBlock` and `peopleBlock` link files, rows and the detail page.
- `sparkline` draws a small SVG trend line. Fewer than two points draws nothing, and a flat series draws a level line.
- `runNowBlock` appears only for the operator and a runnable job. A click disables the button, shows "Starting...", then the message or the failure, and re-enables it.
- `itemId` makes a safe element id from the job and target.
- `renderAccordion` clears the mount and draws a header row (`headerRow`) and then one item per job. A job with two targets stays two items. The header names the nine columns. Service, Status and Last run are sort buttons. The pick is kept per mount, so a poll redraws in the chosen order. Rows are ordinary weight, and only the header is bold. It ends with the server's "switched off" line when there is one.
