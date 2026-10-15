---
capability: deep-research-voice-interface
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.deep_research.cosa_interface.ask_confirmation@1a1a618d8f
  - cosa.agents.deep_research.cosa_interface.get_feedback@80d8cca785
  - cosa.agents.deep_research.cosa_interface.notify_progress@792a535c1d
  - cosa.agents.deep_research.cosa_interface.present_choices@e225a5ad4e
  - cosa.agents.deep_research.cosa_interface.reset_dispatch_context@906fca2640
---
# Deep research voice interface

`cosa_interface.py` wraps the shared `AgentNotificationDispatcher` so [[deep-research]] can notify and ask the user, by voice or the UI card, without blocking the event loop.

## What it does
- `notify_progress` sends a fire-and-forget message. It can carry an abstract, a job id, a queue name and a progress group id for in-place card updates.
- `ask_confirmation` asks a yes/no question and returns a bool. The default answer applies on timeout.
- `get_feedback` asks an open question and returns the transcribed answer, or `None`.
- `present_choices` sends multiple-choice questions and returns a dict with the answers keyed by header. It forwards an optional `priority`.
- Each call copies the module-level `SENDER_ID`, `TARGET_USER` and (for progress) `SESSION_NAME` into the dispatcher first.
- `set_dispatch_context` stores per-task sender, user and session in context variables and returns tokens. `reset_dispatch_context` restores the earlier values and skips missing keys.

## Don't
- Don't set the module globals from pool jobs. Concurrent jobs share them; use `set_dispatch_context`.
