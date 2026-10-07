---
capability: podcast-generation
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.podcast_generator.job.PodcastGeneratorJob@6877725ac2
  - cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent@a29aa8620c
  - cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent.do_all_async@35027a15ba
  - cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent.from_saved_script@31deaf79fe
  - cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent.pause@f6228a01d2
  - cosa.agents.podcast_generator.orchestrator.PodcastGenerationError@0a67abdebe
  - cosa.agents.podcast_generator.orchestrator.auto_approval_notice@4fc01a1320
  - cosa.agents.podcast_generator.state.PodcastScript@56902960a1
  - cosa.agents.podcast_generator.tts_client.PodcastTTSClient@b609170958
  - cosa.agents.podcast_generator.audio_stitcher.PodcastAudioStitcher@7a56300067
  - cosa.agents.podcast_generator.config.PodcastConfig@a0d09ec6c3
---
# Podcast generation

`PodcastGeneratorJob` turns a research document into a two-host podcast: a script, then one MP3 per language, written under `io/podcasts/{user}`. The job runs `PodcastOrchestratorAgent`; the Claude calls are `PodcastAPIClient` in [[generator-sdk-clients]]. The job lifecycle is in [[agentic-job-contract]].

## What it does
- Order: load the document, analyze topics, generate the script, review it, translate and review each extra language, make audio per language, stitch. The state is an `OrchestratorState` (`get_state()` reports it).
- `PodcastTTSClient` streams each segment from ElevenLabs as 24 kHz PCM; `PodcastAudioStitcher` joins them with silence between speakers into an MP3 (192k by default). The key is `ELEVENLABS_API_KEY`, else the key file `eleven11`. The cost in the completion summary is an estimate at 0.30 per 1,000 characters.
- `target_languages` defaults to `["en"]`; The English script is always generated, reviewed and saved; English audio is made only if "en" is listed. `max_segments` limits TTS to the first N segments.
- `from_saved_script` with `do_review_only_async` or `do_audio_only_async` resumes from a script file; only the CLI (`__main__.py`) uses them.

## Invariants
- The script review gate fails open: no answer within `script_review_timeout_seconds` (600) continues as "Approve script", and the completion notice says the script was approved automatically (`auto_approval_notice`). Each translated script has its own gate, with "Skip language".
- "Revise script" followed by silence raises `PodcastGenerationError` and the job fails; it is not turned into an approval. The feedback wait is 300 seconds.
- A script with zero segments raises `PodcastGenerationError` before the gate; it is never offered for approval.
- If some segments fail, the job asks whether to continue with partial audio and takes "yes" when nobody can answer. A language with no successful segment is skipped; if no language has audio, the job fails with a `RuntimeError` that names `ELEVENLABS_API_KEY`.
- The `PodcastConfig` code default is `claude-opus-4-6` with at most 5 turns, but the shipped INI (`[Lupin: Baseline]`) sets `podcast script model` to `claude-opus-5`; `podcast script max turns` is 5 there too.

## How to extend
- A new phase gets an `OrchestratorState` value and a step in `do_all_async` followed by `_check_stop()`.

## Don't
- Don't call `pause()` and expect a pause: it sets `_pause_requested`, which nothing reads, and no code assigns `PAUSED`. Use `stop()` or the job's `request_cancel()`.
