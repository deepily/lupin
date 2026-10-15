---
capability: rest-routers-retired-submit-doors
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.bug_fix_expediter.submit_bug_fix@975d1c6694
  - cosa.rest.routers.claude_code_queue.submit_claude_code_to_queue@0cb72e8ab6
  - cosa.rest.routers.claude_code_queue.submit_claude_code_to_queue_alias@9004a9d7f8
  - cosa.rest.routers.deep_research_to_podcast.submit_research_to_podcast@ffc90b7783
  - cosa.rest.routers.deep_research_to_presentation.submit_research_to_presentation@7d82132d71
  - cosa.rest.routers.podcast_generator.submit_podcast_job@b2dc420798
  - cosa.rest.routers.presentation_generator.submit_presentation_job@7664b7d2ce
  - cosa.rest.routers.swe_team.submit_swe_team_task@0a62c4434c
  - cosa.rest.routers.test_suite.submit_test_suite@9903aa7ec9
  - cosa.rest.routers.mock_job.submit_mock_job@19ac998d7b
---
# Retired submit doors

Ten tombstone handlers. Each one answers 410 Gone. Nine name `/api/v2/submit` as the replacement; `submit_podcast_job` names `/api/v2/ask`. The shared refusal is in [[retired-queue-doors]].

## What it does
- `submit_bug_fix` stands for `/api/bug-fix-expediter/submit`.
- `submit_claude_code_to_queue` and `submit_claude_code_to_queue_alias` stand for `/api/claude-code/submit` and `/api/claude-code/queue/submit`.
- `submit_research_to_podcast` and `submit_research_to_presentation` stand for the two `/api/deep-research-to-*/submit` paths.
- `submit_podcast_job`, `submit_presentation_job`, `submit_swe_team_task`, `submit_test_suite` and `submit_mock_job` stand for the `/submit` path of their feature.
- Each handler calls `gone( path )`, which raises `HTTPException( 410 )` with the replacement door and the `REMOVE BY` date.
- A caller moves to `POST /api/v2/submit` with the command as a string and its old fields as `args`. The podcast door's caller asks through `POST /api/v2/ask` instead.

## Don't
- Don't add an auth dependency to a tombstone. A stale client must see the 410, not a 401.
- Don't put work behind these paths again. They are marked `deprecated` and carry no body.

## Invariants
- None of the ten handlers returns normally.
