---
capability: web-client-stores-panes
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.isActionRequiredLive@cc5c12b4b7
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.isAwaitingActivation@8af6c07cfb
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.countLiveActionRequired@eeebfd88b6
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.cancelResponseFor@fceef38358
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.toWireResponseValue@666c543412
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.ActionRequiredStoreImpl@a5f73a1da3
  - src.lupin_app.static.js.multiplexer.stores.ActionRequiredStore.createActionRequiredStore@7cfee635c9
  - src.lupin_app.static.js.multiplexer.stores.AudioStore.AudioStoreImpl@76c9a010b7
  - src.lupin_app.static.js.multiplexer.stores.AudioStore.defaultAudioContextFactory@cda967fc18
  - src.lupin_app.static.js.multiplexer.stores.PredictionVoteStore.PredictionVoteStoreImpl@9241012ffb
  - src.lupin_app.static.js.multiplexer.stores.PredictionVoteStore.createPredictionVoteStore@53ee19b10a
  - src.lupin_app.static.js.multiplexer.stores.QaStore.QaStoreImpl@83dc7389a8
  - src.lupin_app.static.js.multiplexer.stores.QaStore.errorText@3f111b35ad
  - src.lupin_app.static.js.multiplexer.stores.QaStore.createQaStore@24051d0bd8
  - src.lupin_app.static.js.multiplexer.stores.ReadingPaneStore.ReadingPaneStoreImpl@78359302b4
  - src.lupin_app.static.js.multiplexer.stores.ReadingPaneStore.createReadingPaneStore@6a2eac0a6e
  - src.lupin_app.static.js.multiplexer.stores.TtsQueueStore.TtsQueueStoreImpl@41be18f161
  - src.lupin_app.static.js.multiplexer.stores.ViewStateStore.ViewStateStoreImpl@c915406e29
  - src.lupin_app.static.js.multiplexer.stores.ViewStateStore.coerceFlagMap@a4bfc334b6
  - src.lupin_app.static.js.multiplexer.stores.ViewStateStore.createViewStateStore@467d9d04fa
  - src.lupin_app.static.js.multiplexer.stores.PredictionVoteStore.castPredictionVote@3445b6d201
  - src.lupin_app.static.js.multiplexer.stores.contextForecastFetch.createContextForecastFetcher@e3311804c6
---
# Web client stores: panes and audio

The stores for action-required prompts, TTS audio, the Q and A pane, the reading pane and view state. [[web-client-stores]] covers how they are built. No file in this group imports another; each is loaded on its own by the code that calls it.

## What it does
- `ActionRequiredStore.ts`. `isActionRequiredLive`: Takes the bare `state` so the reading pane's looser item shape can ask it too. `isAwaitingActivation`: a card first in line that has not started: it arrived while TTS played and waits for the current item to finish. The one predicate the store and the renderer both ask. `countLiveActionRequired`: The number of cards in `items` still owed an answer. `cancelResponseFor`: What the ✕ answers a prompt with. `toWireResponseValue`: Turn a response into the server's string: a string as is, anything else as JSON. `ActionRequiredStoreImpl`: Tracks pending action-required prompts with countdowns and a response flow. `respondAndAwait` takes an optional route and posts it as `input_route`. It listens for `prediction_hint_updated`. `applyContextForecast( id, forecast )` puts a card's background Haiku forecast on its hint and emits `context-forecast`. An unknown id or a card with no hint is left alone. `createActionRequiredStore`: Build the store.
- `AudioStore.ts`. `AudioStoreImpl`: Models TTS audio playback as a state machine fed by binary chunks from the audio socket. `defaultAudioContextFactory`: Creates a browser audio context at 24000 Hz for production use.
- `PredictionVoteStore.ts`. `PredictionVoteStoreImpl`: Models thumbs up and down votes on predictions, keyed by notification ID. `createPredictionVoteStore`: Build the store. It makes no request until a vote is cast or a forecast is reported seen. `reportSeen( id, event, draft? )` sends `rendered` or `fold_opened` once per notification and forgets a failed call. A fold-open carries `draft_at_reveal` when a draft is given, and a render never does. The first fold-open's draft is kept, so a retry sends it again and never a draft read after the forecast showed. `isFoldOpen` says whether the reader opened the fold. `castPredictionVote`: Sets the context, sends the vote and runs `revert` once if it is refused or throws.
- `contextForecastFetch.ts`. `createContextForecastFetcher( api, target )`: Builds the function that refreshes one card's Haiku forecast from `/api/notify/prediction-hint/<id>`. It asks only when the card's forecast reads forecasting. A reply with a forecast replaces it. A null forecast or a failed call leaves it alone, and the fetch never throws.
- `QaStore.ts`. `QaStoreImpl`: Models the question and answer pane: agents, status, response and timing. `errorText`: The message a caller should show for a thrown value of unknown shape. `createQaStore`: Build the store.
- `ReadingPaneStore.ts`. `ReadingPaneStoreImpl`: Models the reading pane: layout mode, split ratio, history of opened entries, console. `createReadingPaneStore`: Construct a ReadingPaneStore.
- `TtsQueueStore.ts`. `TtsQueueStoreImpl`: Models the speech queue: one active item and a first-in first-out list of pending items.
- `ViewStateStore.ts`. `ViewStateStoreImpl`: Models which sections are hidden and which accordions are collapsed. `coerceFlagMap`: Returns a map holding only the boolean entries of a saved value. `createViewStateStore`: Construct a ViewStateStore.
