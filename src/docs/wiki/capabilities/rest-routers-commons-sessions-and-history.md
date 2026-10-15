---
capability: rest-routers-commons-sessions-and-history
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.commons.get_active_sessions@64c093d240
  - cosa.rest.routers.commons.project_session_response@fad8f23c7b
  - cosa.rest.routers.commons.filter_and_project_sessions@cc499b5280
  - cosa.rest.routers.commons.get_broadcast_history@2fdef003bf
  - cosa.rest.routers.commons.execute_broadcast_history@56a0cbe71f
  - cosa.rest.routers.commons.RecipientResolutionError@e4ee8ae6e9
---
# Commons sessions and history

The read side of `routers/commons.py`: who a broadcast would reach and the recent traffic list. Both routes need an API key or a JWT. See [[rest-routers-commons-broadcast]] and [[commons-and-dm]].

## What it does
- `get_active_sessions` answers `GET /api/commons/active-sessions` with the caller's live seats, each with persona name, icon and colour.
- `project_session_response` builds one such row: `session_id`, `sender_id`, `persona_name`, `persona_icon`, `persona_color`, `last_seen_iso` and `speakerphone_on`. It never exposes a file path.
- `filter_and_project_sessions` returns `( included, filtered_out )`. A seat is dropped when its bridge is unreadable, owned by another user, older than the threshold or vanished. It also drops the named originator when `include_originator` is false. Both routes pass no originator, so that drop never fires. Each drop carries its reason, but only the broadcast reply shows those reasons: `get_active_sessions` discards `filtered_out`, and `get_broadcast_history` has none.
- `get_broadcast_history` answers `GET /api/commons/broadcast-history` with `since`, `hours` and `limit` (default 200). If the INI flag `commons traffic visibility enabled` is false it answers `disabled: true` with no entries.
- `execute_broadcast_history` merges every topic except the excluded ones. The default exclusions are `presence` and `system-events`. It keeps entries tied to the caller and sorts newest first. It collapses repeated broadcast and ack rows, then caps at the smaller of `limit` and the configured maximum.
- `RecipientResolutionError` is the 422 body for a direct message whose recipient cannot be found. It lists the tries made, the live candidates and a suggested next step.

## Don't
- Don't read `next_cursor`. History is not paged, so it is always `None`.
- Don't treat a missing `owner_user_id` on a seat as a refusal. Such seats pass.

## Invariants
- The session list and the history both read the filesystem off the event loop.
