---
capability: generator-voice-bridges
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.voice_io.reconfigure@8265f4719a
  - cosa.agents.presentation_generator.voice_io.reconfigure@8265f4719a
  - cosa.agents.utils.agent_notification_dispatcher.make_interface_functions@326b64aaa7
---
# Podcast and presentation voice bridges

Each generator has a thin `cosa_interface.py` and `voice_io.py`. They give the shared voice layer in [[agent-voice-io]] this agent's identity. The podcast pair serves [[podcast-generation]], the presentation pair [[presentation-generation]].

## What it does
- `notify_progress` sends a fire-and-forget message with a priority, an optional abstract, a session name, a job id, a queue name and a progress group id.
- `ask_confirmation` asks a yes or no question and returns a bool. The defaults are "no" and 60 seconds.
- `get_feedback` asks an open question and returns the text, or `None` on timeout. The default wait is 300 seconds.
- `present_choices` sends multiple-choice questions and returns a dict with `answers` keyed by header. The default wait is 120 seconds, and a `priority` can be passed.
- Each module builds the four with `make_interface_functions( globals(), ... )`. Each call copies the module's `SENDER_ID` and `TARGET_USER` onto the shared dispatcher first, and `notify_progress` also copies `SESSION_NAME`. The agent type is `podcast.gen` or `presentation.gen`, so notifications carry that sender.
- `reconfigure()` in each `voice_io.py` calls the core `configure` with that agent's `cosa_interface`. The core module holds one global binding, so the last import wins.

## Invariants
- Both jobs call `reconfigure()` at the start of their execute step, not only at import, so notifications come from the right agent.
- The module-level `SENDER_ID` and `TARGET_USER` are mutable. The job sets them at run time, and one value is shared by every run in the process.
