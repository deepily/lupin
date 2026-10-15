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
- `create_task`, `POST /tasks` (`TaskCreateIn`): makes one row with 201. An omitted status takes the approval default. An over-long title is trimmed, with the overflow moved into an empty body. The priority firewall answers 403 for a priority the caller may not set. A manager relaying the operator's word for P0 is filed as a petition at P1 instead.
- `transition_task`, `POST /tasks/{id}/transition` (`TaskTransitionIn`): one state change. Done needs `receipt_refs`, blocked needs typed `blocked_by`, dropped needs a `reason`, parked needs `park_reason`. Returns `{ item, event }`.
- `correlate_task`, `.../correlate` (`TaskCorrelateIn`): re-stamps the `correlation_key`. A terminal row is 422.
- `ask_to_unpark`, `.../unpark-ask` (`UnparkAskIn`): a manager seat asks the operator to un-park a row. The server makes a yes or no card and pushes it. It is 403 for a non-manager and 404 for no such row or no operator account. It is 409 for a row not parked, one with no recorded park time, or one with a card already waiting. It writes no task event.
- `amend_task`, `.../amend` (`TaskAmendIn`): appends a stamped note to the body, and a blank note is 422. It is allowed on a closed row, where the note is marked a post-terminal addendum.
- `patch_task`, `PATCH /tasks/{id}` (`TaskPatchIn`): edits title, body, priority, owner, manager, gate class and urgency on a live row. A title over the cap is 422, not trimmed. Status and blockers are not editable here. A priority raise the priority firewall refuses is 403.

## Don't
- Don't send `asynchronous` as a string. The field is a strict boolean, and `"true"` is refused.
- Don't PATCH a terminal row with anything but a title that starts `WITHDRAWN`, `SUPERSEDED` or `CORRECTED`, sent alone. Everything else is 422, as is a retitle past the cap.

## Invariants
- Every write here except `ask_to_unpark` appends one audit event in the same transaction. Closed rows take `amend` and that title prefix, and nothing else.
