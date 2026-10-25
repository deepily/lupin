---
capability: web-client-render-action-required-interactive
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.renderActionRequiredInteractive@014a28433b
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildYesNo@8dd837f237
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.withComment@eb355a18bb
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.appendYesNoComment@60441dcc3f
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildMultipleChoice@1d28b89fda
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildOpenEnded@5d390bceba
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildOpenEndedBatch@0b98fc36b7
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.appendNoQuestions@e1d1efa348
  - src.lupin_app.static.js.multiplexer.render.actionRequiredMic.createActionRequiredMic@a226fc0930
---
# Action-required interactive forms

The answer forms of an action-required card, one per response type, and the microphone handler they share.

## What it does
- `renderActionRequiredInteractive( item, handlers, step? )` returns the widget for `yes_no`, `multiple_choice`, `open_ended` or `open_ended_batch`. Any other type throws `Unknown response_type`.
- `buildYesNo` paints Yes, No and Neither buttons. A yes or no matching `item.default` gets `default-value`; Neither never does.
- `withComment( answer, comment )` returns `answer [comment: text]` for a non-blank comment and the bare answer otherwise.
- `appendYesNoComment` adds a hint, a mic and a 300 character input, and returns the input. Enter leaves the field without submitting.
- `buildMultipleChoice` shows one question at a time with Back, Next and Submit. A step with nothing chosen is marked invalid and does not advance.
- A multi-select question gives an array and an "Other" text is trimmed and dropped when blank. `onStep` reports the position after every Back, Next and Submit.
- `buildOpenEnded` fills the input from `item.default`. Submit stays disabled until the trimmed text is non-empty, and Enter submits it.
- `buildOpenEndedBatch` paints one input per question and sends `{ answers }` by header only when every row has text. A blank row gets `invalid`.
- `appendNoQuestions` adds "No questions provided." and returns true when the item has no questions. The multiple-choice and batch forms stop there.
- `createActionRequiredMic( recorder, getAuthToken )` returns the click handler a card 🎤 calls.
- A click while this context records stops it and shows `processing`. A click while `processing` does nothing. A click while another context records stops that one and starts nothing.
- Otherwise it starts recording. A transcription goes in at the caret, an `input` event fires, and the button resets on completion, error or cancel.

## How the parts work together
`onSubmit` receives a string for yes/no and open-ended answers and `{ answers }` for the stepped and batch forms. Without `onMic` a mic button renders and does nothing.
