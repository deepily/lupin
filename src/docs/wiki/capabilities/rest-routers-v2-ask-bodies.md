---
capability: rest-routers-v2-ask-bodies
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.v2_ask.AskRequest@b89f692c16
  - cosa.rest.routers.v2_ask.SubmitRequest@e655ec54f9
  - cosa.rest.routers.v2_ask.ResumeRequest@f73f6fa08b
  - cosa.rest.routers.v2_ask.AskResponse@88be2ffdc6
  - cosa.rest.routers.v2_ask.AgentOption@988f30be20
  - cosa.rest.routers.v2_ask.AutoRouteOption@5bbdc7a1a6
  - cosa.rest.routers.v2_ask.AgentsResponse@3d1c963c77
  - cosa.rest.routers.v2_ask.TranscribeTrace@053fc11d10
  - cosa.rest.routers.v2_ask.TranscribeResponse@7aaf90beb3
  - cosa.rest.routers.v2_ask.ResumeJobRequest@9a02713c1e
  - cosa.rest.routers.v2_ask.ResumeJobResponse@d8623c57fe
---
# v2 ask routes: request and response bodies

The typed bodies of the `/api/v2/*` doors on [[rest-routers-v2-ask-doors]]. The flow behind them is on [[v2-ask-flow]].

## What it does
- `AskRequest`: `question` (1 to 4000 characters), `websocket_id`, `speak` (default true), `interactive` (default true) and `parent_id_hash`. When `interactive` is false a missing argument returns `needs_input` instead of parking.
- `SubmitRequest`: `command` (required, up to 200 characters) and `args` carry work already decided, so no routing or extraction runs. `scheduled_at`, `monopolize` and `parent_id_hash` are queue directives, so they sit outside `args`.
- `ResumeRequest`: `pending_id` from an earlier `needs_input` reply and the human's `answer`.
- `AskResponse` is the one result shape for ask, submit and resume. `path` is replay, agent, needs_input or receptionist, `status` is done, waiting, parked, needs_input, expired or failed. It also carries `args_missing`, `pending_id`, `job_id`, `cache_hit`, `timings_ms`, `trace_id` and `queue_position`.
- `AgentsResponse` holds an `AutoRouteOption`, the "let the router decide" entry, and a list of `AgentOption`, one per registry command. Each has `display_name`, `label`, `speakable`, `user_initiable`, `required_args` and `arg_questions`.
- `TranscribeResponse` is `transcription` plus a `TranscribeTrace` of `stt_ms` and `upload_bytes`.
- `ResumeJobRequest` takes `resume_from` plus optional lead and worker model overrides and a `thinking_effort` of low, medium, high, xhigh or max. `ResumeJobResponse` status is `resumed` or `ambiguous`; it carries the new `resumed_job_id` and the phase it restarts from.

## Don't
- Don't put `scheduled_at` or `monopolize` inside `args`. `args` is checked against the command's argument contract, and no contract names them.
- Don't read `queue_position` as live. It is the queue size at submit time.

## Invariants
- Identity comes from the token, never from these bodies.
