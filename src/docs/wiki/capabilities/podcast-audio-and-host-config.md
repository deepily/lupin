---
capability: podcast-audio-and-host-config
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.api_client.APIResponse@640401391b
  - cosa.agents.podcast_generator.audio_stitcher.StitchingResult@fe54d737f5
  - cosa.agents.podcast_generator.config.HostPersonality@005c32a8a0
  - cosa.agents.podcast_generator.config.VoiceProfile@6d8d798ed9
  - cosa.agents.podcast_generator.tts_client.TTSSegmentResult@2924886016
  - cosa.agents.podcast_generator.tts_client.VoiceConfig@708d9863de
---
# Podcast audio results and host config

Small value types used by the script and audio phases of [[podcast-generation]]. The clients that fill them are `PodcastAPIClient` ([[generator-sdk-clients]]), `PodcastTTSClient` and `PodcastAudioStitcher`.

## What it does
- `APIResponse` is one script-phase model reply: content, model, token counts, stop reason, the SDK-reported cost and the raw response.
- `TTSSegmentResult` is one spoken segment. It holds the index, speaker, role, PCM bytes (24 kHz, 16-bit, mono), a character count, a success flag, an error message and a retry count. A missing duration is computed from the PCM length.
- `StitchingResult` is what `stitch_segments` returns: output path, total duration, segments stitched, file size, a success flag and an error message.
- `VoiceConfig` is the per-speaker voice the TTS client resolves: voice id, name, language code (default `en`), stability 0.65, similarity boost 0.75 and style 0.35.
- `VoiceProfile` is the INI-side voice: the same three numbers plus `use_speaker_boost`. It raises `AssertionError` if stability, similarity boost or style is outside 0 to 1. `from_config( config_mgr, prefix )` reads `{prefix} id`, `name`, `stability`, `similarity boost`, `style` and `use speaker boost`.
- `HostPersonality` is one host's profile: name, role, tone, expertise, curiosity, speaking style, typical phrases and interaction style. `to_prompt_description()` renders it as labelled lines. `from_config( config_mgr, prefix )` reads `{prefix} name` and the other keys, and splits `typical phrases` on `|`.

## Don't
- Don't mix up `VoiceConfig` (TTS client) and `VoiceProfile` (config module); they hold the same numbers in two dataclasses.
