# Dry-Run Podcast Fixture

`podcast-dry-run.mp3` is a **pre-rendered, committed** podcast fixture: Maria and
Mr. Radio literally narrating what dry-run mode does. It is served by
`PodcastGeneratorJob._execute_dry_run` so that a **dry-run submit plays real audio
in the floating overlay** — a zero-cost, end-to-end exercise of the whole overlay
path (Play Here link → `&embed=1` interception → iframe render → blob-fetch auth →
auto-start) every time anyone runs one.

## Provenance

- **Source script**: `MOCK_SCRIPT_RESPONSE` in
  `src/cosa/agents/podcast_generator/mock_clients.py` (10 segments, 2 speakers).
- **Rendered via**: the production TTS path — `PodcastTTSClient`
  (ElevenLabs `eleven_turbo_v2_5`) + `PodcastAudioStitcher`.
- **Voices**: Maria `kcQkGnn0HAT2JRDQ4Ljp`, Mr. Radio `Aa6nEBJJMKJwJkCx8VU2`
  (the `podcast voice female/male id` keys in `src/conf/lupin-app.ini`, identical
  to the matching `cc session voice persona` ids).
- **Cost to render**: 415 characters billed to ElevenLabs (turbo v2.5). One-time.
- **Output**: ~27.2s, mono 24 kHz, ~532 KB.

## Regenerating (rarely needed — that's the point of committing it)

The fixture is committed precisely so it never has to be regenerated. If the mock
script changes and you must re-render, drive `PodcastTTSClient.generate_all_segments`
+ `PodcastAudioStitcher.stitch_segments` over `MOCK_SCRIPT_RESPONSE` and write the
result back to this path (`io/fixtures/podcast-dry-run/podcast-dry-run.mp3`).

## Not a real podcast

Dry-run mode never generates content. This is a fixture; the audio itself says so.
The job card keeps its 🧪 markers and "not a real podcast" framing intact.
