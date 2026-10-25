---
capability: mcp-task-store-impls
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.task_store_tools.task_create_impl@0182da3c63
  - lupin_mcp.task_store_tools.task_correlate_impl@06e589af27
  - lupin_mcp.task_store_tools.task_reassign_impl@2ebeb3341d
  - lupin_mcp.task_store_tools.task_amend_impl@f52450e2dc
  - lupin_mcp.task_store_tools.task_request_impl@a994fc1d6f
  - lupin_mcp.task_store_tools.task_ask_unpark_impl@a7493a0e99
  - lupin_mcp.task_store_tools.task_get_impl@4c0524d2d4
  - lupin_mcp.task_store_tools.task_query_impl@6c4bbd9e7a
---
# Task-store tool implementations

Eight functions in `task_store_tools.py` carry the verbs [[mcp-task-store-tools]] does not pin. Each builds one request and hands it to `task_store_request`; the server decides every rule.

## Writes
- `task_create_impl` posts to `/api/tasks`. It canonicalizes `project` through the shared alias table, so a row written under a repo alias matches the owed-work query that reads it.
- It leaves `status` out of the body unless you name one. Where the holding area is on, a named live status is refused unless the row is top priority or the caller is the operator.
- `task_correlate_impl` re-keys an item so a successor session adopts inherited work instead of forking a duplicate. The server records the change as an event and refuses a finished item.
- `task_reassign_impl` patches the owner and the reason. It sends `accountable_manager` only when `new_manager` is given, and it never sends `status`.
- `task_amend_impl` appends a note to the item body and never overwrites. It is the one write verb a finished row still accepts; the server stamps that as a post-terminal addendum.
- `task_request_impl` asks the operator to admit or demote one row. The row does not move and the request has no expiry. `deletion_task_id` goes in the body only when given.
- `task_ask_unpark_impl` posts to `/api/tasks/{id}/unpark-ask` with only the actor. It returns the card id, expiry and whether the push reached the operator.
- After a yes, the manager sends the parked-to-queued transition with that card id as the approval receipt.

## Reads
- `task_get_impl` fetches one row by its full id and returns the whole row, body included. A missing row is an error dict, never an empty success.
- A filtered query that comes back empty does not prove a row is absent, so use this call to check one.
- `task_query_impl` drops every unset filter and canonicalizes `project`. It returns the server envelope unchanged: `count` is the page length and `has_more` says whether to keep paging.
- `blocked_by_persona` lists rows waiting on that persona, whoever owns them. `id_prefix` takes the short id form and counts as a scoping filter.
- Parked rows are hidden by default. Pass `include_parked`, or ask for `status="parked"`.
- `park_reason_stale` and `blocker_terminal` ride on every row, terse or full. Both are advisory and move nothing.
- Without `include_terminal`, an unscoped query also withholds the holding area and says how many rows it held back.
