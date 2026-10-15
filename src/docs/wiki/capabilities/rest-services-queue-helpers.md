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
- `UserJobTracker` is a thread-safe singleton index of user to job ids. Production code calls `register_scoped_job`, which returns `"{base_hash}::{user_id}"` and does not scope an already-scoped hash twice. `associate_job_with_user` is a lower-level update kept for test setup.
- `is_queueable_job( obj )` is true when an object has the attributes and methods of the `QueueableJob` protocol. It checks presence only, not behaviour.
- `emit_job_state_transition` validates a transition against the `JobState` matrix and emits `job_state_transition`. With a user id it goes to that user and to the watching admins; with none it goes to everyone. It persists a transition to Postgres only when `metadata[ "agent_type" ]` names an agentic job type, and only for some transitions. A websocket or persistence failure is logged, never raised.
- `compute_duration_seconds( started_at, completed_at )` takes ISO strings or datetimes and returns seconds, or `None` if either is empty or unparseable.
- `parse_salutations( transcription, salutations )` splits a leading run of salutations from the text and returns `( salutations, remaining )`.
- `TodoFifoQueue` holds todo items. Question routing in production goes through `AskFlow`. `push_job_agentic` submits an agentic job with an explicit routing command and no expeditor, and returns a dict with `message` and `job_id`. `push` emits the pending to todo transition.
- `get_routing_command( question, config_mgr, llm_factory )` asks the router LLM and returns `( command, args )`. If the XML does not parse it returns `( "unknown", "" )`.
- `query_llm_in_memory` runs a loaded model and returns the cleaned text. Generation stops on `</response>`, the end-of-sequence token or `max_new_tokens`, which defaults to 128. `StopOnTokens` stops generation when the end of the first batch row equals the stop token ids.

## Don't
- Don't call `TodoFifoQueue.push_job`. Production has no caller; the voice path is `AskFlow`, and a unit test fails if one is added.

## Invariants
- `job.user_id` is the owner of a job. `UserJobTracker` is only a lookup index.
