---
capability: cosa-voice-mcp-server
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_mcp.cosa_voice_mcp.converse@e80eac9a7e
  - lupin_mcp.cosa_voice_mcp.ask_yes_no@9b3e0b6f3e
  - lupin_mcp.cosa_voice_mcp.ask_multiple_choice@7035439097
  - lupin_mcp.cosa_voice_mcp.request_persona@9bed1bb61e
---
# cosa-voice MCP server

`src/lupin_mcp/cosa_voice_mcp.py` is the FastMCP server (`mcp`) a Claude Code seat uses to speak to the user, ask blocking questions and read or change its own session state. It runs on the host as a stdio subprocess of the seat and talks to the Lupin server over HTTP.

## Tools covered here
- `notify` announces and returns at once; `converse`, `ask_yes_no`, `ask_multiple_choice` and `ask_open_ended_batch` block until the user answers or the timeout passes.
- `get_session_info` reads project, session id, sender id, server URL, speakerphone flag, voice persona and bridge metadata. `set_session_topic` writes the topic into the session bridge file and pushes it to the UI.
- `enable_speakerphone`, `disable_speakerphone` and `request_persona` change speakerphone and voice-persona state through the Lupin server. The two speakerphone verbs fall back to writing the bridge file when the server is unreachable, refuses the login or toggle, or no credentials are found; `request_persona` has no fallback. Their docstrings say to call them only on a user's instruction; the function bodies check nothing of the kind.
- Other families live in the same file. They have their own pages: commons and DM ([[mcp-commons-and-dm]]), spawn, dismiss and `self_respin` ([[mcp-session-spawn-and-reap]]), task store ([[mcp-task-store-tools]]), and reuse search ([[reuse-search-tools]]).

## How a call reaches the Lupin server
- `notify` goes through `notify_user_async` and the asking verbs through `notify_user_sync`. Both POST to `/api/notify` on the Lupin server; the sync client streams the reply as server-sent events.
- Each ask stamps an `idempotency_key` if it has none, so a re-POST of the same ask is de-duplicated by the server. `notify` stamps one before it sends.

## Offload decorator
- `_offloaded_tool` runs a blocking sync handler on a worker thread, so a long ask does not stop the subprocess serving other calls. It is applied to the four blocking ask verbs, `commons_ask_sync` and the four reuse tools; `notify` and the session verbs are not wrapped.

## Rules the bodies enforce
- **Spoken length.** `notify` and the four ask verbs call `_enforce_spoken_brevity` first. A spoken field over the configured cap (500 in the INI) raises `ValueError`, unless `override_size_limitation=True` or the enforce flag is off. The code default is on; the shipped INI sets it `False` in `[Lupin: Baseline]`.
- **Speakerphone on.** `notify` forces `suppress_ding=True`, strips fenced code blocks, and lifts a recognised lower priority to `high`. An unrecognised priority is left alone and returns `[validation error: ...]`.
- **Delivery failure.** If `notify` cannot send and the outbox is enabled, it spools the request and returns `Queued for durable retry (...)`. Otherwise it returns `Failed: ...`.
- **`ask_yes_no` returns a string.** A real answer comes back clean. Any non-answer (timeout, offline, error, validation failure) returns `[default used] ` plus the default, so a prefixed value is not a decision.
- **`converse` returns a string.** A substituted default carries the same prefix. A timeout returns `[timeout - using default] ...` or `[timeout - no response received]`, and other failures return `[error: <status>]`.
- **`ask_multiple_choice` returns a dict.** A non-empty `questions` list is required, and a bad `default` returns `{"error": ...}` before anything is sent. A real answer carries `default_used: False` and `answered: True`; an offline default arrives through the same path stamped `default_used: True, answered: False`. A timeout with `default` returns `{"answers": default, "default_used": True, "answered": False}`; without one it returns `{"error": "timeout - no response received", "timeout": True}`.
- **`request_persona`.** A blank name returns `status: "error"` without any HTTP call. HTTP 422 returns `not_in_pool`, 409 returns `occupied`, and there is no bridge-file fallback.

## When not to use it
- To send a message to a peer session use `dm_send` ([[mcp-commons-and-dm]]), not `notify`.
- For fleet work records use the task-store tools ([[mcp-task-store-tools]]).
- The delivery path behind `/api/notify` is [[notification-delivery]]; persona allocation is [[voice-persona-allocation]].
