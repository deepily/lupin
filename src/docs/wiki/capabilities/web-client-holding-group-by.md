---
capability: web-client-holding-group-by
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.holdingAreaModel.personaDisplay@3ff85e2cec
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.holdingGroupWhose@d4441338b0
  - src.lupin_app.static.js.multiplexer.render.HoldingAreaRenderer.readSavedGroupBy@96147fe37c
---
# Holding area: Creator and Assignee grouping
The holding area groups its rows by creator or by assignee, and the choice is saved in the browser. The model is on [[web-client-render-holding-area-model]] and the table on [[web-client-render-holding-area-table]].
- `personaDisplay` shows a persona as the pane does: session id stripped and each word capitalised. A blank value gives the capitalised fallback, and it never throws.
- Both group labels use it, so the strip and the casing exist once. The Finished Tasks Who column does not use it.
- `holdingGroupWhose` gives the tooltip phrase for whose rows a group holds: `<name> filed`, or `assigned to <name>`.
- `readSavedGroupBy` returns the saved grouping, `creator` unless `assignee` was saved. It also returns `creator` when storage is blocked, so the pane works without it.
