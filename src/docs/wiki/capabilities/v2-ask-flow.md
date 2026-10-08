---
capability: v2-ask-flow
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.v2.flow.AskFlow.ask@57c5527ac0
  - cosa.rest.v2.flow.AskFlow.submit@76e1b6886f
  - cosa.rest.v2.flow.AskFlow.resume@111474020a
  - cosa.rest.v2.registry.resolve@57c59b916b
  - cosa.rest.v2.registry.resolve_agentic@a8c9cfb999
  - cosa.rest.v2.executor.make_executor@0ac07563f3
  - cosa.rest.v2.pending.PendingRequests@5eace53fc7
  - cosa.rest.v2.near_match_guard.quantities_differ@b58fa386e0
  - cosa.rest.routers.v2_ask.v2_submit@72d9cfe688
  - cosa.rest.routers.v2_ask.vet_parent_id_hash@89e2ade028
---
# V2 ask flow

The v2 door onto CJ Flow: `AskFlow` takes a question, or a command that is already decided, and returns one result dict. The HTTP surface is `routers.v2_ask` (`/api/v2/ask`, `ask-audio`, `transcribe`, `submit`, `resume`, `resume-job`, and `GET /api/v2/agents`). Jobs it builds run in [[cj-flow-queue]]; the old submission doors are in [[retired-queue-doors]].

## What it does
- `ask` runs in this order: a fitness check on the question, then the router, then the cache, then arguments. The router comes before the cache, so the flow knows the command when it looks up. An agentic command leaves right after the router, for `_ask_agentic`. It skips the cache, still extracts its arguments, parks a missing one when the call is interactive, and then submits.
- A cache exact hit replays the stored answer. A near match at or above `similarity threshold confirmation` (90.0 by default) is checked in this order. A different quantity or an unservable row routes on. With `similarity confirmation enabled` false, it replays with no ask. Otherwise a non-interactive call is declined unasked, and an interactive call asks and replays only on a yes. The INI sets the key true in Development and false in Testing. A command with a CRUD factory skips the cache while `crud for dataframes agents enabled` is on.
- Missing arguments return the first question at once. An interactive call parks the request in `PendingRequests` and answers `parked`; `resume` fills the next argument from a second call. A non-interactive call answers `needs_input` and parks nothing.
- `submit` is the door beside `ask` for a command that is already named: no routing, no cache, no argument extraction. It never parks. `scheduled_at`, `monopolize` and `parent_id_hash` are queue directives, not agent arguments.
- `registry` is the one table from routing command to agent. `resolve` returns conversational commands and `resolve_agentic` the agentic ones.
- `make_executor` builds the executor named by `v2 executor`: `inline` runs on the calling thread, `queued` pushes to the todo queue and answers `waiting`, which counts as success. The code default is `inline`; `[Lupin: Baseline]` sets `queued`, and Production, Development and Testing resolve to `queued` through inheritance (resolved through `ConfigurationManager` on 2026-10-07).

## Invariants
- A failing agent, replay or argument extraction degrades to the receptionist with its own `route_reason`. A router reply that cannot be parsed lands in `unknown`, which degrades the same way. An error in the router call itself (the LLM call or a missing prompt file) is not caught. Neither is an error in the cache lookup. Both end as an HTTP 500. `ask-audio` and `transcribe` answer 500 with one fixed detail for an unexpected failure.
- `ask`, `ask-audio`, `submit`, `resume` and `GET /api/v2/agents` answer 503 while `v2 flow enabled` is false. `transcribe` and `resume-job` take no flow dependency, so the flag does not gate them. The code default is false, but `[Lupin: Baseline]` and `[Lupin: Development]` set it true, and Production and Testing inherit that.
- A cached row is served only if `answer_is_correct` is `True`. The one exception is an exact hit whose verdict is not `False`; a user's explicit no is never served.
- `quantities_differ` refuses a near match when either question contains a number and the ordered numbers and words differ. "Convert 10 miles to kilometers" once replayed the answer to "How many miles is 10 kilometers?" at a score of 93.4.
- An unknown or expired `pending_id` on `resume` answers `status='expired'`, `route_reason='pending_expired'`. Parked entries expire after `ttl_seconds` (3600 by default).
- `submit` raises `ValueError` unless exactly one of `command` and `job` is given.
- The doors `/api/v2/ask` and `/api/v2/submit` keep a caller's `parent_id_hash` only for an admin, the configured test account, a caller holding the per-run suite token (header `X-Lupin-Lineage-Token`, Development and Testing only, valid while that run holds the monopoly slot), or the owner of the parent job. Any other claim is dropped, logged and traced as `parent_id_hash_dropped`, and the request still runs without it, never as a 4xx.

## How to extend
- Add a command as one `AgentSpec` row in `cosa.rest.v2.registry`; do not add a branch to `AskFlow`.
- A job builder that declines on purpose raises `SubmitRefused`, so the reason reaches the caller as a failed result and not as a generic build error.
