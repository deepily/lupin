---
capability: web-client-render-dictation-toggle
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.dictationToggle.startDictation@e58e81191d
  - src.lupin_app.static.js.multiplexer.render.dictationToggle.toggleDictation@4f6a0f095c
---
# Web client: the shared dictation mic

`dictationToggle.ts` holds the click logic every dictation mic shares. Three mics once kept their own copy: the action-required mic, the new-ticket field mic and the reason mic. The sender card and broadcast card mics now use it too.

## What it does
- `startDictation( options )` stashes the input's text and selection, shows `recording` on the button and starts the recorder.
- `onStart` sees the stash before the recorder starts. `currentStash`, when given, supplies the text the words splice into, so a card that resets its own record mid-recording keeps the reset.
- A transcription is spliced in at the stashed caret, or at the live caret with `liveCaret`. With `focusAfterInsert` the input also takes focus through `setValueFocusCaret`.
- Every outcome clears `recording` and `processing`. `afterInsert`, `onError` and `onCancel` run after the button is reset.
- `toggleDictation( options )` is the click handler. A click while this mic is processing does nothing. A click while this context records stops it and marks the button `processing`.
- With `stopOther`, a click while another context records stops that one and starts nothing. Otherwise `toggleDictation` calls `startDictation`.

## Don't
- Don't keep a private copy of the stash and splice code in a new mic. Pass the four differences as options.
