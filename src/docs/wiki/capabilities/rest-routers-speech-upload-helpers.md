---
capability: rest-routers-speech-upload-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.speech.resolve_stt_upload_dir@9a8009f92b
  - cosa.rest.routers.speech.audio_suffix_from_filename@ba6c1f1632
  - cosa.rest.routers.speech.remove_audio_upload@e535062184
  - cosa.rest.routers.speech.insert_stt_io_row@580fa9d1a9
  - cosa.rest.routers.speech.read_utterance_id@6a2dd832bd
  - cosa.rest.routers.speech.stream_frame@7786a29532
  - cosa.rest.routers.speech.get_whisper_pipeline@cf281baeb1
  - cosa.rest.routers.speech.get_speech_provider@2546580ce1
  - cosa.rest.routers.speech.get_websocket_manager@5c65f1b7d1
  - cosa.rest.routers.speech.get_config_manager@ca35634d0d
  - cosa.rest.routers.speech.get_active_tasks@5d1e6982b5
  - cosa.rest.routers.speech.get_ask_flow@e251c77288
---
# Speech routes: upload helpers and dependencies

The small pieces of `routers/speech.py`. The upload helpers serve its MP3 and WAV doors and the two audio doors on [[rest-routers-v2-ask-doors]]. `read_utterance_id` and `stream_frame` serve the speech doors only.

## What it does
- `resolve_stt_upload_dir` returns the INI value of `speech upload temp dir`, stripped, or `/tmp/lupin-stt` when the key is missing or blank.
- `audio_suffix_from_filename` keeps a client filename's extension only if it is a dot plus one to five letters or digits. Otherwise it returns the `fallback`, so the client's name never reaches a path.
- `remove_audio_upload` deletes a saved upload. `None` and an already-gone file are fine, and any other OS error is printed, not raised.
- `insert_stt_io_row` writes one speech-to-text row, with `input_type`, `input`, `output_raw` and `output_final`, to the input and output table.
- `read_utterance_id` reads the optional `utterance_id` from a request body. It must be a string of 1 to 255 characters that encodes as UTF-8, or the TTS door answers 400.
- `stream_frame` adds `utterance_id` to an outgoing frame when one was given and leaves the frame alone when not.
- `get_whisper_pipeline` returns the main module's Whisper pipeline, or `None` in remote model-server mode.
- `get_speech_provider` builds a `SpeechToTextProvider` with the app's debug flags. `get_websocket_manager`, `get_config_manager` and `get_active_tasks` return the main module's `websocket_manager`, `config_mgr` and `active_tasks`.
- `get_ask_flow` returns the main module's v2 flow, `None` before startup finishes. It is not the v2 router's gated dependency of the same name, so it never answers 503.

## Don't
- Don't use a client filename in a path. Use `audio_suffix_from_filename`.
- Don't leave an upload on disk. Call `remove_audio_upload` on every path.

## Invariants
- A saved upload is named `<user8>-<timestamp>-<random><suffix>` and created exclusively.
