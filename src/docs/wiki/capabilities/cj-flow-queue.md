---
capability: cj-flow-queue
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.running_fifo_queue.RunningFifoQueue@57f3de9795
  - cosa.rest.running_fifo_queue.RunningFifoQueue.get_pool_status@3a08a734df
  - cosa.rest.queue_consumer.start_todo_producer_run_consumer_thread@f6dc7ec19a
  - cosa.rest.queue_protocol.QueueableJob@92f93edba8
  - cosa.rest.job_state.JobState@516480b31e
  - cosa.rest.job_state.validate_transition@e52a308c3e
  - cosa.rest.job_persistence.persist_job_completed_from_metadata@e3834ece8e
  - cosa.rest.job_persistence.mark_interrupted_jobs@dbe7ae3549
  - cosa.rest.dead_queue_watchdog.DeadQueueWatchdog@58bfca263c
---
# CJ Flow queue

The queues every job passes through: todo, running, done and dead. `TodoFifoQueue` takes jobs in and routes them; a consumer thread hands them to `RunningFifoQueue`, which runs them and files each in done or dead. `agentic_job_base` is owned by [[agentic-job-contract]]; [[v2-ask-flow]] is the door most jobs arrive by.

## What it does
- `RunningFifoQueue._process_job` branches on type. An `AgenticJobBase` is submitted to a thread pool and the consumer returns at once. An `AgentBase` or a `SolutionSnapshot` runs inline on the consumer thread, so the pool never blocks it.
- The pool size is the INI key `cj flow max concurrent agentic jobs`: 1 when there is no config. Resolved through `ConfigurationManager` on 2026-10-07, it is 3 in `[Lupin: Production]`, `[Lupin: Development]` and `[Lupin: Testing]` (Testing sets none and inherits Development) and 1 in `[Lupin: Baseline]`. Re-read the INI before relying on it.
- A monopolize job runs on its own single-worker executor, not the shared pool. It is left out of `inflight_agentic_jobs` and shown as `monopolize_inflight` and `monopolize_id`. While one holds the pool and monopolize is enabled, the consumer defers other intake. It admits only that job's own child jobs, which run on the shared pool beside it. At most one monopolizer runs at a time; a child that itself monopolizes is deferred like any other job.
- `JobState` is the one lifecycle enum, with a fixed transition table: pending, queued, scheduled, paused, running, completed, failed, interrupted, cancelled and stalled. `stalled` is the only resumable state.
- `job_persistence` writes agentic jobs to Postgres at each step. At startup `mark_interrupted_jobs` marks every job that cannot come back as `interrupted`, and `restore_pending_jobs` re-enqueues the rest (future-scheduled, downtime catch-up and immediate) through the v2 `AskFlow`.
- `init_watchdogs` initializes both watchdogs. `DeadQueueWatchdog` evaluates a dead-queue push for an automatic bug-fix run. `TestSuiteCompletionWatchdog` does the same for a failed test suite on a done-queue push, and `test fix expediter auto fix enabled` is `false` in the INI.

## Invariants
- `completed`, `failed`, `cancelled` and `interrupted` have no way out. Check a move with `job_state.validate_transition`.
- `_on_agentic_complete` removes the job from `_agentic_futures` before it moves the job to done or dead. The ghost-job sweeper reads "future done and still tracked" as "never transitioned", so reversing the order would dead-letter a finished job.
- The ghost-job sweeper runs every `cj flow ghost job sweep interval seconds` (30 in the INI) and dead-letters those jobs.
- The running queue removes a finished job with `delete_by_id_hash`, never by popping the head. Pool callbacks finish in any order, so the head is not the job you mean.
- `get_pool_status` describes the pool and not the whole server. Its counts leave out inline work and the todo queue, so they do not show whether a server is idle.
- Every `persist_*` function is fire-and-forget: it logs a failure and never stops the queue. Persistence covers agentic jobs only.

## How to extend
- Implement the `QueueableJob` protocol (`do_all`, `code_ran_to_completion`, `formatter_ran_to_completion` and the unified attributes). `is_queueable_job` checks it.
- Make a long-running job an `AgenticJobBase` subclass so it rides the pool; see [[bounded-claude-code-jobs]]. The retired submission doors are in [[retired-queue-doors]].
