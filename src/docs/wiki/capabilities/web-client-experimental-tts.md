---
capability: web-client-experimental-tts
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.test.experimental-tts.ExperimentalProgressiveTTS@fc9ce4c2d7
  - src.lupin_app.static.js.test.experimental-tts.setTestText@1a3d5905f5
  - src.lupin_app.static.js.test.experimental-tts.testProgressiveStreaming@89be7c3882
  - src.lupin_app.static.js.test.experimental-tts.stopStreaming@1752240b6e
  - src.lupin_app.static.js.test.experimental-tts.clearLogs@7fb8ea62f5
  - src.lupin_app.static.js.test.experimental-tts.testABComparison@1b69e28a79
  - src.lupin_app.static.js.test.experimental-tts.updateCustomSettings@48494dbf06
  - src.lupin_app.static.js.test.experimental-tts.getCurrentSettings@a832cd3e50
---
# Web client experimental TTS scripts

The experimental text-to-speech scripts kept in the static folder. [[web-client-audio-and-tts]] describes the audio that ships. No file in this group imports another; each is loaded on its own by the code that calls it.

## What it does
- `experimental-tts.js`. `ExperimentalProgressiveTTS`: Models a page that streams TTS audio over a WebSocket and measures latency. `setTestText`: Fills the test text box with a preset message and focuses it. `testProgressiveStreaming`: Starts the streaming test on the page's experimental TTS object, if it exists. `stopStreaming`: Stops streaming on the page's experimental TTS object, if it exists. `clearLogs`: Clears the log on the page's experimental TTS object, if it exists. `testABComparison`: Starts the Flash and Turbo comparison on the page's TTS test object. `updateCustomSettings`: Shows or hides the custom settings and sets the model for the profile. `getCurrentSettings`: Reads the model, voice and profile controls into a settings object.
