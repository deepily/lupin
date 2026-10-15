---
capability: rest-routers-tasks-writes
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.tasks.TaskCreateIn@ca33745685
  - cosa.rest.routers.tasks.TaskTransitionIn@e00e7dcdc2
  - cosa.rest.routers.tasks.UnparkAskIn@287a548d04
  - cosa.rest.routers.tasks.TaskCorrelateIn@22e61de319
  - cosa.rest.routers.tasks.TaskAmendIn@2696c629b7
  - cosa.rest.routers.tasks.TaskPatchIn@cf730bfc20
  - cosa.rest.routers.tasks.create_task@12e9802221
  - cosa.rest.routers.tasks.transition_task@6a5554ab30
  - cosa.rest.routers.tasks.correlate_task@323fddc93c
  - cosa.rest.routers.tasks.ask_to_unpark@f623852974
  - cosa.rest.routers.tasks.amend_task@fd1f47f8e4
  - cosa.rest.routers.tasks.patch_task@8d03a01c16
---
# Task store write routes

The routes of `cosa.rest.routers.tasks` that change an item, under `/api`. All take an API key or a Bearer token. Each body model forbids unknown fields, so a misspelt key is a 422, never a silent drop. Reads are in [[rest-routers-tasks-reads]]; the rules are in [[task-store]].

## What it does
- `create_task`, `POST /tasks` (`TaskCreateIn`): makes one row with 201. An omitted status takes the approval default, and an over-long title is trimmed with the overflow moved to the body.
- `transition_task`, `POST /tasks/{id}/transition` (`TaskTransitionIn`): one state change. Done needs `receipt_refs`, blocked needs typed `blocked_by`, dropped needs a `reason`, parked needs `park_reason`. Returns `{ item, event }`.
- `correlate_task`, `.../correlate` (`TaskCorrelateIn`): re-stamps the `correlation_key`. A terminal row is 422.
- `ask_to_unpark`, `.../unpark-ask` (`UnparkAskIn`): a manager seat asks the operator to un-park a row. 403 for a non-manager, 409 for a row not parked or one with a card already waiting.
- `amend_task`, `.../amend` (`TaskAmendIn`): appends a stamped note to the body. It is the one write allowed on a closed row.
- `patch_task`, `PATCH /tasks/{id}` (`TaskPatchIn`): edits title, body, priority, owner, manager, gate class and urgency. Status and blockers are not editable here.

## Don't
- Don't send `asynchronous` as a string. The field is a strict boolean, and `"true"` is refused.
- Don't PATCH a terminal row, or retitle past the cap. Both are 422.

## Invariants
- Every write appends one audit event in the same transaction.
