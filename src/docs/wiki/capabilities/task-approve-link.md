---
capability: task-approve-link
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.task_approve_link.approve_link_line@3cc3b3a862
  - src.lupin_app.static.js.multiplexer.render.approveLink.approveRowId@a89b50efaa
  - src.lupin_app.static.js.multiplexer.render.approveLink.handleApproveLinkClick@e1dc0cb8f4
---
# One-click approve link

A manager who asks Rick to approve held rows writes each as a card bullet with an approve link and a 📋 view link. A click on the approve link sends the approve move in place; a click on 📋 shows the ticket in place. Nothing else opens. The view link used to be written 📄. Both clients find it by its `/app/tasks/view?row=` address, not its label. A card sent with 📄 still works.

## Writing the line
- `approve_link_line` returns `- <title> [approve ☐](/app/tasks/approve?row=<id>) [📋](/app/tasks/view?row=<id>)`. It is the one writer of that line, and the MCP verb `task_approve_line` calls it ([[mcp-task-store-impls]]).
- It takes only a full lowercase hyphenated UUID. Short, braced and unhyphenated ids raise `ValueError`, and a non-string raises `TypeError`.
- The title has its whitespace runs, newlines included, folded to single spaces. A blank title raises `ValueError`. `[` and `]` are backslash-escaped so a title cannot form a link of its own.

## Claiming the click
- `approveRowId` returns the row id an href names, or null. It accepts the relative path or a loopback origin, and a short or malformed id is null, so nothing is sent for it.
- `handleApproveLinkClick` returns true when it claimed the click. It stops the browser following the link, then sends the move through `HoldingAreaStore.transitionTask( id, "queued" )`.
- The holding-area store always posts. The task-list store sends nothing for a row missing from its cache, which would have shown "approved ✅" for a request never made.
- A second click while a request is out sends nothing. On success the link becomes a disabled "approved ✅"; on a refusal or a pending answer it becomes the server's message, word for word.
- The reading pane offers a click to this handler before its doc-link branch ([[web-client-render-transcript-and-reading]]), and `bootMultiplexer` supplies the sender ([[web-client-transport-and-auth]]). The older page does the same in `NotificationsUI` ([[web-client-notifications-script]]).
- A click on the 📋 link reads `GET /api/tasks/{id}` and opens the shared task-body overlay. The overlay shows the title, priority, owner, status and full body. The multiplexer handler is `handleViewLinkClick`; the older page uses `_handleViewLinkClick`.
- The overlay lives in `render/taskBodyOverlay.ts`, and the task list's 📄 opens the same one. A failed read says "Could not read this ticket."
- A card drawn after a reload is checked once per row id (`markApproveLinks`, `_markApproveLinks`), started by a mutation observer. A held row keeps its live link.
- A row that left `not_approved` for a live or done status reads a disabled "approved ✅". A `dropped` or `wont_fix` row reads its status as plain text. A failed read leaves the live link.
- The link's landing page, for a browser that follows it, is `page_tasks_approve`, and the 📋 link's is `page_tasks_view` ([[rest-routers-page-shells-and-stats]]). Opening either changes nothing; the view page has no button.

## Don't
- Don't type the link by hand. Take the line from `task_approve_line`.
- Don't send the move through `TaskListStore.transitionTask` from a link handler.
