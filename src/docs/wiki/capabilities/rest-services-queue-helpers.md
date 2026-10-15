---
capability: rest-services-queue-helpers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.queue_auth.authorize_queue_filter@d4f4dcdaac
  - cosa.rest.queue_extensions.UserJobTracker@c79e4d3f25
  - cosa.rest.queue_protocol.is_queueable_job@2bf7fbaf53
  - cosa.rest.queue_util.emit_job_state_transition@ba7483f9c6
  - cosa.rest.running_fifo_queue.compute_duration_seconds@8803f27d89
  - cosa.rest.salutations.parse_salutations@3ab075cb2b
  - cosa.rest.todo_fifo_queue.TodoFifoQueue@12be5d9226
  - cosa.rest.todo_fifo_queue.get_routing_command@a8a02fc1fe
  - cosa.rest.util_llm_client.StopOnTokens@d0c8d6208b
  - cosa.rest.util_llm_client.query_llm_in_memory@7353ead10a
---
# Queue helpers and the todo queue

Small helpers around the job queues. The pipeline itself is in [[cj-flow-queue]]; the contract a job must meet is in [[agentic-job-contract]].

## What it does
- `authorize_queue_filter( current_user, filter_user_id )` returns the user filter a caller may use. `None` gives the caller's own uid. `"*"` and `"!self"` (returned as `"!<uid>"`) need an admin; another user's id also needs an admin. A refusal is HTTP 403.
- `UserJobTracker` is a thread-safe singleton index of user to job ids. `register_scoped_job` is the one write entry and returns `"{base_hash}::{user_id}"`; an already-scoped hash is not scoped twice.
- `is_queueable_job( obj )` is the runtime `QueueableJob` protocol check.
- `emit_job_state_transition` validates a transition against the `JobState` matrix and emits `job_state_transition` to the user, or to everyone when no user is given. For agentic jobs it also persists the transition to Postgres. A websocket or persistence failure is logged, never raised.
- `compute_duration_seconds( started_at, completed_at )` takes ISO strings or datetimes and returns seconds, or `None` if either is empty or unparseable.
- `parse_salutations( transcription, salutations )` splits a leading run of salutations from the text and returns `( salutations, remaining )`.
- `TodoFifoQueue` is the todo queue. `push_job_agentic` submits an agentic job with an explicit routing command and no expeditor, and returns a dict with `message` and `job_id`. `push` emits the pending to todo transition.
- `get_routing_command( question, config_mgr, llm_factory )` asks the router LLM and returns `( command, args )`. If the XML does not parse it returns `( "unknown", "" )`.
- `query_llm_in_memory` runs a loaded model and stops on `</response>`; `StopOnTokens` is its stopping criterion.

## Don't
- Don't call `TodoFifoQueue.push_job`. Production has no caller; the voice path is `AskFlow`, and a unit test fails if one is added.

## Invariants
- `job.user_id` is the owner of a job. `UserJobTracker` is only a lookup index.
