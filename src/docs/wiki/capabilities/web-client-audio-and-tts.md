---
capability: web-client-audio-and-tts
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.audio.AudioRecorder.AudioRecorder@5b4685811f
  - src.lupin_app.static.js.multiplexer.audio.recordingManager.RecordingManager@9943e780a7
  - src.lupin_app.static.js.multiplexer.audio.pcm-decoder.pcm16ToAudioBuffer@a1fc299226
  - src.lupin_app.static.js.multiplexer.stores.AudioStore.createAudioStore@1a56a14b2a
  - src.lupin_app.static.js.multiplexer.stores.TtsQueueStore.createTtsQueueStore@b45f90b61e
  - src.lupin_app.static.js.multiplexer.wireTtsPlayback.wireTtsPlayback@6284cc3a19
  - src.lupin_app.static.js.multiplexer.wireTtsIntent.wireNotificationTtsIntent@0a44a0071a
  - src.lupin_app.static.js.multiplexer.shared.ttsPreview.computeTtsPreview@27e7f93477
  - src.lupin_app.static.js.multiplexer.render.TtsPreviewSliderRenderer.createTtsPreviewSliderRenderer@0bcd474087
---
# Browser audio and TTS

The browser records speech for transcription and plays server-made speech through a queue. The code is in `src/lupin_app/static/js/multiplexer/`.

## Recording
- `recordingManager` keeps one recording at a time, starts a new `AudioRecorder` for each, and cancels it on Esc.
- The recorder takes the first supported of mp3, webm and ogg, and stops after 30 seconds. No caller changes either value.
- It sends the whole recording as one base64 text body to `/api/upload-and-transcribe-mp3` and reads `transcription` from the reply.
- The manager has hooks to pause speech while recording, but nothing sets them, so speech keeps playing.

## Speaking
- A notification is queued for speech only at `high` or `urgent` priority. Job answers and Direct TTS text also queue, but job answers are dropped at a 0% slider.
- `wireNotificationTtsIntent` applies the preview slider first, and `TtsQueueStore` then plays one item at a time, in arrival order.
- `wireTtsPlayback` posts the active item's text once, to `/api/get-speech-elevenlabs` in `instant` mode or `/api/get-speech` in `reliable` mode. `instant` is the default.
- Audio comes back as binary frames on the audio WebSocket. `AudioStore` decodes 16-bit mono PCM at 24 kHz and schedules each chunk right after the last.
- An item ends when the stream-complete message has arrived and no chunk is still playing. A watchdog forces the end if no audio arrives within 30 seconds of the request. Once chunks are scheduled it allows the remaining audio plus 10 seconds, and a manual pause stops it.
- Live speech is not cached. The queue keeps its waiting items across a page reload.

## Preview slider
- The slider has nine stops from 0% to 100%. At 0% nothing is queued except text sent from the Direct TTS pane.
- With `tts preview enabled` true, as shipped, text of 100 characters or more is cut after the chosen fraction. The cut falls at the next sentence end, dash or line break.
- The legacy page's saved slider value, when valid, outranks this page's saved value, which outranks the server default of 25%.

## Not wired
- The Direct TTS pane reads `TtsAudioCache`, and this client never writes it. The legacy page shares the IndexedDB and does write it, so text it cached plays without the queue.
- `SequentialAudioManager` and `JobCompletionCache` are never created.
