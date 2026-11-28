---
capability: web-client-render-action-required-interactive
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.renderActionRequiredInteractive@014a28433b
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildYesNo@174e6245c7
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.withComment@eb355a18bb
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.appendYesNoComment@f69c2586fa
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildMultipleChoice@7e77b83e5a
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildOpenEnded@99f2f916d8
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.buildOpenEndedBatch@d5a4d73c3c
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.appendNoQuestions@e1d1efa348
  - src.lupin_app.static.js.multiplexer.render.actionRequiredMic.createActionRequiredMic@d56bbb1e17
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.checkedChoices@03585cc962
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.markVoice@9d080bb778
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.clearVoice@4cda69d3b2
  - src.lupin_app.static.js.multiplexer.render.templates.actionRequiredInteractive.commentRoute@320d187b05
---
# Action-required interactive forms
The answer forms of an action-required card, one per response type, and the microphone handler they share.

## What it does
- `renderActionRequiredInteractive( item, handlers, step? )` returns the widget for `yes_no`, `multiple_choice`, `open_ended` or `open_ended_batch`. Any other type throws `Unknown response_type`.
- `buildYesNo` paints Yes, No and Neither buttons. A yes or no matching `item.default` gets `default-value`; Neither never does.
- `withComment( answer, comment )` returns `answer [comment: text]` for a non-blank comment and the bare answer otherwise.
- `appendYesNoComment` adds a hint, a mic and a 300 character input, and returns the input. Enter leaves the field without submitting.
- `buildMultipleChoice` shows one question at a time with Back, Next and Submit. A step with nothing chosen is marked invalid and does not advance.
- A multi-select question gives an array and an "Other" text is trimmed and dropped when blank. `checkedChoices( block )` is the one reader of a question's ticks. It gives the value of each ticked option in page order. A ticked Other counts through its trimmed text, and an empty one counts for nothing. It marks nothing invalid and changes no control. `buildMultipleChoice` uses it when saving a step, and [[web-client-render-action-required-draft]] uses it to read the question on screen. `onStep` reports the position after every Back, Next and Submit.
- `buildOpenEnded` fills the input from `item.default`. Submit stays disabled until the trimmed text is non-empty, and Enter submits it.
- `buildOpenEndedBatch` paints one input per question and sends `{ answers }` by header only when every row has text. A blank row gets `invalid`.
- `appendNoQuestions` adds "No questions provided." and returns true when the item has no questions. The multiple-choice and batch forms stop there.
- `createActionRequiredMic( recorder, getAuthToken )` returns the click handler a card 🎤 calls. The click logic is the shared `toggleDictation` in `dictationToggle.ts`.
- A click while this context records stops it and shows `processing`. A click while `processing` does nothing. A click while another context records stops that one and starts nothing.
- Otherwise it starts recording. A transcription goes in at the caret, an `input` event fires, and the button resets on completion, error or cancel.
- `markVoice( input )` flags a field when its mic is clicked, and `clearVoice( input )` drops the flag on a key press. `commentRoute( input, typedRoute )` gives `voice` while the flag is set and `typedRoute`, `comment` by default, otherwise.
- Routes: a yes/no answer with a blank comment is `click`, else `comment` or `voice`. An open-ended answer is `typed` or `voice`, and every batch answer is `typed`. A stepped answer is `click` unless it was saved with Other ticked and filled. It is then `typed`, or `voice` after the Other mic with no key press since.
- The Other flags live in the widget, not in the saved step. A question answered through Other before a repaint, and not saved again, is sent as `click`.

## How the parts work together
`onSubmit` receives a string for yes/no and open-ended answers and `{ answers }` for the stepped and batch forms. Its second argument is the route, how the answer was given: `click`, `typed`, `comment` or `voice`. The stepped and batch forms give one route per question header. Without `onMic` a mic button renders and does nothing.
