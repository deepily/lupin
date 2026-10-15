---
capability: rest-data-v2-execution
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.v2.executor.Executor@e26eb9c73e
  - cosa.rest.v2.executor.InlineExecutor@177640a44d
  - cosa.rest.v2.executor.QueuedExecutor@6190d45bca
  - cosa.rest.v2.executor.Outcome@9d66c5eefa
  - cosa.rest.v2.executor.Work@08666d1ed4
  - cosa.rest.v2.flow.AskFlow@0c61303bd8
  - cosa.rest.v2.pending.PendingEntry@c9cdc88763
  - cosa.rest.v2.refusal.SubmitRefused@8a214915b8
---
# V2 execution

The classes that run a v2 request once the flow has decided what it is. `AskFlow` makes the decision and is described in [[v2-ask-flow]]. This page covers what it hands work to, what comes back, and how a parked or refused request is represented.

## What it does
- `AskFlow( cache, router, expeditor, executor, pending, *, crud_enabled, ... )` takes every collaborator by injection. `crud_enabled` has no default. A `writeback_enabled` flow whose cache lacks `snapshot_from_result` or `write_back` raises `ValueError` at construction.
- `Work` is a frozen record of one unit: `kind` (`replay`, `agent` or `receptionist`), the `job`, the requester's `user_id`, `user_email` and `session_id`, and `snapshotable`.
- `Executor` is a protocol with one method, `submit( work, trace )`, that returns an `Outcome`.
- `InlineExecutor` runs on the calling thread. A replay copies the cached snapshot for the current user first, so the shared cached row is never changed. An agent runs through `do_all()`.
- `QueuedExecutor` stamps the requester's id and email on the job, scopes its id, pushes it to the todo queue and answers `waiting`. `queue_position` is the queue size right after the push. It is not kept current. A queue that refuses the push gives `failed`.
- `Outcome.status` is `done`, `waiting` or `failed`. A done agent also carries `code`, `code_example` and `code_returns`, so a write-back can persist a replayable row. They are `None` when the agent ran no prompt.
- `PendingEntry` is one parked request, held by `PendingRequests`. `claim` moves its `status` from `pending` to `answering`, and `release_turn` sets it back to `pending`. `set_status` writes `running`, then `done` or `failed`. An entry past its time to live is deleted by `get` or `sweep`; `expired` is never written.
- `SubmitRefused( route_reason, message, details=None )` is what a job builder raises when it declines to build. The flow reports it as a `failed` result carrying that reason, the message as `error` and the details as `submit_details`.

## Don't
- Don't expect a replay or agent error to raise out of an executor. Both catch it and return `failed`, so the flow can degrade to the receptionist.
- Don't treat `waiting` as parked. A waiting job is in the queue; a parked request is waiting for a person's answer.
- Don't build `QueuedExecutor` without the todo queue. It raises `ValueError` at construction.

## Invariants
- An unrecognised `work.kind` makes `InlineExecutor` raise `ValueError`. That is a programming error and is not turned into `failed`.
- A queue size that cannot be read leaves `queue_position` as `None`. The job still counts as queued.
- An empty `user_id` or `user_email` on `Work` leaves the job's own value in place and never blanks it.
- A write-back needs a `done` outcome that is snapshotable, and code unless the class is codeless. A `waiting` job has no answer to cache.
