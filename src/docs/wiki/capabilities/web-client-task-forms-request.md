---
capability: web-client-task-forms-request
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.shared.arg-interview.isAnswerable@a1e8d299b8
  - src.lupin_app.static.js.shared.arg-interview.resumeBody@d374204dbf
  - src.lupin_app.static.js.shared.arg-interview.renderArgQuestion@857015f638
  - src.lupin_app.static.js.shared.arg-interview.clearArgQuestion@7ba8034708
  - src.lupin_app.static.js.shared.arg-interview.publishOnWindow@a536d04686
  - src.lupin_app.static.js.shared.task-request.requestVerdictPath@1951f8b67b
  - src.lupin_app.static.js.shared.task-request.requestAge@0b3d598cc8
  - src.lupin_app.static.js.shared.task-request.pendingRequestChip@be67091a58
  - src.lupin_app.static.js.shared.task-request.requestVerdictBody@197b3f67f1
  - src.lupin_app.static.js.shared.task-request.requestEventsPath@6592d8fb6e
  - src.lupin_app.static.js.shared.task-request.requestFiledDetail@0d8e1e2cd2
  - src.lupin_app.static.js.shared.task-request.requestBadgeText@c327486bbd
  - src.lupin_app.static.js.shared.task-request.pendingRequestCount@b097d14e81
  - src.lupin_app.static.js.shared.task-request.groupRequestBadgeText@8f9855da4e
  - src.lupin_app.static.js.shared.task-request.groupRequestBadgeLabel@0dfc0bc5e4
---
# Web client task forms: request and interview

The shared scripts that file a task request and run the argument interview. [[web-client-task-board-panes]] describes the board that uses them.

## What it does
- `arg-interview.js`. `isAnswerable`: Is this response a question the user can actually answer?. `resumeBody`: The body for the POST /api/v2/resume that answers this question. `renderArgQuestion`: Render the flow's question as an inline answer box inside `containerEl`. `clearArgQuestion`: Take the interview box down. `publishOnWindow`: Publish for the classic-script consumer. See shared/agent-select.js:publishOnWindow.
- `task-request.js`. `requestVerdictPath`: `"/api/tasks/<id>/request-verdict"`. `requestAge`: How long a request has waited, in words short enough for a chip. `pendingRequestChip`: What the pending-request chip on a row says, or null when the row has nothing pending. `requestVerdictBody`: The body a verdict click sends, or the reason it cannot be sent yet. `requestEventsPath`: `"/api/tasks/<id>/events"` — where the filer and reason of a request live. `requestFiledDetail`: Who filed the row's current request and why, read off its audit trail. `requestBadgeText`: A badge chip's text for one of the two counts, or "" when nothing is waiting. `pendingRequestCount`: How many of these rows carry a pending request. `groupRequestBadgeText`: A persona group's request badge text, or "" when none. `groupRequestBadgeLabel`: A persona group's request badge, spoken: "1 pending request", "3 pending requests", or "".
