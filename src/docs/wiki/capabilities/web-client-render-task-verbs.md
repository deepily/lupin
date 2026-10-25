---
capability: web-client-render-task-verbs
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.render.taskVerbs.verbNeeds@8c27e60969
  - src.lupin_app.static.js.multiplexer.render.taskVerbs.verbLabel@c0aa61aec9
  - src.lupin_app.static.js.multiplexer.render.taskVerbs.verbReasonComplaint@7cbba76943
  - src.lupin_app.static.js.multiplexer.render.taskVerbs.verbDateComplaint@fbb977d594
---
# Web client: task verb table

What each task verb asks the operator for, how it is labelled, and the sentence a missing field earns.

Which verbs a row may take (`verbLegality`) and the extra body fields (`transitionExtras`) are in [[web-client-task-board-panes]]. The controls that use this table are in [[web-client-render-task-row-cells]].

## What it does
- `verbNeeds( verb )` returns the verb's record, or null for an unknown or empty verb. A null means the operator has chosen nothing yet.
- The record holds the `to_status`, whether a reason or a date is required, the date label, the reason placeholder and whether the verb is terminal.
- Park goes to `parked` and needs a reason and a date ("Chase me again on"). Demote goes to `not_approved` and needs the same ("Triage this by").
- drop goes to `dropped` and needs a reason. wont_fix goes to `wont_fix`, needs a reason and is terminal.
- fixed goes to `done`, needs no reason and is terminal. unpark and approve both go to `queued` and need nothing.
- `verbLabel` returns Park, Drop, Demote, Won't fix, Fixed, Un-park or Approve, and the verb itself when unknown.
- `verbReasonComplaint` has its own sentence for drop, park, demote and wont_fix. Any other verb gets "A reason is required."
- `verbDateComplaint` returns the chase-date sentence for park and the triage-by sentence for every other verb.

## How the parts work together
The row controller calls `verbNeeds` on the chosen verb, checks the reason and date it asks for. It shows the matching complaint before any request is sent.
A terminal verb earns a second click as confirmation. The same record shapes the reason box and date input when the verb changes.

## Don't
- Don't share one complaint across verbs. Park wants a quoted sentence, demote a reason for going back to triage.
