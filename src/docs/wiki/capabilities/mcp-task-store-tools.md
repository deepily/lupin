---
capability: mcp-task-store-tools
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_mcp.task_store_tools.task_store_request@ea2417cc5d
  - lupin_mcp.task_store_tools.task_transition_impl@ddb8c478ae
  - lupin_mcp.task_store_tools.task_promotion_status_impl@cf20b89578
  - lupin_mcp.task_store_tools.task_edit_impl@a2b53fe29b
  - lupin_mcp.cosa_voice_mcp.task_transition@7c686e048b
  - lupin_mcp.cosa_voice_mcp.task_reassign@51ee36ffb6
---
# MCP task-store tools

Eleven MCP tools let a session read and write the task store over HTTP. The tools live in `cosa_voice_mcp.py`; `task_store_tools.py` holds the transport. [[task-store]] owns the rules.

## What it does
- Write tools: `task_create`, `task_transition`, `task_correlate`, `task_reassign`, `task_amend`, `task_request`, `task_ask_unpark`, `task_edit`. Read tools: `task_query`, `task_get`, `task_promotion_status`.
- Every call goes through `task_store_request` to `/api/tasks/...` with the outbound `X-API-Key`. A 2xx body comes back unchanged.
- `session_spawner.py` also calls `task_transition_impl` and `task_reassign_impl` directly, bypassing the tool layer.

## Rules it enforces
- Callers cannot name `created_by` or `actor`. The verb stamps it from the session persona and id, so a session cannot write as another.
- The eight write tools refuse with `borrowed_identity` when the session id was guessed from the working directory. Read tools do not check.
- Status rules, receipts and blocked fields are not checked here; the server's 422 `errors` list comes back verbatim.
- `task_reassign` returns `empty_reason` on a blank reason, and sends no `status`. `accountable_manager` is sent only when `new_manager` is given.
- `task_edit` returns `empty_updates` on an empty dict, and `owner_field_refused` for owner keys before any request. Use `task_reassign` for owners.
- `task_create` leaves `status` out of the request unless you name one, so the server can apply its own default.

## Failure shapes
- No readable key gives `missing_auth_header`. A connection failure or connect timeout gives `server_unreachable`.
- A read timeout gives `server_read_timeout` with `outcome_indeterminate`. The write may have landed; do not report it as failed.
- The timeout is 10 seconds each for connect and for read.

## Promotion wait
- `task_transition` passes `asynchronous=True` by default. If the server answers `awaiting_human_approval` with a ticket, the impl polls once a second, and a failed poll is skipped. It checks its 25-second budget at the top of each loop, so it can run a little over.
- Approved returns the item and event, or an error dict if no response body was stored. Any other ticket state returns an error dict. Budget exhausted returns the 202 body with a `ticket_id`; check it with `task_promotion_status`. See [[task-promotion-gate]].

## Query flags
- `task_query` sends only filters you set. `terse`, `include_terminal`, `unscoped_audit` go as `"true"` when set; `include_parked` sends `hide_parked=false`.
- The impl accepts `id_prefix`, but the registered tool does not expose it. To fetch one row by id, use `task_get`.
