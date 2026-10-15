---
capability: web-client-render-job-meta
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard.configureMetaDisplayCap@d714ac2df6
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard._getMaxMetaBytesForTesting@9f43a917b7
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard.estimateSize@19619fe59c
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard.formatBytes@fc959aff1d
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard._formatBytesForTesting@703017b21a
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard.safeStringifyMeta@95e03c2d55
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard.populateJobMetaIfNeeded@da7d04b2ba
  - src.lupin_app.static.js.multiplexer.render.templates.jobCard.renderJobCard@485624a384
---
# Job meta display cap

These functions keep a job's meta JSON from freezing the page. `populateJobMetaIfNeeded` fills a card's meta block on first expand, behind a size cap.

## What it does
- `configureMetaDisplayCap( serverConfig )` sets the cap from `multiplexer_max_meta_display_bytes`. It applies only a finite number above zero, rounded down. The default is 256,000.
- `_getMaxMetaBytesForTesting` returns the current cap. Production code does not call it.
- `estimateSize( meta, cap )` walks the object once and adds an approximate size per node. It stops as soon as the total passes the cap.
- It counts a string as its length plus 2, a number or boolean as 8, `null` as 4, and a repeated object as 4.
- `formatBytes( n )` returns `NB` under 1024, `x.xKB` under one megabyte, and `x.xMB` above. `_formatBytesForTesting` calls it directly.
- `safeStringifyMeta( meta )` never throws. Over the estimate it returns "[meta too large to display — size]".
- Otherwise it pretty-prints with 2 spaces. A result over the cap gives "[meta too large to display]", a failure gives "[meta serialization failed: message]", and `undefined` gives `{}`.
- `populateJobMetaIfNeeded( card, meta )` fills the card's `.job-meta-json` on the first call, removes `hidden`, and remembers that element.

## How the parts work together
The pane's card-header click handler calls `populateJobMetaIfNeeded`. It runs `safeStringifyMeta`, which checks `estimateSize` first and so avoids a large `JSON.stringify`. Boot calls `configureMetaDisplayCap` once with the server config it fetches at startup.

## Don't
- Don't expect the meta block to refresh. After the first expand the element is cached, and later calls do nothing.
- Don't read the size in the too-large message as the payload's true size. The walk stops once it passes the cap.
