---
capability: web-client-render-epic-board
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.epicBoardCollapse.epicGroupIdSlug@1ce036a66a
  - src.lupin_app.static.js.multiplexer.render.epicBoardCollapse.epicDefaultExpanded@735bf68817
  - src.lupin_app.static.js.multiplexer.render.epicBoardCollapse.loadEpicGroupState@96c8bc68cb
  - src.lupin_app.static.js.multiplexer.render.epicBoardCollapse.saveEpicGroupState@2907376057
  - src.lupin_app.static.js.multiplexer.render.epicBoardCollapse.epicGroupIsExpanded@682a40a218
  - src.lupin_app.static.js.multiplexer.render.epicBoardCollapse.toggleEpicCollapsed@3c6b644b51
  - src.lupin_app.static.js.multiplexer.render.epicBoardModel.epicKeyOf@b2fdddfd73
  - src.lupin_app.static.js.multiplexer.render.epicBoardModel.taskWaitsOnRick@44165bce89
  - src.lupin_app.static.js.multiplexer.render.epicBoardModel.epicTitleLabel@dd48248bfe
  - src.lupin_app.static.js.multiplexer.render.epicBoardModel.epicStoryText@b9a0b15041
  - src.lupin_app.static.js.multiplexer.render.templates.epicBoardTable.renderGroupHeader@55c0d0bc8d
  - src.lupin_app.static.js.multiplexer.render.templates.epicBoardTable.renderSection@90463f24c0
  - src.lupin_app.static.js.multiplexer.render.templates.epicBoardTable.epicBoardSections@9a2e80e126
  - src.lupin_app.static.js.multiplexer.render.templates.epicBoardTable.renderEpicBoardTable@2f6c39830f
---
# Multiplexer epic board render

The pure model, the saved open and closed choices, and the table builder of the epic board card.

## Model (`epicBoardModel`)
- `epicKeyOf( task )` returns the task's `correlation_key` when it starts with `epic:`, else null, so a row with none is drift and never dropped.
- `taskWaitsOnRick( task )` is true when `blocked_by` is an array holding a ref with id `rick`, any case, and kind `user` or `persona`. Anything else is false, and it never throws.
- `epicTitleLabel( epicKey, stories )` is the story title when it is non-empty, else the key without `epic:` and with dashes as spaces. `epicStoryText` is the story line, or an empty string.

## Collapse state (`epicBoardCollapse`)
- The state is a map of group key to expanded. A key never toggled is absent and takes `epicDefaultExpanded`, which is true only for the `__on_rick__` group.
- `loadEpicGroupState` reads the map from localStorage and returns `{}` for a missing key, bad JSON, an array or storage that throws. It drops non-boolean values. `saveEpicGroupState` swallows a write failure.
- `epicGroupIsExpanded( epicKey, state )` is the recorded choice, else the default. `toggleEpicCollapsed` flips and saves the choice and returns the new collapsed value, not the expanded one.
- `epicGroupIdSlug( epicKey )` gives `epic-group-` plus the key with characters outside letters, digits, `_` and `-` replaced by `-`.

## Table (`epicBoardTable`)
- `epicBoardSections( model, stories )` lists sections in order: Waiting on Rick only when it has rows, then one per epic, then Drift last and always.
- `renderEpicBoardTable` builds an `.epic-board-table` with the shared row header and one `tbody.epic-group` per section. `renderSection` adds the header bar, the story row when one exists, and the rows; `renderGroupHeader` is the clickable bar with a chevron and `aria-expanded`.
