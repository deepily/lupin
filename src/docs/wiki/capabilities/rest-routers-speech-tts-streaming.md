---
capability: rest-routers-speech-tts-streaming
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.speech.get_tts_audio@a601cde028
  - cosa.rest.routers.speech.get_tts_audio_elevenlabs@a261b96ea0
  - cosa.rest.routers.speech.stream_tts_hybrid@8457fec2fa
  - cosa.rest.routers.speech.stream_tts_elevenlabs@14e7d8deb6
  - cosa.rest.routers.speech.websocket_pcm_tts_endpoint@f85afa39b6
---
# Speech routes: text-to-speech streaming

Text goes in by POST, and audio comes back over the caller's already-open audio WebSocket, not in the HTTP reply. The upload helpers are on [[rest-routers-speech-upload-helpers]].

## What it does
- `get_tts_audio` (`POST /api/get-speech`) takes `session_id` and `text`, starts OpenAI streaming in the background and replies at once with `status: success`. A user token is required.
- `get_tts_audio_elevenlabs` (`POST /api/get-speech-elevenlabs`) does the same through ElevenLabs. It also takes optional `voice_id`, `model_id`, `stability`, `similarity_boost`, `speed`, `style`, `use_speaker_boost` and `quality_profile`, and replies with the provider and voice.
- `stream_tts_hybrid` forwards each 8192-byte OpenAI MP3 chunk to the WebSocket as it arrives, then sends a completion frame with timing and chunk count. Failures go to the client as error frames.
- `stream_tts_elevenlabs` streams text to ElevenLabs and forwards decoded audio chunks the same way.
- `websocket_pcm_tts_endpoint` (`/api/ws/pcm-tts`) is a WebSocket demo door with no credential check. The browser connects with optional `model_id` and `voice_id` query values. It takes no client text: the server speaks one fixed test sentence and relays the raw 24000 Hz PCM from ElevenLabs.
- Every JSON frame of the two POST streams carries `utterance_id` when the request had one. PCM frames carry none.

## Don't
- Don't send `text` over 10,000 characters or a `session_id` over 255. Both answer 400.
- Don't call either POST door without an open audio WebSocket for that `session_id`. It answers 404.
- Don't send ElevenLabs `stability` or `similarity_boost` outside 0.0 to 1.0, or `speed` outside 0.1 to 3.0. Each answers 400.

## Invariants
- `active_tasks` holds the latest task per `session_id`. A second POST overwrites the entry and does not cancel the first stream.
