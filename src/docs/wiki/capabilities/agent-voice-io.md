---
capability: agent-voice-io
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.utils.voice_io.configure@d2624f0109
  - cosa.agents.utils.voice_io.notify@137826045d
  - cosa.agents.utils.voice_io.ask_yes_no@9c640a4cee
  - cosa.agents.utils.voice_io.present_choices@b1c28fbb38
  - cosa.agents.utils.voice_io.read_gate_answer@c775d66871
  - cosa.agents.utils.voice_io.VoiceGateNoDefaultError@8a7e015aa2
  - cosa.agents.utils.agent_notification_dispatcher.AgentNotificationDispatcher@4453d24bc5
  - cosa.agents.deep_research.cosa_interface.set_dispatch_context@fb2623d695
  - cosa.agents.deep_research.voice_io.reconfigure@8265f4719a
  - cosa.agents.utils.sender_id.build_sender_id@e3f42ed236
  - cosa.agents.utils.sync_notify.notify@71446723de
---
# Agent voice I/O

How a job tells the user something or asks a question: by voice when a notification path is configured, by console text when not. Agent jobs call `cosa.agents.utils.voice_io`; [[agentic-job-contract]] describes the jobs.

## What it does
- `notify` announces progress, `ask_yes_no` asks for a yes or no, `present_choices` asks a multiple-choice question and returns a dict, `choose`, `select_themes` and `select_topics` return a bare label or list.
- `configure( cosa_interface )` binds the module to one agent's `cosa_interface`, which must provide `notify_progress`, `ask_confirmation`, `get_feedback` and `present_choices`.
- `AgentNotificationDispatcher` is what each `cosa_interface` delegates to: it builds the sender id (`{agent}@{project}.deepily.ai[#suffix]`, from `build_sender_id`) and sends from a worker thread. `sync_notify.notify` is the fire-and-forget REST call for the synchronous proxy agents, which have no event loop.

## When nobody can answer
- On a run with no terminal, when voice is unavailable or the dispatch raises, `ask_yes_no` returns the caller's `unattended_default`, and raises `VoiceGateNoDefaultError` if none was given. At a terminal `default` is only what the prompt offers; on the dispatched path it is also sent on as the notification's `response_default`, so the two are not fully separate.
- One path bypasses that: `AgentNotificationDispatcher.ask_confirmation` swallows an unexpected error and returns `default == "yes"` (bug row 6734ff14). An offline user does not raise: the server streams the `response_default` straight back (exit code 0, `default_used`), and `ask_confirmation` returns it as the answer. A timeout (exit code 2), another non-zero code, a validation error or a connection error is raised as `VoiceGateTimeoutError`.
- `read_gate_answer` returns the answer under a header. A missing header raises `VoiceGateNoDefaultError` unless the caller passed an `unattended_default`, which is then returned; a default used is logged as a warning.

## Invariants
- One module-level interface binding serves the whole process, so the last `configure()` wins. Each agent's `voice_io.reconfigure()` (see deep_research's) re-asserts its own binding; call it at the start of a job.
- Inside the agentic pool, set the sender, user and session name with the agent's `set_dispatch_context()` (ContextVars). Writing the module-level `SENDER_ID` or `TARGET_USER` leaks one job's identity onto a concurrent job's notifications.
- `notify` never raises: a failed dispatch falls back to `print`.

## How to extend
- A new agent adds a `cosa_interface.py` that wraps an `AgentNotificationDispatcher( agent_type=... )` and a `voice_io.py` that calls `configure` and re-exports the core functions. Copy deep_research's pair.

## Don't
- Don't answer a gate with `options[0]` or a hard-coded fallback; pass `unattended_default` or `response_default` so the choice is on the record. Don't import `cosa.agents.test_fix_expediter` from inside a gate: that package's `__init__` rebinds the interface to swe_team's, which has no `present_choices`.
