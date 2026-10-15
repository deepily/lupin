---
capability: podcast-mock-clients
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.podcast_generator.mock_clients.MockCostEstimate@a6f03bb687
  - cosa.agents.podcast_generator.mock_clients.MockPodcastAPIClient@27c188cf47
  - cosa.agents.podcast_generator.mock_clients.MockTTSClient@ecb17b6cd6
  - cosa.agents.podcast_generator.mock_clients.MockTTSSegmentResult@29addfc020
---
# Podcast mock clients

`mock_clients.py` has stand-ins for the script and speech clients of [[podcast-generation]]: a canned script, and silence for audio. No key or network is needed.

## What it does
- `MockPodcastAPIClient` has `generate_script`, `revise_script` and `call_with_json_output`. Each waits one second, counts the call in `call_count` and returns a ten-segment script between Maria and Mr. Radio. A revision changes only the title.
- `MockCostEstimate` mirrors the real cost tracker. Its `add_usage` raises only the call count; the cost stays 0.
- `MockTTSClient` has `generate_segment` and `generate_all_segments`. Each segment waits 0.3 seconds and returns zeroed 24 kHz PCM. The duration is the word count divided by 2.5, at least one second.
- `MockTTSSegmentResult` has the same fields as the real `TTSSegmentResult` and `success` defaults to True.
- `MockTTSClient` calls `progress_callback` with the segment number, the total, the speaker and an estimated time left. It never calls `retry_callback`.

## Don't
- Don't expect the job's dry run to use these: `PodcastGeneratorJob` runs its own `_execute_dry_run` and imports no mock client. They are used by tests.
- Don't expect real segment text: the mock reads a `dialogue` attribute, and a `ScriptSegment` has `text`. It then sees empty text, so each segment is one second long.
