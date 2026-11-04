---
capability: rest-routers-v2-ask-doors
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.v2_ask.v2_agents@974b4881e9
  - cosa.rest.routers.v2_ask.v2_ask@0ff6dcc307
  - cosa.rest.routers.v2_ask.ask_audio@fae13163c9
  - cosa.rest.routers.v2_ask.transcribe@06188e48a6
  - cosa.rest.routers.v2_ask.v2_resume@fbf2e43245
  - cosa.rest.routers.v2_ask.get_todo_queue@9bc801466a
  - cosa.rest.routers.v2_ask.v2_resume_job@aa056ff85f
---
# v2 ask routes: the doors

The handlers in `routers/v2_ask.py`. All need a signed-in user; bodies are on [[rest-routers-v2-ask-bodies]]. The flow behind them is on [[v2-ask-flow]].

## What it does
- `v2_agents` (`GET /api/v2/agents`) lists every registry command once, with the CRUD fork applied to labels, plus the auto-route option.
- `v2_ask` (`POST /api/v2/ask`) runs one question through the flow on a worker thread and returns an `AskResponse`. Agent, replay, router and extract failures degrade to the receptionist, not a 500.
- A `parent_id_hash` claim is kept for an admin, the test account, the parent job's owner or a holder of a valid suite token. Any other claim is dropped, and the flow trace records `parent_id_hash_dropped`. A claim that names the test-suite job holding the monopoly slot is refused with 403 `parent_id_hash_refused`. `POST /api/v2/submit` applies the same check.
- `ask_audio` (`POST /api/v2/ask-audio`) transcribes an uploaded file, then asks the text. The 200 body is NDJSON: a transcript line, then one ask or error line. The ask starts before the response, so a client that drops after line 1 does not cancel it.
- `transcribe` (`POST /api/v2/transcribe`) returns only the words and asks nothing. It needs no flow, so the `v2 flow enabled` gate does not apply.
- `v2_resume` (`POST /api/v2/resume`) answers a parked question. An unknown or expired `pending_id` returns status `expired`.
- `v2_resume_job` (`POST /api/v2/resume-job`) resumes a stalled job from its checkpoint and pushes the new job. A job id shape (not `tfe-`) goes straight to the factory, and a non-admin must own that job. Anything else goes through the resume resolver and may answer `ambiguous` with candidates.
- `get_todo_queue` hands the live todo queue to `v2_resume_job`.

## Don't
- Don't expect `v2_ask`, `v2_agents`, `ask_audio` or `v2_resume` while `v2 flow enabled` is off. They answer 503.
- Don't read the 404 from `v2_resume_job` as proof a job is missing. It also hides jobs the caller does not own.

## Invariants
- Uploaded audio is removed on every path. An empty transcript is 422, a GPU out-of-memory is 503 with `Retry-After: 5`.
