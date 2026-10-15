---
capability: web-client-stores-transcripts-and-history
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptRoster.parseSenderId@8bf7e6db55
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptRoster.resolveTranscriptSeat@dd4fb987d3
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptRoster.rowsOf@a1337af3a2
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptRoster.SessionTranscriptRosterImpl@1773b32823
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptRoster.createSessionTranscriptRoster@72f103d076
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptStore.transcriptBlockBytes@37437380c9
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptStore.isFrame@4b606c9c95
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptStore.blocksOf@2c1e6eeacc
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptStore.SessionTranscriptStoreImpl@a00bb61ebb
  - src.lupin_app.static.js.multiplexer.stores.SessionTranscriptStore.createSessionTranscriptStore@8000b12bf8
  - src.lupin_app.static.js.multiplexer.stores.StripReconnectRehydrator.StripReconnectRehydratorImpl@7d7004203c
  - src.lupin_app.static.js.multiplexer.stores.StripReconnectRehydrator.createStripReconnectRehydrator@b55d2e2967
  - src.lupin_app.static.js.multiplexer.stores.awaitingResponseHydration.createAwaitingResponseHydration@bf440596f4
  - src.lupin_app.static.js.multiplexer.stores.coldHistoryHydration.ColdHistoryHydrationImpl@2527d10a19
  - src.lupin_app.static.js.multiplexer.stores.historyWindow.sendersVisiblePath@ad58294ebe
  - src.lupin_app.static.js.multiplexer.stores.historyWindow.parseStoredHistoryWindow@aba2246f20
  - src.lupin_app.static.js.multiplexer.stores.historyWindow.serializeHistoryWindow@eff6dc4991
  - src.lupin_app.static.js.multiplexer.stores.historyWindow.effectiveHoursForQuery@9998acc523
  - src.lupin_app.static.js.multiplexer.stores.historyWindow.historyWindowLabel@7642ceb71f
  - src.lupin_app.static.js.multiplexer.stores.responseQuestions.parseResponseQuestions@861f3de8ed
  - src.lupin_app.static.js.multiplexer.stores.responseQuestions.toOption@29eaea2bea
  - src.lupin_app.static.js.multiplexer.stores.responseQuestions.isRecord@f2d88db5fc
---
# Web client stores: transcripts and history

The session transcript store and roster, the page-load history helpers and the response question parser. [[web-client-stores]] covers how they are built. `StripReconnectRehydrator.ts` imports `historyWindow.ts`. `coldHistoryHydration.ts` imports `historyWindow.ts`.

## What it does
- `SessionTranscriptRoster.ts`. `parseSenderId`: Split a chip's `sender_id` into its project and its 8-hex id prefix. `resolveTranscriptSeat`: Resolve a chip to exactly one watchable roster row's full id. `rowsOf`: Returns the entries of a value that look like roster rows. `SessionTranscriptRosterImpl`: Models the seats whose transcripts can be watched, for admin users. `createSessionTranscriptRoster`: Build the roster.
- `SessionTranscriptStore.ts`. `transcriptBlockBytes`: A block's size for the ring budget: the UTF-8 byte length of its text. `isFrame`: Tells whether a value is a plain object, not null and not an array. `blocksOf`: Returns the object entries of a value as transcript blocks, or an empty list. `SessionTranscriptStoreImpl`: Keeps the transcript of one watched Claude Code session in a size-capped ring of segments. `createSessionTranscriptStore`: Build the store.
- `StripReconnectRehydrator.ts`. `StripReconnectRehydratorImpl`: Reloads the strip's data after the queue socket reconnects. `createStripReconnectRehydrator`: Build the rehydrator.
- `awaitingResponseHydration.ts`. `createAwaitingResponseHydration`: Build the runner.
- `coldHistoryHydration.ts`. `ColdHistoryHydrationImpl`: Loads senders and history on page open, and again on retry or change.
- `historyWindow.ts`. `sendersVisiblePath`: The senders-visible path for a user, with an hours window. `parseStoredHistoryWindow`: Parse the legacy client's stored window value. `serializeHistoryWindow`: Serialize a window for HISTORY_WINDOW_KEY. `effectiveHoursForQuery`: The hours to send on a query. `historyWindowLabel`: The picker's display label.
- `responseQuestions.ts`. `parseResponseQuestions`: Read the questions out of a notification's `response_options`. `toOption`: Converts one raw option value into a list holding zero or one action-required options. `isRecord`: Tells whether a value is a plain object, excluding null and arrays.
