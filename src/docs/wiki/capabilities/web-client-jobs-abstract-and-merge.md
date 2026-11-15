---
capability: web-client-jobs-abstract-and-merge
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.jobs.mergedRows.cronOnlyEntry@1b9621a08c
  - src.lupin_app.static.js.multiplexer.jobs.mergedRows.mergeJobs@0352496f4f
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.mdText@fca7e42f2b
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.mdLink@f6dd6f6b66
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.section@8070a72006
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.titleLine@4c8685c1d3
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.reasonLines@dcfb296f33
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.stripLines@6ee88d15f5
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.scanLines@5060c4e4fa
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.fixLines@a441606b23
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.scheduleLines@b7609efd2d
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.peopleLines@b702360694
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.abstractMarkdown@f46465d07a
---
# Web client: merging the two job doors, and the 📋 abstract

Two pure modules behind the one jobs list. Neither touches the DOM or the clock. The list that draws their output is [[web-client-jobs-render]]; the pane that fetches the two doors is [[web-client-jobs-pane]].

## Merging
- `mergeJobs` joins the summary's jobs with the switch rows by job id. Each job carries its switch row, or null. A switch no job names (a job with reporting switched off) gets its own entry from `cronOnlyEntry`, marked `cron_only`, state unknown, with no figures. Neither input is changed, and targets stay nested under their job.

## The abstract
- `abstractMarkdown` writes the text the expanded panel used to show, as markdown. The sections are Reasons, Last attempts, Scan debt, Fix debt, Schedule, Evidence, People and Not reported. A liveness job has no attempts or scan debt, and a debt that does not apply is left out. The 📋 on the row carries it.
- `mdText` escapes the characters markdown would act on, so writer text reads as written. `mdLink` draws a link only for a path on this server; any other address is plain escaped text.
- `titleLine`, `section`, `reasonLines`, `stripLines`, `scanLines`, `fixLines`, `scheduleLines` and `peopleLines` build the parts. A missing figure says `not reported`, never zero.

## Don't
- Don't share this code with the legacy client's copy (static/js/background-jobs.js). The two are kept separate; a unit test compares what each writes for every fixture job.
