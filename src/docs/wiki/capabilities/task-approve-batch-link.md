---
capability: task-approve-batch-link
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.task_approve_link.approve_batch_line@70b06baceb
  - cosa.rest.task_approve_link.parse_batch_row_ids@7d083d848c
  - lupin_mcp.cosa_voice_mcp.task_approve_batch_line@e290cde912
  - lupin_mcp.task_store_tools.task_approve_batch_line_impl@b9f218cfe4
  - src.lupin_app.static.js.shared.approve-link.applyBatch@6b37bc74e2
  - src.lupin_app.static.js.shared.approve-link.batchLinkOf@696bdcbd77
  - src.lupin_app.static.js.shared.approve-link.batchParams@ece0b947e1
  - src.lupin_app.static.js.shared.approve-link.batchViewIds@b3c139e8e8
  - src.lupin_app.static.js.shared.approve-link.handleBatchApproveLinkClick@9ca763714b
  - src.lupin_app.static.js.shared.approve-link.handleBatchViewLinkClick@85b248c7e4
  - src.lupin_app.static.js.shared.approve-link.parseBatchIds@5e6c5bd4c0
---
# One-click batch link

For more than one held row, a manager sends one batch line. One click then moves every listed row, so Rick never clicks row by row. The single-row link is in [[task-approve-link]].

## Writing the line
- `approve_batch_line( row_ids, move, reason )` returns `- <N> held rows [approve all N ☐](/app/tasks/approve?rows=<a>,<b>&move=queued) [📋](/app/tasks/view?rows=<a>,<b>)`.
- `move` is `queued` to approve or `dropped` to drop. A drop reads `[drop all N ☐]` and ends with `&move=dropped&reason=<percent-encoded>`.
- A drop needs a non-blank reason. An approve takes none.
- `parse_batch_row_ids` refuses an empty list, a short or malformed id, and a repeated id with `ValueError`.
- The MCP verb `task_approve_batch_line` calls `task_approve_batch_line_impl`, which asks the server nothing ([[mcp-task-store-impls]]). A bad batch comes back as `{ "error": "invalid_batch", "detail": ... }`.

## Claiming the click
- Both clients find the link by its address, not its label. A list that fails the rules above is claimed so the browser stays put, and nothing is sent.
- `parseBatchIds` and `batchParams` read the list. `batchLinkOf` and `batchViewIds` return the ids, the move and the reason. The older page calls these same functions through `window.LUPIN_APPROVE_LINK`; it keeps no copy.
- `applyBatch` sends one `HoldingAreaStore.transitionTask` per row, all together, under Rick's login with `user_direct`. A drop carries its reason.
- `handleBatchApproveLinkClick` replaces the link with `N of M applied` and one line per row. A second click while it is out sends nothing. A line reads `<first 8> applied ✅` or `<first 8> refused: <server words>`, so a refusal never hides the others.
- `handleBatchViewLinkClick` reads every row and shows `<first 8> · <status> · <title>` per row, the way the abstract 📋 shows text.
- An unreadable row says so, and the rest still show. The older page gets the same behaviour through `_handleBatchApproveLinkClick` and `_handleBatchViewLinkClick`, which call the shared handlers.
- The single-row readers `approveRowId` and `viewRowId` do not claim a batch address. The batch handlers do not claim a single one.
- `/app/tasks/approve?rows=...&move=...` lists the rows and has one button, and `/app/tasks/view?rows=...` only lists them. Opening either changes nothing.

## Don't
- Don't send single lines for many rows, and don't type the link by hand. Take the batch line from `task_approve_batch_line`.
