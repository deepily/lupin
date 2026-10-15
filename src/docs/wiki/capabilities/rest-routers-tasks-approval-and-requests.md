---
capability: rest-routers-tasks-approval-and-requests
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.tasks.ManagerPullRequest@a40e662dad
  - cosa.rest.routers.tasks.ApprovalSettingsRequest@9588049be1
  - cosa.rest.routers.tasks.get_approval_settings@cd0fa786cf
  - cosa.rest.routers.tasks.patch_approval_settings@4c3c547429
  - cosa.rest.routers.tasks.get_manager_pull@722e5920de
  - cosa.rest.routers.tasks.set_manager_pull@d275064055
  - cosa.rest.routers.tasks.RequestVerdictIn@28aacb4fcc
  - cosa.rest.routers.tasks.RequestFileIn@c4de8b53e2
  - cosa.rest.routers.tasks.get_request_badges@6ca1d42be6
  - cosa.rest.routers.tasks.file_request@26420ae53f
  - cosa.rest.routers.tasks.record_request_verdict@a49da8cd36
---
# Task store approval settings and promote requests

The operator controls and the manager request flow in `cosa.rest.routers.tasks`, under `/api`. The gate itself is in [[task-promotion-gate]].

## What it does
- `get_approval_settings`, `GET /tasks/approval-settings`: the effective settings and where each came from. Any authenticated caller may read them.
- `patch_approval_settings`, `PATCH`, body `ApprovalSettingsRequest`: only the operator's login may write, 403 for anyone else. An empty body or a bad value is 422 and writes nothing. A failed save is 500 and nothing applies. The reply is the settings read back.
- `get_manager_pull` and `set_manager_pull`, `/tasks/manager-pull`: read or flip the switch that stops pulling work into in_progress for everyone but an approver. The read returns `disabled` and `source` (`override` or `config`). The write (`PATCH`) needs an admin and a real boolean in `ManagerPullRequest`.
- `file_request`, `POST /tasks/{id}/request` (`RequestFileIn`): a manager asks the operator to `admit` or `demote` one row. The row's status does not move. A non-manager is 403, a move the row's status cannot make is 409, and a blank reason is 422. While `sword_of_damocles_active` is on, an admit must name a live ticket you own in `deletion_task_id`, and approval drops it.
- `record_request_verdict`, `.../request-verdict` (`RequestVerdictIn`): the operator answers `approved` or `denied`. Approval performs the move. A row with no request is 409, a caller who is not the operator is 403, and a request already answered is 409.
- `get_request_badges`: `{ task_area, holding_area }`, the pending demote and promote counts, never summed.

## Don't
- Don't send a boolean setting as the string `"false"`. The strict fields refuse it.
- Don't file a second request on a row while one is pending. It is 409, except an admit whose pledged ticket has since died, which may be re-filed.

## Invariants
- A denial leaves the row's status where it is. A refused approval rolls back the verdict, so the request stays pending.
