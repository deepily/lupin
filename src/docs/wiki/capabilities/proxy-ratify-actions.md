---
capability: proxy-ratify-actions
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.toggleSelect@55706eea2e
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.toggleSelectAll@5d27846489
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.updateBulkActions@c68b035d38
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.bulkApprove@3753aa0ac2
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.showConfirmModal@d750bcf24c
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.closeConfirmModal@e8f9db7228
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.bulkReject@9a522545a3
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.confirmBulkReject@6649fdb9ef
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.bulkDelete@1e7eea5ae2
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.confirmBulkDelete@c0415bede5
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.quickApprove@12bddf070e
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.quickReject@f78fb37bd3
  - src.lupin_app.static.html.auth.admin.js.proxy-ratify.quickDelete@b07a897f6f
---
# Proxy ratification actions

The selection, bulk and one-click actions of [[proxy-ratify-page]]. Each ends by reloading the pending list with `loadPending`.

## Selection
- `toggleSelect` adds or removes one id. `toggleSelectAll` selects or clears the rows on the current page only, then redraws.
- `updateBulkActions` shows the bulk bar with "N selected" when the selection is not empty, and hides it otherwise.

## Bulk actions
- `bulkApprove` approves each selected id in turn with no confirmation. A failure is counted and logged, and the loop goes on. The message says how many succeeded and how many failed.
- `bulkReject` and `bulkDelete` do nothing on an empty selection. Otherwise they open the confirm dialog, and `confirmBulkReject` or `confirmBulkDelete` runs the same loop. Deletion is worded as permanent.
- `showConfirmModal( title, message, label, onConfirm )` fills the dialog, stores the action and focuses the confirm button. `closeConfirmModal` hides it and drops the action.

## One-click actions
- `quickApprove` and `quickReject` ratify one row at once, with an empty feedback, and show a success or error message.
- `quickDelete` asks for confirmation first, then deletes.

## Don't
- Don't expect `bulkApprove` to ask first. Only reject and delete confirm.
