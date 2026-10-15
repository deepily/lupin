---
capability: web-client-shared-services
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.shared.EventBus.EventBusImpl@5f463260ea
  - src.lupin_app.static.js.multiplexer.shared.EventBus.createEventBusForTesting@e28a0a5730
  - src.lupin_app.static.js.multiplexer.shared.StorageService.StorageServiceImpl@abb46ba6a9
  - src.lupin_app.static.js.multiplexer.shared.StorageService.isEnvelope@bce591d7c0
  - src.lupin_app.static.js.multiplexer.shared.StorageService.createStorageServiceForTesting@97955c4da0
  - src.lupin_app.static.js.multiplexer.shared.StorageService.InMemoryStorage@08307b51f3
  - src.lupin_app.static.js.multiplexer.shared.afterWriteRead.readBackAfterWrite@3f4ec565a9
  - src.lupin_app.static.js.multiplexer.shared.afterWriteRead.stampReadBackFailed@93cee54d18
  - src.lupin_app.static.js.multiplexer.shared.afterWriteRead.clearReadBackFailed@d13ae28533
  - src.lupin_app.static.js.multiplexer.shared.broadcast.BroadcastWrapperImpl@e340e04fcc
  - src.lupin_app.static.js.multiplexer.shared.broadcast.isLupinEvent@8672e99c0f
  - src.lupin_app.static.js.multiplexer.shared.broadcast.defaultChannelFactory@ae9d310c1f
  - src.lupin_app.static.js.multiplexer.shared.broadcast.createBroadcastWrapper@8b9eb7d729
  - src.lupin_app.static.js.multiplexer.shared.debugSink.setDebugPanel@63489a1901
  - src.lupin_app.static.js.multiplexer.shared.debugSink.currentDebugPanel@7d26556cc7
  - src.lupin_app.static.js.multiplexer.shared.debugSink.toPanel@f7055a683c
  - src.lupin_app.static.js.multiplexer.shared.debugSink.log@817ca497fd
  - src.lupin_app.static.js.multiplexer.shared.debugSink.error@0c1a9beed7
  - src.lupin_app.static.js.multiplexer.shared.debugSink.wsDiag@77f64d31f3
  - src.lupin_app.static.js.multiplexer.shared.ownLookup.ownLookup@f6c9133efb
  - src.lupin_app.static.js.multiplexer.shared.personaLabel.personaLabel@dacc497542
  - src.lupin_app.static.js.multiplexer.shared.ttsPreview.truncateAtBoundary@0652519fe1
---
# Web client shared services

The small services every multiplexer module shares: the event bus, storage, the debug sink and a few helpers. [[web-client-stores]] and [[web-client-transport-and-auth]] build on them.

## What it does
- `EventBus.ts`. `EventBusImpl`: Delivers typed events to listeners through a DOM event target. `createEventBusForTesting`: Build a separate bus for a test, so no listeners leak between test cases.
- `StorageService.ts`. `StorageServiceImpl`: Reads and writes versioned JSON envelopes in a storage backend under a key prefix. `isEnvelope`: Tells whether a parsed value has the envelope shape of version, payload and time. `createStorageServiceForTesting`: Build a storage service for a test. `InMemoryStorage`: A storage backend that holds keys in a map and forgets them with the page, for tests.
- `afterWriteRead.ts`. `readBackAfterWrite`: Run a post-write read whose failure can never be mistaken for a failed write. `stampReadBackFailed`: Paint `READ_BACK_FAILED_STAMP` into a pane's updated-stamp element. `clearReadBackFailed`: Drop the read-back-failed marking, for a pane that has just re-read successfully.
- `broadcast.ts`. `BroadcastWrapperImpl`: Copies whitelisted bus events to other tabs and replays incoming ones locally. `isLupinEvent`: Says whether a value has the shape of a bus event. `defaultChannelFactory`: Creates a browser broadcast channel with the given name. `createBroadcastWrapper`: Build the cross-tab wrapper over a bus.
- `debugSink.ts`. `setDebugPanel`: Register (or clear) the panel that receives lines. `currentDebugPanel`: The sink currently registered — for a test to assert wiring without a panel. `toPanel`: Sends a message to the registered debug panel with its type. `log`: An ordinary diagnostic line. `error`: An error line. `wsDiag`: A WebSocket diagnostic.
- `ownLookup.ts`. `ownLookup`: Read `key` from `table`, answering only for keys the table owns.
- `personaLabel.ts`. `personaLabel`: The display name inside a stored `<persona> <8-hex session>` value.
- `ttsPreview.ts`. `truncateAtBoundary`: Truncate `text` to roughly `fraction` of its length, extending forward to the next.
