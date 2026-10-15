---
capability: rest-routers-tasks-reads
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.tasks.query_tasks@12321c7fa3
  - cosa.rest.routers.tasks.query_event_stream@5bc1fb024a
  - cosa.rest.routers.tasks.get_flow_ratio@c699b4eeef
  - cosa.rest.routers.tasks.FlowRatioSettingsRequest@7b62555168
  - cosa.rest.routers.tasks.get_flow_ratio_settings@82992009e6
  - cosa.rest.routers.tasks.patch_flow_ratio_settings@e9c0e73163
  - cosa.rest.routers.tasks.delete_flow_ratio_settings@394f1ffeb2
  - cosa.rest.routers.tasks.list_promotion_tickets@0006ec0f91
  - cosa.rest.routers.tasks.get_promotion_ticket@5a79b7fc16
  - cosa.rest.routers.tasks.get_task@7e8446a939
  - cosa.rest.routers.tasks.get_task_events@00562e21db
  - cosa.rest.routers.tasks.get_epic_stories@3876b4aef0
---
# Task store query and report routes

The read routes of `cosa.rest.routers.tasks`, under `/api`, plus the flow-ratio settings. Writes are in [[rest-routers-tasks-writes]].

## What it does
- `query_tasks`, `GET /tasks`: exact-match filters, newest first, `limit` up to 500. It returns `tasks`, `count`, `total`, `has_more`, `truncated` and `warnings`. `count_only=true` returns a true count with a per-status `breakdown` and a `priority_breakdown`. Without `unscoped_audit=true`, a query with no filter that would return over 50 live rows is 400.
- `query_event_stream`, `GET /tasks/events`: the audit trail across all items, filtered by actor, transition, `to_status`, project and `since` and `until`. An unknown `to_status` is 422.
- `get_task`, `GET /tasks/{id}`: one item by full UUID or a hex prefix of 4 or more characters. An ambiguous prefix is 422 naming the candidates.
- `get_task_events`: one item's events, oldest first. 404 for an unknown item.
- `get_flow_ratio`, `GET /tasks/flow-ratio`: created against closed over a rolling window, with a verdict and the room left.
- `get_flow_ratio_settings`, `patch_flow_ratio_settings` and `delete_flow_ratio_settings`, `/tasks/flow-ratio/settings`: read the live window and threshold with their sources, set an override (admin, `FlowRatioSettingsRequest`, partial), or clear it.
- `list_promotion_tickets` lists pending tickets by default and `get_promotion_ticket` returns one with its response.
- `get_epic_stories` serves `src/conf/epic-stories.json`. A missing file is 200 with no stories.

## Don't
- Don't read `count` as the result size. Use `total` and `has_more`.

## Invariants
- A junk enum filter is 422, never an empty result.
