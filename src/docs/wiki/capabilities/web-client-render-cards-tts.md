---
capability: web-client-render-cards-tts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.ttsChrome.ttsHeaderMode@de2508f4cb
  - src.lupin_app.static.js.multiplexer.render.templates.ttsChrome.deriveControlState@45a32dd352
  - src.lupin_app.static.js.multiplexer.render.templates.ttsChrome.wireControl@fbbf9ba1a5
  - src.lupin_app.static.js.multiplexer.render.templates.ttsChrome.rootClass@508bf724de
  - src.lupin_app.static.js.multiplexer.render.templates.ttsChrome.renderTtsEmpty@750b6f1ecd
  - src.lupin_app.static.js.multiplexer.render.templates.ttsChrome.renderTtsChrome@8b3f948d45
  - src.lupin_app.static.js.multiplexer.render.templates.ttsCardShared.ttsCardIcon@29d2887bde
  - src.lupin_app.static.js.multiplexer.render.templates.ttsCardShared.truncateTtsText@7a76990b12
  - src.lupin_app.static.js.multiplexer.render.templates.ttsCardShared.ttsCardTime@aef52dafec
  - src.lupin_app.static.js.multiplexer.render.templates.ttsActiveCard.renderTtsActiveCard@9e92cb04ae
  - src.lupin_app.static.js.multiplexer.render.templates.ttsMinimizedCard.renderTtsMinimizedCard@39d3d92b8c
  - src.lupin_app.static.js.multiplexer.render.templates.ttsPreviewSlider.renderTtsPreviewSlider@96bf9ec810
---
# Speech queue templates

Builds the speech queue pane: transport controls, the card for the item being spoken, cards for waiting items, and the preview slider.

## Chrome
- `renderTtsChrome( opts, handlers )` returns the control panel. When `queueEmpty` is true it returns the empty panel instead, whatever the audio state. It also draws a Clear all button, always enabled and shown, which acts only when `onClearAll` is given. A Resume button is present only in focus mode. `TtsChromeRenderer` is the only caller.
- `ttsHeaderMode( state, focusMode, hasActive )` returns paused only when audio is paused with an active item, then focus, otherwise playing. It returns only that mode; the chrome and `TtsChromeRenderer` read it.
- `deriveControlState` is private. Only playing enables Pause, only paused enables Play, and Stop is on for playing, paused, ended and error. Skip is on for playing and paused.
- `wireControl` is private. It sets `disabled`, toggles the disabled class and attaches the click listener only when enabled.
- `rootClass` is private. It adds the playing or paused class to the chrome root.
- `renderTtsEmpty` is private. It builds the "Nothing in the queue" panel with `data-state` idle.

## Cards and slider
- `ttsCardIcon` returns a warning sign for action required items, else a bell. `truncateTtsText( text, max )` cuts to `max` characters ending in three dots.
- `ttsCardTime` returns the notification's display time when set, else the enqueue time in 24-hour hours and minutes.
- `renderTtsActiveCard( item, handlers )` shows icon, time, text cut to 80, a Stop button and a delete button. Delete calls `onDelete` with the item's id hash.
- `renderTtsMinimizedCard( item, position, handlers )` shows position, icon, time, text cut to 50 and delete. Action required items get a priority class.
- `renderTtsPreviewSlider( opts, handlers )` returns a `div.tts-preview-slider`. It holds a `TTS:` label, a range input from 0 to 100 in steps of 12.5, a datalist of nine stops and a value label. Each input event calls `onInput` with a float.

Every template writes text with `textContent` or the `html` helper, never raw markup. The renderer owns which item is active and the card positions.
