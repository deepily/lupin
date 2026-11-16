---
capability: web-client-jobs-abstract-and-merge
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.jobs.mergedRows.cronOnlyEntry@11fd7447bc
  - src.lupin_app.static.js.multiplexer.jobs.mergedRows.mergeJobs@0352496f4f
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.mdText@fca7e42f2b
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.mdLink@f6dd6f6b66
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.section@5960e8a996
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.titleLine@b6b352d703
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.reasonLines@dcfb296f33
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.stripLines@6ee88d15f5
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.scanLines@d493cfa82b
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.fixLines@1c515605a3
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.scheduleLines@b7609efd2d
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.peopleLines@b702360694
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.abstractMarkdown@24d5bcaf49
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.descriptionBlock@742c05fe69
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.jobSections@c460f15540
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.nameOf@c1f3e6d0b6
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.switchLines@23765cdf3e
  - src.lupin_app.static.js.multiplexer.jobs.abstractText.trendLine@d92978d010
---
# Web client: merging the two job doors, and the 📋 abstract

Two pure modules behind the one jobs list. Neither touches the DOM or the clock. The list that draws their output is [[web-client-jobs-render]]; the pane that fetches the two doors is [[web-client-jobs-pane]].

## Merging
- `mergeJobs` joins the summary's jobs with the switch rows by job id. Each job carries its switch row, or null. A switch no job names (a job with reporting switched off) gets its own entry from `cronOnlyEntry`, marked `cron_only`, state unknown, with no figures. Neither input is changed, and targets stay nested under their job.

## The abstract
- `abstractMarkdown` writes the text the expanded panel used to show, as markdown. The sections are Reasons, Last attempts, Scan debt, Fix debt, Schedule, Switch, Evidence, People and Not reported. A liveness job has no attempts or scan debt, and a debt that does not apply is left out. The 📋 on the row carries it. `descriptionBlock` draws a short plain-English paragraph on what the service does, right after the title. It takes the job's own `description`, else its switch row's, and draws nothing when both are empty. `cronOnlyEntry` copies the switch row's description onto its entry, so a switch-only job gets one too.
- Switch is what the old Scheduled Jobs row showed. It lists the state, the cron schedule, the last flip and how the job reads its switch. A Check line names drift, an unreadable switch or an off host job. Switch appears only for a job that has one. It takes the switch list as a third argument, so the host check can find the host.
- The old sparklines come back as text: `Trend (scan debt)` and `Trend (rows opened)`, from two points up. The arrows on Count and Unfiled stay.
- Each target of a job follows as a `## Target:` block with the same sections one level down. That is the per-service report the old nested panels gave. A switch-only job (`cron_only`) gets its title, its Switch and one line saying reporting is switched off, with none of the empty sections.
- `mdText` escapes the characters markdown would act on, so writer text reads as written. `mdLink` draws a link only for a path on this server; any other address is plain escaped text.
- `titleLine`, `section`, `reasonLines`, `stripLines`, `scanLines`, `fixLines`, `scheduleLines` and `peopleLines` build the parts. A missing figure says `not reported`, never zero.

## Don't
- Don't share this code with the legacy client's copy (static/js/background-jobs.js). The two are kept separate; a unit test compares what each writes for every fixture job.
