---
capability: web-client-audio-modules
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.audio-recorder.AudioRecorder@bca1865f32
  - src.lupin_app.static.js.hybrid-tts.HybridTTS@706943cb41
  - src.lupin_app.static.js.job-completion-cache.JobCompletionCache@1d14a266a4
  - src.lupin_app.static.js.multiplexer.audio.JobCompletionCache.defaultIndexedDBFactory@35f7dec4df
  - src.lupin_app.static.js.multiplexer.audio.JobCompletionCache.JobCompletionCache@afd7858617
  - src.lupin_app.static.js.multiplexer.audio.SequentialAudioManager.SequentialAudioManager@920c5dc455
  - src.lupin_app.static.js.multiplexer.audio.TtsAudioCache.defaultIndexedDBFactory@1e5ff07151
  - src.lupin_app.static.js.multiplexer.audio.TtsAudioCache.TtsAudioCache@536b5eebe2
  - src.lupin_app.static.js.multiplexer.audio.directTtsPlayback.DirectTtsPlayerImpl@fda63cb9b9
  - src.lupin_app.static.js.multiplexer.audio.directTtsPlayback.createDirectTtsPlayer@ad66de8283
  - src.lupin_app.static.js.multiplexer.audio.pcm-decoder.pcm16ToAudioBufferFromBlob@c08863664b
  - src.lupin_app.static.js.sequential-audio-manager.SequentialAudioManager@e86b52ab86
  - src.lupin_app.static.js.tts-audio-cache.TTSAudioCache@f4a9ad1171
---
# Web client audio modules

TTS playback, its caches and the recorder, in the multiplexer's modules and the older page scripts. [[web-client-audio-and-tts]] describes the audio flow. No file in this group imports another; each is loaded on its own by the code that calls it.

## What it does
- `audio-recorder.js`. `AudioRecorder`: AudioRecorder - Reusable audio recording module with server-side transcription.
- `hybrid-tts.js`. `HybridTTS`: Hybrid TTS Module.
- `job-completion-cache.js`. `JobCompletionCache`: Job Completion Cache Module.
- `JobCompletionCache.ts`. `defaultIndexedDBFactory`: Returns the browser IndexedDB factory, or null when the environment has none. `JobCompletionCache`: A two-tier cache of job-completion messages, keyed by job id, in memory and in IndexedDB.
- `SequentialAudioManager.ts`. `SequentialAudioManager`: Plays audio chunks one after another, in the order they were added.
- `TtsAudioCache.ts`. `defaultIndexedDBFactory`: Returns the browser's global IndexedDB when it exists, and null otherwise. `TtsAudioCache`: A two-tier cache of synthesized speech, in memory and in IndexedDB.
- `directTtsPlayback.ts`. `DirectTtsPlayerImpl`: Plays TTS audio blobs through an audio element and tracks the one playing. `createDirectTtsPlayer`: Build a player for cached speech blobs.
- `pcm-decoder.ts`. `pcm16ToAudioBufferFromBlob`: Async wrapper for Blob inputs. AudioStore's binary handler may receive.
- `sequential-audio-manager.js`. `SequentialAudioManager`: Sequential Audio Manager.
- `tts-audio-cache.js`. `TTSAudioCache`: TTS Audio Cache Module.
