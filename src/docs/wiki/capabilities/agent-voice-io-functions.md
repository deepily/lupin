---
capability: agent-voice-io-functions
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.utils.voice_io.set_cli_mode@b71a621301
  - cosa.agents.utils.voice_io.is_cli_mode@934e25ab77
  - cosa.agents.utils.voice_io.get_mode_description@9ec851ecd8
  - cosa.agents.utils.voice_io.is_voice_available@4283d7298d
  - cosa.agents.utils.voice_io.reset_voice_check@c627d0c341
  - cosa.agents.utils.voice_io.set_job_id@86afa97e5a
  - cosa.agents.utils.voice_io.clear_job_id@f597454c41
  - cosa.agents.utils.voice_io.get_input@85d0c7f16c
  - cosa.agents.utils.voice_io.choose@b322fdc845
  - cosa.agents.utils.voice_io.select_themes@c8e173a42a
  - cosa.agents.utils.voice_io.select_topics@cb0ef16c81
---
# Agent voice I/O functions

Agentic jobs ask the user questions through one module. It speaks and listens when voice is up. It falls back to the terminal when it is not. This page covers the mode switches and the question functions.

## What it does
- `set_cli_mode` forces terminal text even when voice is available. `is_cli_mode` is true when it is forced or no voice interface is configured.
- `is_voice_available` probes the voice service once and caches the answer. `reset_voice_check` clears the cache so the next call probes again.
- `get_mode_description` returns a short label, such as forced CLI mode, voice mode or voice unavailable.
- `set_job_id` makes later notifications carry that job id, so they reach the right job card. `clear_job_id` stops it, and a job should call it at the end.
- `get_input` asks an open question and returns the text, or `None` on a timeout, an error or an empty answer that is not allowed.
- `choose` asks a multiple-choice question and returns the chosen label. Options are strings or dicts with a label and description.
- `allow_custom` lets the user type another answer to `choose`.
- `select_themes` returns the chosen theme indices. `select_topics` returns the chosen topic indices, and can start with all topics selected.
- A cancel from `select_themes` or `select_topics` returns an empty list.

## Don't
- Don't expect an unattended gate to pick the first option. When no human answers, `choose`, `select_themes` and `select_topics` return the declared `response_default`, and raise when none was declared.
- Don't block on terminal input in a queue worker. `get_input` returns `None` there when the session is not interactive.
