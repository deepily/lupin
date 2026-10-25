---
capability: web-client-notifications-script
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.chunk-sequencer.ChunkSequencer@79c213d642
  - src.lupin_app.static.js.chunk-sequencer.runComparisonTest@8debe294c2
  - src.lupin_app.static.js.chunk-sequencer.testOriginalMethod@2bc4eab913
  - src.lupin_app.static.js.chunk-sequencer.testSequencedMethod@7b68996755
  - src.lupin_app.static.js.chunk-sequencer.stopAllTests@9cfd017a99
  - src.lupin_app.static.js.chunk-sequencer.clearLogs@11032d147e
  - src.lupin_app.static.js.chunk-sequencer.getCurrentSettings@6e33e0d114
  - src.lupin_app.static.js.notifications.ccConsoleResetStream@1dc22525db
  - src.lupin_app.static.js.notifications.ccConsoleBlockBytes@df0fa3d87d
  - src.lupin_app.static.js.notifications.ccConsoleResolveSessionId@168643882d
  - src.lupin_app.static.js.notifications.ccConsoleCanWatch@c5c3cc039c
  - src.lupin_app.static.js.notifications.ccConsoleBuildPageHref@7800981618
  - src.lupin_app.static.js.notifications.ccConsoleParseSenderId@27fe075f49
  - src.lupin_app.static.js.notifications.ccConsolePaintSenderButtons@42382e1bb8
  - src.lupin_app.static.js.notifications.ccConsolePaintSenderCard@8219885626
  - src.lupin_app.static.js.notifications.ccConsoleRenderPlanFor@239a51dadf
  - src.lupin_app.static.js.notifications.ccConsoleShouldRender@30460dc3d0
  - src.lupin_app.static.js.notifications.ccConsoleIsFrame@db318e8b12
  - src.lupin_app.static.js.notifications.ccConsoleBeginWatch@9964fe5867
  - src.lupin_app.static.js.notifications.ccConsoleEndWatch@efe6f62fe9
  - src.lupin_app.static.js.notifications.ccConsoleApplyChunk@092a363890
  - src.lupin_app.static.js.notifications.ccConsoleApplyState@e88891a26b
  - src.lupin_app.static.js.notifications.NotificationsUI@ccc24cb235
---
# Web client notifications script

The older notifications page script and the chunk sequencer it plays speech through. [[web-client-notification-panes]] describes the newer panes. No file in this group imports another; each is loaded on its own by the code that calls it.

## What it does
- `chunk-sequencer.js`. `ChunkSequencer`: Chunk Sequencing Test Laboratory - ElevenLabs Audio Order Fix. `runComparisonTest`: Runs the original and then the sequenced method on the same text. `testOriginalMethod`: Runs one test with the play-on-arrival handler using the page settings. `testSequencedMethod`: Runs a single test with the sequenced handler using the current page settings. `stopAllTests`: Stops streaming on both the original and sequenced handlers. `clearLogs`: Empties the on-page console log and leaves a short cleared and ready message. `getCurrentSettings`: Reads the test text, voice, model and quality profile from the page controls.
- The `NotificationsUI` holding area has the same Creator / Assignee toggle, kept under the key `lupin.holdingArea.groupBy`.
- `notifications.js`. `ccConsoleResetStream`: Reset everything scoped to one epoch's byte stream, keeping the watched seat. `ccConsoleBlockBytes`: A block's size for the ring budget: the UTF-8 byte length of its text. `ccConsoleResolveSessionId`: Resolve a sender card's 8-hex session id to the full `cc_session_id` to watch. `ccConsoleCanWatch`: Whether a sender card should offer a "open console" affordance at all. `ccConsoleBuildPageHref`: The standalone console page's URL for one seat — the legacy twin of the multiplexer's `buildConsolePageHref`. `ccConsoleParseSenderId`: Split a sender id into its project and its hex id prefix, the way the multiplexer does. `ccConsolePaintSenderButtons`: Paint, move or remove the console button on every sender card in `container`. `ccConsolePaintSenderCard`: Paint one card's console button. See ccConsolePaintSenderButtons for the contract. `ccConsoleRenderPlanFor`: Decide how one block renders: which path, and whether it starts folded. `ccConsoleShouldRender`: Whether a block should be rendered at all. `ccConsoleIsFrame`: Whether a value is a plain frame object. `ccConsoleBeginWatch`: The envelopes to send when the console moves to a seat. `ccConsoleEndWatch`: Close the console: unwatch whatever is watched and clear everything. `ccConsoleApplyChunk`: Apply one `cc_transcript_append` frame. `ccConsoleApplyState`: Apply one `cc_transcript_state` frame. `NotificationsUI`: Models the notifications page: auth, WebSocket channels, TTS, and job cards.
