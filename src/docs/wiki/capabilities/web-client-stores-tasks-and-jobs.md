---
capability: web-client-stores-tasks-and-jobs
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - src.lupin_app.static.js.multiplexer.stores.FinishedTasksStore.FinishedTasksStoreImpl@4a23036965
  - src.lupin_app.static.js.multiplexer.stores.FinishedTasksStore.describeFailure@9af781738c
  - src.lupin_app.static.js.multiplexer.stores.FinishedTasksStore.createFinishedTasksStore@7af05b7439
  - src.lupin_app.static.js.multiplexer.stores.HoldingAreaStore.awaitingApproval@e705b50bce
  - src.lupin_app.static.js.multiplexer.stores.HoldingAreaStore.holdingRefusalMessage@6e41206dfc
  - src.lupin_app.static.js.multiplexer.stores.HoldingAreaStore.HoldingAreaStoreImpl@247e2ac0fe
  - src.lupin_app.static.js.multiplexer.stores.HoldingAreaStore.createHoldingAreaStore@24100b1b81
  - src.lupin_app.static.js.multiplexer.stores.JobStore.mapServerStateToStatus@32af852f5e
  - src.lupin_app.static.js.multiplexer.stores.JobStore.JobStoreImpl@ab0a7a9e82
  - src.lupin_app.static.js.multiplexer.stores.JobStore.createJobStore@2813e361cd
  - src.lupin_app.static.js.multiplexer.stores.TaskListStore.AwaitingHumanApprovalError@422bee653c
  - src.lupin_app.static.js.multiplexer.stores.TaskListStore.awaitingApproval@37c5a42215
  - src.lupin_app.static.js.multiplexer.stores.TaskListStore.TaskListStoreImpl@d33bd14695
  - src.lupin_app.static.js.multiplexer.stores.TaskListStore.NOOP_MUTATION@1dea27fe33
  - src.lupin_app.static.js.multiplexer.stores.TaskListStore.createTaskListStore@e8b9d2e800
  - src.lupin_app.static.js.multiplexer.stores.TaskRequestStore.TaskRequestStoreImpl@b23bfa9314
  - src.lupin_app.static.js.multiplexer.stores.TaskRequestStore.createTaskRequestStore@cde4e87eca
  - src.lupin_app.static.js.multiplexer.stores.alreadyAtTarget.alreadyThereMessage@9a10906b6f
  - src.lupin_app.static.js.multiplexer.stores.alreadyAtTarget.alreadyAtTarget@cab7d07e46
  - src.lupin_app.static.js.multiplexer.stores.jobViewFilter.jobHistoryUserFilter@ee7fed5158
---
# Web client stores: tasks and jobs

The stores for jobs, the task list, the holding area, finished tasks and task requests. [[web-client-stores]] covers how they are built.

## What it does
- `FinishedTasksStore.ts`. `FinishedTasksStoreImpl`: Holds finished-task events by terminal status for a chosen window of days. `describeFailure`: A human-readable failure for one status's call. `createFinishedTasksStore`: Build the store. It fetches nothing when it is built.
- `HoldingAreaStore.ts`. `awaitingApproval`: Whether a transition response says "Rick has not been asked yet". `holdingRefusalMessage`: Turn whatever the api client threw into the sentence the operator reads. `HoldingAreaStoreImpl`: Holds the held-task list and writes task changes back for the holding pane. `createHoldingAreaStore`: Build the store. It fetches nothing when it is built.
- `JobStore.ts`. `mapServerStateToStatus`: Maps a server job state name to a UI status, or null when unknown. `JobStoreImpl`: Holds jobs in todo, running, done, dead, and history buckets from server events. `createJobStore`: Build the store.
- `TaskListStore.ts`. `AwaitingHumanApprovalError`: Raised when the transition door answers "Rick has not been asked yet". `awaitingApproval`: Whether a transition answer is the 202 awaiting-approval body. `TaskListStoreImpl`: Holds the cached task list, refreshes it by polling and push, and applies quick edits. `NOOP_MUTATION`: Returns a mutation handle that does nothing: inert rollback and a resolved promise. `createTaskListStore`: Build the store. It fetches nothing when it is built.
- `TaskRequestStore.ts`. `TaskRequestStoreImpl`: Holds the request badge counts and cached filing details for task requests. `createTaskRequestStore`: Build the store. It fetches nothing when it is built.
- `alreadyAtTarget.ts`. `alreadyThereMessage`: The sentence both clients show when a click found the row already at the target. `alreadyAtTarget`: True when a rejected transition left the row already at the status it was sent to.
- `jobViewFilter.ts`. `jobHistoryUserFilter`: The `user_filter` to send with a job-history replace.
