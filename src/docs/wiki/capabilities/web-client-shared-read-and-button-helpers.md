---
capability: web-client-shared-read-and-button-helpers
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.shared.afterWriteRead.stampFreshRead@fab2827831
  - src.lupin_app.static.js.multiplexer.stores.polling.createSingleFlightRead@da0b9a0b05
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.restArmedButton@9e38f718df
---
# Web client: fresh-read stamp, single-flight read and armed button

Three small helpers that several panes share.

## What it does
- `stampFreshRead( el, text )` writes a pane's `updated` label after a fresh read and ends any read-back-failed marking. A null element is a no-op, because the pane is unmounted.
- The holding area, epic board, task list, fleet status pane and finished tasks pane all use it.
- `createSingleFlightRead( read, joinInFlight )` wraps a store's read so only one runs at a time. It returns `refresh` and `refreshAfterWrite`.
- With a read in flight, `refresh` returns that read when `joinInFlight` is true, and returns at once when it is false.
- `refreshAfterWrite` waits out the read in flight, then joins any read that began meanwhile. That read began after the write, so skipping it would resolve too early.
- `restArmedButton( button, label )` puts an armed button back to rest: no armed mark, no armed class and the given label. The batch buttons, plan buttons and per-row Submit share it.

## Don't
- Don't clear the in-flight read by hand. The wrapper clears it by identity, so a read that rejects early cannot leave a rejection parked.
