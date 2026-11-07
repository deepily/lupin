---
capability: utils-task-store-adapter
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.task_store_adapter.TaskStoreAdapter@ff4fae7e00
  - cosa.repo.symindex.task_store_adapter.TaskStoreAdapter.create@7b392200c8
  - cosa.repo.symindex.task_store_adapter.TaskStoreAdapter.amend@8c6a6ec971
---
# Task-store adapter

The base of the two live store adapters: the wiki librarian tick ([[repo-tools-symindex-librarian-tick-run]]) and the daily duplicate check ([[duplicate-check-filing]]). Both hold the same settings, key and client, and make the same two calls.

## What it does
- `TaskStoreAdapter( settings, api_key, client )` keeps the three collaborators. The client is the hooks' `task_store_client`, or a stand-in with `create_task` and `amend_task`.
- `create( payload )` sends the payload plus the class's `create_extra` fields. `amend( row_id, note )` sends the note plus `amend_extra`. Both return `( ok, status, body )`.
- The tick stamps its actor and the standing authority on both calls. The filing adds nothing to a create and a reason to an amend.

## Don't
- Don't add a `query` here. Each subclass reads the store its own way.
