---
capability: web-client-render-task-row-cells
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowDisclosed.renderVisibleCell@4c47029642
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowDisclosed.disclosedValues@6188e3ed8a
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowDisclosed.renderDisclosedRow@6efe3fd508
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowControls.renderDetailContent@908872eee0
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowControls.renderVerbControl@b12d27e410
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowControls.ensureDropReasonDatalist@5286822aed
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowControls.renderPriorityControl@d9367db449
  - src.lupin_app.static.js.multiplexer.render.templates.taskRowControls.renderActionsContent@0368446061
---
# Web client: shared task row

The one row template the task list, holding area and epic board all paint, and the controls behind its toggle.

The panes are in [[web-client-task-board-panes]]. The click handling is in [[web-client-render-task-row-controller]].

## What it does
- `renderDisclosedRow( task, pane, zone, reassignTargets, nowMs )` returns a `DocumentFragment` of three rows: the visible row, a hidden controls row and a hidden error stripe.
- The visible row has one cell per line-one field in order, then the toggle cell. Its class carries `task-row`, `epic-row` on the epic board, the status class and `task-row-parked` when parked.
- A row with a pending promote or demote request gets a request chip in its title cell. The task list and holding area show it; the epic board never does.
- `renderVisibleCell` fills one line-one cell. The title cell keeps the full title as its `title` attribute, and the status cell adds a "parked" badge for a parked row. The id cell shows 8 characters and, when the id exists, is a "Click to copy ID" button.
- `disclosedValues` returns the line-two and line-three content: blocked, chase, accountable, filer, project, detail and actions.
- `renderDetailContent` returns the 📄. With no body it is dimmed, `aria-disabled`, "No detail". Otherwise it is a button, "View detail", carrying the body and id.
- `renderVerbControl` returns a verb select, 🎤 mic, reason box and Submit. Illegal verbs are greyed with the reason in the label, and a terminal row disables all four.
- `ensureDropReasonDatalist( doc )` puts one `datalist#task-drop-reason-suggestions` on the body, with four canned reasons.
- `renderPriorityControl` returns a P0 to P5 select and an Update button, disabled until the value differs from `data-original`.
- `renderActionsContent` returns the priority control, an owner select and the verb control. The current owner comes first, then the targets, de-duplicated.

## How the parts work together
`renderDisclosedRow` calls `disclosedValues`, which calls `renderDetailContent` and `renderActionsContent`. The actions cell uses `verbLegality` for greying, so the template never restates the rule.

## Don't
- Don't give a pane its own row. Cell-for-cell identity across panes is required.
