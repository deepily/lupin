---
capability: web-client-render-voice-and-tts
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.DirectTtsRenderer.directTtsTestText@86f4bcaf4a
  - src.lupin_app.static.js.multiplexer.render.DirectTtsRenderer.DirectTtsRendererImpl@64f815192e
  - src.lupin_app.static.js.multiplexer.render.DirectTtsRenderer.createDirectTtsRenderer@c5a6801517
  - src.lupin_app.static.js.multiplexer.render.TtsChromeRenderer.TtsChromeRendererImpl@6cabb033cf
  - src.lupin_app.static.js.multiplexer.render.TtsChromeRenderer.createTtsChromeRenderer@11ad140f34
  - src.lupin_app.static.js.multiplexer.render.TtsPreviewSliderRenderer.clampFraction@5b56e544bd
  - src.lupin_app.static.js.multiplexer.render.TtsPreviewSliderRenderer.resolveInitialFraction@663c458ce1
  - src.lupin_app.static.js.multiplexer.render.TtsPreviewSliderRenderer.readLegacyFraction@9dd38e5c41
  - src.lupin_app.static.js.multiplexer.render.TtsPreviewSliderRenderer.resolveLiveFraction@e2e450347d
  - src.lupin_app.static.js.multiplexer.render.TtsPreviewSliderRenderer.TtsPreviewSliderRendererImpl@8cefa606de
  - src.lupin_app.static.js.multiplexer.render.ConversationModePinRenderer.ConversationModePinRendererImpl@bd99e761e5
  - src.lupin_app.static.js.multiplexer.render.ConversationModePinRenderer.cssEscape@6428b04fa5
  - src.lupin_app.static.js.multiplexer.render.ConversationModePinRenderer.createConversationModePinRenderer@a381b7ec26
  - src.lupin_app.static.js.multiplexer.render.TimeSavedRenderer.TimeSavedRendererImpl@e50983b969
  - src.lupin_app.static.js.multiplexer.render.TimeSavedRenderer.createTimeSavedRenderer@336093145b
---
# Voice and TTS render modules

These five modules draw the speech-related panes of the multiplexer page and wire their controls.

- `DirectTtsRendererImpl` (built by `createDirectTtsRenderer`) draws the Direct TTS Test pane: one text input and four buttons, with no Enter-key handler.
- Speak Now refuses empty text through `errorFn`, then checks the cache. A hit plays the blob directly; a miss calls `speak`. The input clears after playback ends, and also after a failed play or cache check.
- `directTtsTestText` builds the sentence for the Test Instant and Test Reliable buttons from the mode name, which each button passes as a fixed value. Only Speak Now reads the mode from the audio store.
- `TtsChromeRendererImpl` (built by `createTtsChromeRenderer`) draws the Playing section with pause, resume, stop, skip, clear and focus-resume controls, plus the active and waiting cards.
- After the first paint at `mount`, it coalesces repaints to one per animation frame after audio state, decoded chunk or queue change events. A second `mount` without `unmount` throws.
- `clampFraction` returns a number only when it is finite and between 0 and 1; anything else gives `null`.
- `resolveInitialFraction` prefers a valid stored value, then a valid INI default, then 0.25. `readLegacyFraction` reads the old client's raw storage key and returns `null` when it is missing, invalid or unreadable.
- `resolveLiveFraction` resolves the current value on demand. The legacy key wins, then the mounted slider, then the stored value, INI default and 0.25.
- `TtsPreviewSliderRendererImpl` draws the slider and writes each move to both its own storage entry and the legacy key. `seedIniDefault` does nothing once the user has chosen a value.
- `ConversationModePinRendererImpl` (built by `createConversationModePinRenderer`) sets `data-pinned-conv-mode` on the pinned sender's card. It sets `data-focus-flash` for 1200 ms by default when the pin moves to a different card, never on the first pin after mount. The private `cssEscape` makes the sender id safe for the card selector.
- `TimeSavedRendererImpl` (built by `createTimeSavedRenderer`) draws four stat tiles and a leaderboard. It fetches once at mount and again when the refresh button is pressed.
- Each of its two fetches is separate. A failure is only logged and leaves the earlier values on screen. On a successful answer a missing count shows `0` and a missing formatted time shows `--`.

## How the parts work together

Each renderer is created with its stores or clients, mounted on a root element, and unmounted to release listeners. For how audio itself plays, see [[web-client-audio-and-tts]]. The chrome's queue state comes from stores owned elsewhere. The slider keeps its own fraction and persists it to storage.
