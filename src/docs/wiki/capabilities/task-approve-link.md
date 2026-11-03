---
capability: task-approve-link
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.task_approve_link.approve_link_line@8b4a3b7bc2
  - src.lupin_app.static.js.multiplexer.render.approveLink.approveRowId@43ca4df24a
  - src.lupin_app.static.js.multiplexer.render.approveLink.handleApproveLinkClick@e2236cc4c3
  - src.lupin_app.static.js.multiplexer.render.approveLink.handleViewLinkClick@f655d67e20
  - src.lupin_app.static.js.multiplexer.render.approveLink.markApproveLinks@7ac6282405
  - src.lupin_app.static.js.multiplexer.render.approveLink.observeApproveLinks@ea77a11f83
  - src.lupin_app.static.js.multiplexer.render.approveLink.rowIdAfter@2b88c2c70a
  - src.lupin_app.static.js.multiplexer.render.approveLink.taskOverlayText@54e6708b6d
  - src.lupin_app.static.js.multiplexer.render.approveLink.taskReaderFor@36fe42e48d
  - src.lupin_app.static.js.multiplexer.render.approveLink.viewRowId@9de180c26c
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
- The reading pane offers a click to this handler before its doc-link branch ([[web-client-render-transcript-and-reading]]). `bootMultiplexer` supplies the sender, the row reader and the tooltip ([[web-client-transport-and-auth]]). The older page does the same in `NotificationsUI` ([[web-client-notifications-script]]).
- A click on the 📋 link reads `GET /api/tasks/{id}` and shows the row the way the abstract 📋 shows text. That is the reading pane in horizontal layout, and the tooltip otherwise. No overlay and no tab opens. The multiplexer handler is `handleViewLinkClick`; the older page uses `_handleViewLinkClick`.
- The text is `taskOverlayText`: the title, then priority, owner and status, then the full body. A missing field reads as a dash, "unowned" or "(no body)". A failed read says "Could not read this ticket."
- `taskReaderFor( api )` builds the `TaskReader` on the api client, and any failure reads as null. `viewRowId` and `approveRowId` both find the id with `rowIdAfter`. The body overlay in `render/taskBodyOverlay.ts` is only for the task list's 📄 ([[web-client-render-task-row-controller]]).
- A card drawn after a reload is checked once per row id (`markApproveLinks`, `_markApproveLinks`), started by a mutation observer (`observeApproveLinks`). A held row keeps its live link.
- A row that left `not_approved` for a live or done status reads a disabled "approved ✅". A `dropped` or `wont_fix` row reads its status as plain text. A failed read leaves the live link.
- The link's landing page, for a browser that follows it, is `page_tasks_approve`, and the 📋 link's is `page_tasks_view` ([[rest-routers-page-shells-and-stats]]). Opening either changes nothing; the view page has no button.

## Don't
- Don't type the link by hand. Take it from `task_approve_line`, or from `task_approve_batch_line` for many rows ([[task-approve-batch-link]]). For the P0 link see [[task-approve-p0-link]].
- Don't send the move through `TaskListStore.transitionTask` from a link handler.
