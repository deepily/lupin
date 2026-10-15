---
capability: web-client-render-holding-area-model
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingBatchNeeds@6ebcb97ce7
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingBatchInFlightStatus@455aaac66e
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingBatchFinalStatus@14bf6cfeac
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingBatchExtras@2ee69d2982
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingBatchRestLabel@5852362a24
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingBatchConfirmLabel@09a6e8f02d
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingBatchArmedStatus@9682b0687e
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingPlanConfirmLabel@61b5efc470
  - src.lupin_app.static.js.multiplexer.render.holdingAreaBatch.holdingPlanArmedStatus@9cfaed28d9
  - src.lupin_app.static.js.multiplexer.render.holdingAreaModel.holdingPlanId@3730f4bc4d
  - src.lupin_app.static.js.multiplexer.render.holdingAreaModel.taskFilerLabel@dcc9552946
  - src.lupin_app.static.js.multiplexer.render.holdingAreaModel.groupHeldRowsByFiler@9fa2629d92
  - src.lupin_app.static.js.multiplexer.render.holdingAreaModel.planTitle@4303456a5a
  - src.lupin_app.static.js.multiplexer.render.holdingAreaModel.heldHeaderCount@210ceb37a0
---
# Multiplexer holding-area model

The status wording of the batch buttons, and the model that groups the holding area's tickets by who filed them.

## Batch wording (`holdingAreaBatch`)
- `holdingBatchNeeds( verb )` returns a batch verb's obligation record, or null for an unknown, empty or inherited name. `holdingBatchExtras( verb, reason )` carries a `reason` field only for a verb that takes one.
- `holdingBatchRestLabel( verb )` is `Won't fix all` or `Approve all`. `holdingBatchConfirmLabel( verb, count )` is the armed label naming the verb and the count.
- `holdingBatchArmedStatus( verb, count )` is the line shown while a button is armed. It is not kept across a repaint.
- `holdingBatchInFlightStatus( pastLabel, attempted, total )` is `<Past> <attempted> of <total>…`. The number counts attempts, not successes.
- `holdingBatchFinalStatus( pastLabel, ok, failed, total, firstError )` is `<ok> of <total> <past>.` and adds the refused count and the first refusal when any failed.
- `holdingPlanConfirmLabel( count )` and `holdingPlanArmedStatus( count )` are the armed label and status line of a plan's approve button.

## Model (`holdingAreaModel`)
- `holdingPlanId( filer, key )` joins the filer and the plan key with a `\u0001` separator, since two filers can hold rows under one key.
- `taskFilerLabel( task )` is the person in `created_by`, display-cased, with a trailing session id stripped. A value with no session id is kept whole. An absent one is a dash.
- `groupHeldRowsByFiler( tasks, keep )` groups by filer, not owner. Filers sort alphabetically, and rows sort by priority then title. A key forms a plan only with two or more of one filer's rows, unless named in `keep`.
- `planTitle( key )` drops a leading `epic:` and turns hyphens and underscores into spaces. A key that is only the prefix stays as it is.
- `heldHeaderCount( composite )` is the count the pane's header would show, or null before the first poll, for a sentinel status or for malformed tasks.
