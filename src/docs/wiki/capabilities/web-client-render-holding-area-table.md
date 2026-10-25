---
capability: web-client-render-holding-area-table
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.holdingApproveAllTitle@be681a42b3
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.holdingWontFixAllTitle@89304f525c
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.holdingGroupChevron@33eabdedea
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.batchButton@6ee248287a
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.renderGroupHeader@bd18da6563
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.renderRowTable@f5ba98c2e9
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.holdingPlanApproveLabel@924a7e77b0
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.holdingPlanApproveTitle@ccf91b6b71
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.holdingPlanChevron@94df1b86e0
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.renderHoldingPlanGroup@606881d551
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.renderHoldingAreaGroup@d54469de58
  - src.lupin_app.static.js.multiplexer.render.templates.holdingAreaTable.renderHoldingAreaGroups@10013f375d
---
# Multiplexer holding-area table render

The DOM builders of the holding area: one collapsible group per filer, with batch controls, plan sub-groups and a table of held rows. The grouping model is in [[web-client-render-holding-area-model]].

## Wording and controls
- `holdingApproveAllTitle( filer )` and `holdingWontFixAllTitle( filer )` are the batch tooltips. The approve one says it is reversible. The won't-fix one says it is terminal and every row gets the same reason.
- `holdingGroupChevron( expanded )` is `▼` open and `▶` closed. `holdingPlanChevron` returns the same glyph for a plan group.
- `holdingPlanApproveLabel( n )` is `Approve all N`, and `holdingPlanApproveTitle( n )` says the N rows are reversible.
- `batchButton( cls, filer, label, title )` builds a task action button carrying the filer name, class, label and tooltip.

## Groups and rows
- `renderGroupHeader( group, expanded )` is the keyboard-reachable header with the filer label, the count, batch approve, batch won't-fix, the reason box and the status span. Every control carries `data-filer`.
- `renderRowTable( tasks, ianaZone, reassignTargets )` builds a `.holding-area-table` with the shared row head.
- `renderHoldingPlanGroup( filer, plan, ianaZone, reassignTargets, expanded )` is one `.holding-plan-group` with a header and a table of only the plan's rows. The approve button's `data-task-ids` come from the same rows.
- `renderHoldingAreaGroup( group, ... )` is one filer's `.holding-area-group`, `collapsed` unless expanded. Plan groups come first, then the filer's ungrouped rows, with no table when there are none.
- `renderHoldingAreaGroups( groups, ... )` returns a fragment of one group per filer, open only for a filer in `expandedFilers`. An empty model gives an empty fragment.
