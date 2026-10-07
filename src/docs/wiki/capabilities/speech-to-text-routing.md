---
capability: speech-to-text-routing
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.memory.speech_to_text_provider.SpeechToTextProvider@7e666d2675
  - cosa.memory.speech_to_text_provider.SpeechToTextProvider.transcribe@0a0b07b325
  - cosa.memory.speech_to_text_provider.SpeechToTextProvider.declare_in_process_owner@098b04c17a
  - cosa.rest.routers.speech.upload_and_transcribe_mp3_file@55d6f0b872
  - cosa.rest.routers.speech.upload_and_transcribe_wav_file@e26c02b1c8
  - cosa.rest.routers.speech.save_audio_upload@eb408b4df7
---
# Speech-to-text routing

One singleton, `SpeechToTextProvider`, sends audio to in-process Whisper or to the model server. The server end is [[model-server]]; INI keys are in [[configuration]].

## What it does
- `transcribe` runs the in-process pipeline only when the INI value is `local` and the process called `declare_in_process_owner`.
- Any other case POSTs the file to the model server's `/transcribe` and ignores extra keyword arguments.
- The code default is `local`. The shipped INI sets `model-server` only under Development, which Testing inherits; Baseline and Production set nothing.
- The INI value is read once, when the singleton is first built. The `main.py` lifespan reads the same key itself.
- In `model-server` mode the lifespan skips the Whisper load and calls `declare_remote_only`. After a successful local load it calls `declare_in_process_owner`.
- Local mode puts `return_timestamps=True` under the caller's keywords and retries once after a CUDA out-of-memory. It returns a dict result's `text`; any other result goes through `str`.
- The URL is `LUPIN_MODEL_SERVER_URL`, else the INI `model server url`, else `http://lupin-model-server:7998`. The request sends an `X-API-Key` header.
- The HTTP call times out at 120 s. It makes up to three attempts, sleeping 2 s then 4 s, on timeouts, connection errors and 5xx.
- A 4xx reply is not retried.
- Four routes call `transcribe`, each through `get_speech_provider`: `/api/upload-and-transcribe-mp3`, `/api/upload-and-transcribe-wav`, `/api/v2/ask-audio` and `/api/v2/transcribe`.
- Each route saves the audio with `save_audio_upload` under INI `speech upload temp dir` (`/tmp/lupin-stt` in INI and code). A `finally` removes it.

## Don't
- Don't call `whisper_pipeline` directly in a new route. In model-server mode it is `None`; use the provider so both modes work.
- Don't expect a fallback. A local failure other than the one OOM retry propagates; it never switches to HTTP.
- Don't expect `chunk_length_s` or other keywords to reach the model server. The HTTP path takes the file only.
- Don't send an agent request to the MP3 door without a bearer token. It transcribes first, then answers 401. Plain dictation needs no token.

## Invariants
- Local mode with no pipeline passed raises `RuntimeError`. So do a missing API key, an unreadable file, an unreachable server, a non-200 reply and a reply without `text`.
- The MP3 door turns that error into a fixed-text 500; the WAV door puts the message in its 500. Out-of-memory becomes 503 with `Retry-After: 5`.
- The saved name is `<uid8>-<time>-<random><suffix>`, with `anon` when no user id survives cleaning. A failed write removes the file.
- `/api/v2/ask-audio` and `/api/v2/transcribe` answer 422 for an empty transcript. The MP3 and WAV doors have no such check.
