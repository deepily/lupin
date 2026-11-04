---
capability: rest-core-fifo-queue
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.fifo_queue.FifoQueue@a61ada1e1a
  - cosa.rest.job_state.assert_valid_transition@3b51d5f458
---
# FifoQueue and the job state matrix

`FifoQueue` is the base container behind the todo, running, done and dead queues; the pipeline around it is on [[cj-flow-queue]]. It keeps a list for order and a dict keyed by `id_hash` for lookup, behind one lock.

## FifoQueue
- `push( item )` appends and counts it, and raises `TypeError` for a non-`QueueableJob`. `get_push_counter` is the total ever pushed, and `clear` resets it to 0.
- `pop` and `head` return the first item or `None`. `pop_next_eligible( now, predicate )` takes the first job that is not `PAUSED`, whose `scheduled_at` is empty or past, and which passes `predicate`. Jobs it skips keep their place.
- An unparseable `scheduled_at` counts as immediate. A timezone-aware one is converted to naive local time before the comparison.
- `earliest_scheduled_at` is the soonest `scheduled_at` among non-paused jobs, or `None`. The consumer waits no longer than that, capped by its idle wake interval.
- `get_by_id_hash` raises `KeyError` when absent. `delete_by_id_hash` returns `False` when absent and `True` after deleting.
- `get_jobs_for_user`, `get_jobs_excluding_user` and `get_all_jobs` return raw jobs. They check no authorization.
- `has_changed` compares the size with the size at the last call, and updates it.

## Job state matrix
- `assert_valid_transition( from_state, to_state )` returns `None`, or raises `ValueError` naming both states.
- Allowed from pending: queued, scheduled, paused. From queued: running, paused, scheduled, cancelled, failed.
- From scheduled: queued, paused, cancelled. From paused: queued, scheduled, cancelled.
- From running: completed, failed, interrupted, stalled, cancelled. From stalled: running, cancelled.
- `completed`, `failed`, `cancelled` and `interrupted` are terminal: nothing leaves them.

## Don't
- Don't use `pop` to remove a known job; use `delete_by_id_hash`, because the head is not deterministic under pool callbacks.
