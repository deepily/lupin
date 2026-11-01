---
capability: task-approve-link
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.task_approve_link.approve_link_line@3cc3b3a862
  - src.lupin_app.static.js.multiplexer.render.approveLink.approveRowId@a89b50efaa
  - src.lupin_app.static.js.multiplexer.render.approveLink.handleApproveLinkClick@e1dc0cb8f4
---
# One-click approve link

A manager who asks Rick to approve held rows writes each as a card bullet with an approve link. A click on the link sends the approve move in place, and nothing else opens.

## Writing the line
- `approve_link_line` returns `- <title> [✅ approve](/app/tasks/approve?row=<id>)`. It is the one writer of that line, and the MCP verb `task_approve_line` calls it ([[mcp-task-store-impls]]).
- It takes only a full lowercase hyphenated UUID. Short, braced and unhyphenated ids raise `ValueError`, and a non-string raises `TypeError`.
- The title has its whitespace runs, newlines included, folded to single spaces. A blank title raises `ValueError`. `[` and `]` are backslash-escaped so a title cannot form a link of its own.

## Claiming the click
- `approveRowId` returns the row id an href names, or null. It accepts the relative path or a loopback origin, and a short or malformed id is null, so nothing is sent for it.
- `handleApproveLinkClick` returns true when it claimed the click. It stops the browser following the link, then sends the move through `HoldingAreaStore.transitionTask( id, "queued" )`.
- The holding-area store always posts. The task-list store sends nothing for a row missing from its cache, which would have shown "Approved ✓" for a request never made.
- A second click while a request is out sends nothing. On success the link becomes "Approved ✓"; on a refusal or a pending answer it becomes the server's message, word for word.
- The reading pane offers a click to this handler before its doc-link branch ([[web-client-render-transcript-and-reading]]), and `bootMultiplexer` supplies the sender ([[web-client-transport-and-auth]]). The older page does the same in `NotificationsUI` ([[web-client-notifications-script]]).
- The link's landing page, for a browser that follows it, is `page_tasks_approve` ([[rest-routers-page-shells-and-stats]]). Opening it changes nothing.

## Don't
- Don't type the link by hand. Take the line from `task_approve_line`.
- Don't send the move through `TaskListStore.transitionTask` from a link handler.
