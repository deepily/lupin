---
capability: task-approve-p0-link
pins:
  - cosa.rest.task_priority_firewall.refusal_for_promote_p0
---
# One-click promote-to-P0 link

A third link on a held-row card admits the row to queued at P0 in one click. The single-row approve link is in [[task-approve-link]].

## Writing the line
- `approve_link_line( row_id, title, with_p0=True )` puts `[P0 ⏫](/app/tasks/approve?row=<id>&priority=P0)` between the approve link and the 📋 link.
- The MCP verb `task_approve_line( task_id, with_p0=True )` calls it ([[mcp-task-store-impls]]). Without `with_p0` the line is unchanged.

## Claiming the click
- `handleApproveP0LinkClick` sends the approve move plus `promote_priority: "P0"`. The older page has `_handleApproveP0LinkClick`.
- Success reads "approved at P0 ✅" in place. A refusal reads the server's words.
- `approveP0RowId` and `approveRowId` each return null for the other's href, so a click has one handler.
- The landing page takes `&priority=P0` too. Its one button reads "Approve at P0".

## The server decides
- `transition_task` calls `refusal_for_promote_p0` before every other policy gate.
- It passes only when `caller_is_operator( account_email )` is true: a validated login mapped to the operator by `task approval approver accounts`.
- The move must be `not_approved` to `queued` with the value `P0`.
- An API key, another approver's login, another move or another value gets a 403, and the row is unchanged. The typed `actor` confers nothing.
- The priority change and the admission are one store event. Its reason reads `promoted to P0 (was P1) by the operator login <persona>`.

## Don't
- Don't type the link by hand. Take it from `task_approve_line`.
