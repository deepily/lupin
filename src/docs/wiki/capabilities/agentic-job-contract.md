---
capability: agentic-job-contract
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.agentic_job_base.AgenticJobBase@028ecca7ff
  - cosa.agents.agentic_job_base.AgenticJobBase.__init__@c9e3ac2365
  - cosa.agents.agentic_job_base.AgenticJobBase.do_all@1a00149391
  - cosa.agents.agentic_job_base.AgenticJobBase.base_id@5c2da75c6e
  - cosa.agents.agentic_job_base.AgenticJobBase.request_cancel@e2d03f8429
  - cosa.agents.agentic_job_base.AgenticJobBase.is_cacheable@01b6dc970e
  - cosa.agents.agentic_job_base.AgenticJobBase.notify_progress@b170b03671
  - cosa.agents.deep_research.job.DeepResearchJob.do_all@b9c361cc76
  - cosa.agents.claude_code.job.ClaudeCodeJob@1b092e0e63
---
# Agentic job contract

`AgenticJobBase` is the base class of every long-running queue job: it carries the fields the queue reads and the lifecycle a job fills in. [[cj-flow-queue]] owns the queue that runs these jobs in the agentic pool; this page is what a job class must provide.

## What a subclass provides
- Two class attributes: `JOB_TYPE` (for example `"deep_research"`) and `JOB_PREFIX` (`"dr"`). The id is `{prefix}-{8 hex}`.
- A `last_question_asked` property, `do_all()` and `async _execute()`. All three are abstract, so a class without them cannot be instantiated.
- `do_all()` is what the queue calls. `DeepResearchJob.do_all` shows the shape: set `RUNNING` and `started_at`, run `asyncio.run( self._execute() )`, then end in `CANCELLED` or `COMPLETED` and return the conversational answer. On an exception it sets `FAILED` and re-raises, so the pool's `Future` carries the error.
- Thirteen production classes subclass it (grep of `src` outside tests at `08509073d`): `ClaudeCodeJob`, `DeepResearchJob`, `PodcastGeneratorJob`, `PresentationGeneratorJob`, `DeepResearchToPodcastJob`, `DeepResearchToPresentationJob`, `BugFixExpediterJob`, `TestFixExpediterJob`, `TestSuiteJob`, `SweTeamJob`, `HeartbeatPokerJob`, `ArbiterConsumerJob` and `MockAgenticJob`.

## What the base gives
- Queue fields: `id_hash`, `user_id`, `session_id`, `push_counter`, `scheduled_at`, `monopolize`, `state` (a `JobState`), `result`, `artifacts`, `answer_conversational`.
- `notify_progress` and `notify_completion` send through the shared [[agent-voice-io]] module, tagged with the job's id so they land on its job card. They never raise.
- `request_cancel()` sets `_cancel_requested` and, when the job stored an orchestrator, its `_stop_requested`. Stopping is cooperative: `_execute` must poll the flag.

## Invariants
- `is_cacheable` is always `False` and `is_cache_hit` is `False`: an agentic job is never replayed from a snapshot.
- The queue may rewrite `id_hash` to `{base}::{user_id}`. Build sender ids from `base_id`, which strips the suffix.
- `brake_terminal_claimed` is written by `RunningFifoQueue`, never by a job. `routing_command` and `original_args` are set after construction, by `agentic_job_factory` (`_finish`). `spawned_by_id_hash` is also a constructor argument; the factory stamps it only when truthy, and `v2/executor.py` stamps it on a job from the trace's `parent_id_hash`.

## How to extend
- Copy the closest member's `__init__`, call `super().__init__` with the user, email and session, and set the two attributes. A job submitted by command also needs a `_build_*` function and an entry in `_UNWRAPPED_JOB_BUILDERS` (`JOB_BUILDERS` wraps it) in `cosa.rest.agentic_job_factory`, and an entry in `JOB_ARG_CONTRACTS` (`runtime_argument_expeditor/agent_registry.py`), from which `cosa.rest.v2.registry` derives `JOB_COMMANDS`; `test_1b2` compares the key sets of `JOB_BUILDERS` and `JOB_COMMANDS` and fails on a command in only one, but it cannot see a `_build_*` function that was never added to `_UNWRAPPED_JOB_BUILDERS`. `HeartbeatPokerJob` and `ArbiterConsumerJob` are not built from a command.

## Don't
- Don't override `is_cacheable`, and don't write `brake_terminal_claimed`.
- Don't use `id_hash` where a sender id is built; use `base_id`. Don't ignore `_cancel_requested` in a long `_execute`; the base cannot stop it.
