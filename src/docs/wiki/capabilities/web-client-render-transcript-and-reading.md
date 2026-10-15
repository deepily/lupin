---
capability: web-client-render-transcript-and-reading
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.SessionTranscriptRendererImpl@c1ab6e2b9c
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.describeState@22cb011086
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.renderTranscriptBlock@2741a5a5f1
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.chipLine@ed23654464
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.plain@0c5db85df1
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.unrecordedThinking@374c12e6da
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.inlineThinking@dae4212c87
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.folded@6bbcf6a191
  - src.lupin_app.static.js.multiplexer.render.SessionTranscriptRenderer.createSessionTranscriptRenderer@eb73d026b3
  - src.lupin_app.static.js.multiplexer.render.ReadingPaneRenderer.ReadingPaneRendererImpl@d5fb7fbec3
  - src.lupin_app.static.js.multiplexer.render.ReadingPaneRenderer.req@dd208cc4ab
  - src.lupin_app.static.js.multiplexer.render.ReadingPaneRenderer.reqId@f912a21288
  - src.lupin_app.static.js.multiplexer.render.QaPaneRenderer.formatMetric@d058d31430
  - src.lupin_app.static.js.multiplexer.render.QaPaneRenderer.anyMetric@64cf0d7bf8
  - src.lupin_app.static.js.multiplexer.render.QaPaneRenderer.QaPaneRendererImpl@4f7d28c4ef
  - src.lupin_app.static.js.multiplexer.render.SubmitJobsPaneRenderer.schedulingOf@5176441fd7
  - src.lupin_app.static.js.multiplexer.render.SubmitJobsPaneRenderer.SubmitJobsPaneRendererImpl@e7c1ad06b5
---
# Transcript console, reading pane, Q&A pane and submit pane renderers

These four renderers paint the reading pane, one seat's live console, the Q&A pane and the Submit Agentic Jobs pane.

- `createSessionTranscriptRenderer` builds `SessionTranscriptRendererImpl`, which paints nothing until `mount()`. It lists blocks newest at the bottom and follows the live end until the reader scrolls up.
- `SessionTranscriptRendererImpl` opens a seat with `openSeat`, which refuses when the pane refuses. `toggleSeat` closes the console when that seat shows. Pane exit or `unmount()` closes the watch.
- `describeState` returns the status line: "Catching up…" while repairing, "Session ended", or for a refused watch "Session not found" or "Watch refused". Otherwise it returns an empty string.
- `renderTranscriptBlock` makes one element per block. `text` is markdown. A tool call is a folded `chipLine`, the first line cut at 120 characters. Other kinds go through `plain`, and a truncated block gets a note.
- `unrecordedThinking` is a dim label for thinking with no text. `inlineThinking` shows thinking text under a label, unfolded. `folded` is a `details` element with plain text inside; `tool_result` uses it.
- `ReadingPaneRendererImpl` owns the pane chrome, splitter, layout toggle and bust-out. It hides the reading body and shows the console mount when the content is `console`. `req` and `reqId` look up elements by selector or id at mount and throw when one is missing.
- `QaPaneRendererImpl` paints the Q&A pane from its store. `formatMetric` shows milliseconds or `--`. `anyMetric` keeps the metrics strip hidden until one of the three stamps has landed.
- `SubmitJobsPaneRendererImpl` wires the CC, research, test suite and TFE cards to the store. `schedulingOf` reads a card's schedule checkbox and time, plus the monopolize box when the card has one.

## How the parts work together

`openSeat` asks the reading pane to show the console, and the reading pane renderer paints that choice. The transcript renderer watches a seat only while the pane's content is "console". Each renderer reads its store and repaints when the store announces a change.
