---
capability: task-approve-priority-link
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.task_priority_firewall.refusal_for_promote_priority@b03a59afc5
  - src.lupin_app.static.js.multiplexer.render.approveLink.approvePriorityLink@b9090ffbe4
  - src.lupin_app.static.js.multiplexer.render.approveLink.handleApprovePriorityLinkClick@7ba0308cfc
---
# One-click priority link

An optional third link on a held-row card admits the row to queued at a higher priority in one click. The single-row approve link is in [[task-approve-link]].

## Writing the line
- `approve_link_line( row_id, title, priority )` puts `[⏫ P0](/app/tasks/approve?row=<id>&priority=P0)` between the approve link and the 📋 link.
- The level is P0 to P5. With no priority the line is the two-link line, and admission keeps the row's own priority.
- The MCP verb `task_approve_line( task_id, priority )` calls it ([[mcp-task-store-impls]]). A level outside P0 to P5 returns `invalid_priority`.

## Claiming the click
- `handleApprovePriorityLinkClick` sends the approve move plus `promote_priority: "<level>"`. The older page has `_handleApprovePriorityLinkClick`.
- Success reads "approved at P0 ✅" in place. A refusal reads the server's words.
- `approvePriorityLink` and `approveRowId` each return null for the other's href, so a click has one handler.
- The landing page takes `&priority=<level>` too. Its one button reads "Approve at P0".

## The server decides
- `transition_task` calls `refusal_for_promote_priority` before every other policy gate.
- It passes only when `caller_is_operator( account_email )` is true: a validated login mapped to the operator by `task approval approver accounts`.
- The move must be `not_approved` to `queued`, and the level must raise the row. A lower or equal level is refused.
- An API key, another approver's login, another move or a bad level gets a 403, and the row is unchanged. The typed `actor` confers nothing.
- The priority change and the admission are one store event. Its reason reads `promoted to P0 (was P1) by the operator login <persona>`.

## Don't
- Don't type the link by hand. Take it from `task_approve_line`.
