---
capability: web-client-render-task-list-table
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.rowSchema.rowWidth@d9f22271e0
  - src.lupin_app.static.js.multiplexer.render.rowSchema.rowFieldLabel@3691affc7f
  - src.lupin_app.static.js.multiplexer.render.rowSchema.disclosedFields@acbd648b3f
  - src.lupin_app.static.js.multiplexer.render.taskListCollapse.ownerKeyForGroup@d83c487b79
  - src.lupin_app.static.js.multiplexer.render.taskListCollapse.taskGroupIdSlug@000d4464f6
  - src.lupin_app.static.js.multiplexer.render.taskListCollapse.loadCollapsedOwners@38c9ef3b00
  - src.lupin_app.static.js.multiplexer.render.taskListCollapse.saveCollapsedOwners@6db989523a
  - src.lupin_app.static.js.multiplexer.render.taskListCollapse.toggleCollapsedOwner@46e123a293
  - src.lupin_app.static.js.multiplexer.render.templates.taskListTable.renderGroupHeader@7f059a9b4e
  - src.lupin_app.static.js.multiplexer.render.templates.taskListTable.renderTaskListTable@ed47b044e1
---
# Web client: task list table

The row schema, the per-owner collapse state and the table that lays out the owner-grouped task list.

The pane's own states (sign-in, unreachable, empty) are in [[web-client-task-board-panes]]. The grouping and formatters are in [[web-client-render-task-list-model]].

## What it does
- `ROW_SCHEMA` splits a row into three lines. Line one (id, title, class, status, priority) is always visible. Line two (blocked, chase, accountable, filer, project) and line three (detail, actions) sit behind the row's disclosure toggle.
- `rowWidth` is the line-one field count plus one for the toggle cell. `rowFieldLabel` returns a field's label, such as "Next chase", or the field name when unknown. `disclosedFields` returns line two then line three.
- `ownerKeyForGroup` returns the persona, or `__unassigned__` for the ownerless group. `taskGroupIdSlug` prefixes `task-group-` and turns every character outside letters, digits, `_` and `-` into `-`.
- `loadCollapsedOwners` reads a JSON array from `localStorage` key `lupin.taskList.collapsedOwners`. Missing, garbled or unavailable storage gives an empty set, so every owner starts expanded.
- `saveCollapsedOwners` writes the set and swallows a storage failure. `toggleCollapsedOwner` flips one key, saves, and returns the new collapsed state.
- `renderTaskListTable( model, ianaZone, collapsedOwners, reassignTargets )` returns a `.task-list-table`: the shared head, then one `tbody.task-group` per owner. A collapsed owner's tbody gets the class `collapsed`.
- `renderGroupHeader` builds the header row: ▸ when collapsed, ▾ when open, `aria-expanded`, and `aria-controls` set to the tbody id. It reads "owner · count", or "(Unassigned)" with no count.

## How the parts work together
`renderTaskListTable` asks `ownerKeyForGroup` and `taskGroupIdSlug` for each group's key and tbody id, and checks the key against the set it was given. It appends three rows per task through `renderDisclosedRow` ([[web-client-render-task-row-cells]]). It only reads the set; a caller flips it with `toggleCollapsedOwner` and repaints.

## Don't
- Don't write a colspan literal. Every span comes from `rowWidth`, so the head, header and controls rows stay in step.
