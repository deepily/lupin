---
capability: rest-routers-mode-and-client-config
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.cc_transcript.get_cc_transcript_roster@fceea4c65a
  - cosa.rest.routers.mode.ModeSetRequest@43e172d201
  - cosa.rest.routers.mode.ModeResponse@9d285cafd1
  - cosa.rest.routers.mode.ModeChangeResponse@7ba1891bed
  - cosa.rest.routers.mode.ModeInfo@4762ac61e6
  - cosa.rest.routers.mode.AvailableModesResponse@f38cd4620b
  - cosa.rest.routers.mode.get_todo_queue@9bc801466a
  - cosa.rest.routers.mode.get_available_modes@71a3847364
  - cosa.rest.routers.mode.get_mode@4de6ebde6f
  - cosa.rest.routers.mode.clear_mode@58cbebc925
  - cosa.rest.routers.multiplexer_config.MultiplexerConfigResponse@4c261c4e88
---
# Mode, multiplexer config and transcript roster routes

Three small readers and writers: the user's agent mode (`/api/mode`), the multiplexer front-end tuning values and the admin roster for the Claude Code transcript console. See [[session-transcript-console]].

## What it does
- `get_available_modes` (`GET /api/mode/available`) lists the selectable modes as `AvailableModesResponse`, each a `ModeInfo` (`key`, `display_name`, `description`). The mode routes need a signed-in user.
- `get_mode` (`GET /api/mode/current`) returns `ModeResponse` for the signed-in user, with `mode` null and `is_system_mode` true when none is set.
- `clear_mode` (`DELETE /api/mode/current`) returns the user to system mode and answers `ModeChangeResponse` with the previous mode.
- `ModeSetRequest` is the body of `POST /api/mode/current`, and `null` means system mode. A bad key answers 400.
- `get_todo_queue` hands the todo queue from the main module to the mode routes.
- `get_multiplexer_config` returns `MultiplexerConfigResponse`: `multiplexer_max_meta_display_bytes` (default 256000) and `tts_preview_fraction` (default 0.25). It needs no sign-in (`GET /api/multiplexer/config`).
- `get_cc_transcript_roster` (`GET /api/cc-transcript-roster`) is admin only. It returns `{ status, seats, session_count }`, each seat with `session_id`, `project`, `last_ts` and `transcript_watchable`.

## Don't
- Don't read an empty roster as a quiet fleet. `status: "unreachable"` means the arbiter did not answer.

## Invariants
- A mode is stored by the user's `uid`, not the email.
