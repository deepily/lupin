---
capability: generator-voice-bridges
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.podcast_generator.cosa_interface.ask_confirmation@1a1a618d8f
  - cosa.agents.podcast_generator.cosa_interface.get_feedback@80d8cca785
  - cosa.agents.podcast_generator.cosa_interface.notify_progress@792a535c1d
  - cosa.agents.podcast_generator.cosa_interface.present_choices@e225a5ad4e
  - cosa.agents.podcast_generator.voice_io.reconfigure@8265f4719a
  - cosa.agents.presentation_generator.cosa_interface.ask_confirmation@1a1a618d8f
  - cosa.agents.presentation_generator.cosa_interface.get_feedback@80d8cca785
  - cosa.agents.presentation_generator.cosa_interface.notify_progress@792a535c1d
  - cosa.agents.presentation_generator.cosa_interface.present_choices@e225a5ad4e
  - cosa.agents.presentation_generator.voice_io.reconfigure@8265f4719a
---
# Podcast and presentation voice bridges

Each generator has a thin `cosa_interface.py` and `voice_io.py`. They give the shared voice layer in [[agent-voice-io]] this agent's identity. The podcast pair serves [[podcast-generation]], the presentation pair [[presentation-generation]].

## What it does
- `notify_progress` sends a fire-and-forget message with a priority, an optional abstract, a session name, a job id and a progress group id.
- `ask_confirmation` asks a yes or no question and returns a bool. The defaults are "no" and 60 seconds.
- `get_feedback` asks an open question and returns the text, or `None` on timeout. The default wait is 300 seconds.
- `present_choices` sends multiple-choice questions and returns a dict with `answers` keyed by header. The default wait is 120 seconds, and a `priority` can be passed.
- Each function copies the module's `SENDER_ID` and `TARGET_USER` onto the shared dispatcher before the call. The agent type is `podcast.gen` or `presentation.gen`, so notifications carry that sender.
- `reconfigure()` in each `voice_io.py` calls the core `configure` with that agent's `cosa_interface`. The core module holds one global binding, so the last import wins.

## Invariants
- Both jobs call `reconfigure()` at the start of their execute step, not only at import, so notifications come from the right agent.
- The module-level `SENDER_ID` and `TARGET_USER` are mutable. The job sets them at run time, and one value is shared by every run in the process.
