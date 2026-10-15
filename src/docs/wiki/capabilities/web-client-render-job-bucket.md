---
capability: web-client-render-job-bucket
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.jobBucket.renderJobBucket@7d7f4594a1
  - src.lupin_app.static.js.multiplexer.render.templates.jobBucket.toggleBucket@f8c071c2b7
---
# Jobs bucket and job card templates

`renderJobBucket` draws one of the five jobs buckets as a `<section>`, and `toggleBucket` flips it open or closed.

## What it does
- `renderJobBucket( bucketName, jobs, opts )` returns a `section.jobs-bucket` for `todo`, `running`, `done`, `dead` or `history`.
- The header is a `role="button"` with a glyph, label, count, a delete-all button and a toggle. `aria-expanded` and `aria-controls` track the cards container.
- A bucket starts expanded unless `opts.expanded` says otherwise. The default is open for `todo` and `running`, closed for the other three.
- The `history` bucket adds a time-window select, defaulting to all time, and shows `historyTotalCount` as its count when given. A Load more button appears when loaded is below total.
- An empty bucket shows "No job history found" for history and "No jobs in queue" for the others.
- Otherwise the cards are built by `keyedListMerge`, each by `renderJobCard`. Cards in `dead` and `history` get a retry button.
- `renderJobCard( job, opts )` returns a `.job-card` with `data-id-hash`, `data-job-type` and `status-<status>` set. The header has a status icon, type, `#` plus the first 8 characters of the id, a timing text and a delete button.
- Its details area starts `collapsed` and holds an empty hidden `pre.job-meta-json`.
- `toggleBucket( root )` flips `aria-expanded`, the ▼ and ▶ glyph and the cards `collapsed` class, and returns the new state.

## How the parts work together
The header click and the Enter or Space key both call `toggleBucket`, then report the new state through `opts.onToggle`. The template keeps no state, so the pane stores the choice and passes it back as `opts.expanded` on the next paint. A click on a button or select inside the header does not toggle.
