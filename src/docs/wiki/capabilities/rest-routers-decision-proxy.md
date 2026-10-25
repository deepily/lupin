---
capability: rest-routers-decision-proxy
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.decision_proxy.get_current_batch_id@6e2276614f
  - cosa.rest.routers.decision_proxy.acknowledge_batch@0d0fc41baf
  - cosa.rest.routers.decision_proxy.acknowledge_proxy_batch@341fe0435b
  - cosa.rest.routers.decision_proxy.get_proxy_batch_id@cde0ccb1ef
  - cosa.rest.routers.decision_proxy.get_pending_decisions@58855cf867
  - cosa.rest.routers.decision_proxy.ratify_decision@778a4d0210
  - cosa.rest.routers.decision_proxy.delete_decision@fd7e1edf39
  - cosa.rest.routers.decision_proxy.get_trust_state@90d45c3fcc
  - cosa.rest.routers.decision_proxy.get_decisions_by_domain_category@3413319e5a
  - cosa.rest.routers.decision_proxy.TrustModeUpdateRequest@d138ee0eee
  - cosa.rest.routers.decision_proxy.get_run_queue@7e094de5fe
  - cosa.rest.routers.decision_proxy.get_config_mgr@ff2636b05f
  - cosa.rest.routers.decision_proxy.get_trust_mode@447bfd2d53
  - cosa.rest.routers.decision_proxy.update_trust_mode@0f7032eb05
---
# Decision proxy routes

The `/api/proxy` routes that list, ratify and delete the decisions the proxy made for a user, show trust, and switch the trust mode. The proxy's own logic is on [[decision-proxy]].

## What it does
- `get_pending_decisions` (`GET /pending/{user_email}`) lists pending decisions, oldest first, with `domain`, `category` and `limit` filters and a summary. The path user must be the caller, but the query has no user filter, so it lists everyone's.
- `ratify_decision` (`POST /ratify/{decision_id}`) approves or rejects one pending decision and updates the trust counters. `delete_decision` (`DELETE /decision/{decision_id}`) hard-deletes a pending one. Both take `user_email` in the query, which must be the caller.
- Both record `audit_identity`, the caller's account email from their credential, never the typed `user_email`.
- `get_trust_state` (`GET /trust/{user_email}`) returns a user's trust rows, with an optional `domain` filter. `get_decisions_by_domain_category` (`GET /decisions/{domain}/{category}`) returns history, newest first, for any credentialed caller.
- `get_current_batch_id` builds `pr-<8 hex>-<N>`. `acknowledge_batch` bumps N and returns `retired_batch` and `new_batch`. `get_proxy_batch_id` (`GET /batch-id`) and `acknowledge_proxy_batch` (`POST /acknowledge`) serve them and need a credential.
- `get_trust_mode` (`GET /mode`) returns `ini_mode`, `running_mode`, `effective` and `has_running_job`. `update_trust_mode` (`PUT /mode`) takes a `TrustModeUpdateRequest` with `mode` of `disabled`, `shadow`, `suggest` or `active`. It calls `config_mgr.put`, which `ConfigurationManager` lacks, so the INI key `swe team trust mode` is never written. The error is caught and the route still answers 200. It does set the running SWE job's proxy at once, if there is one. The reply is `status: updated` with `target: running` and `job_id`, or `status: queued` with `target: next_job`. Both `/mode` routes take any signed-in user, with no role check.
- `get_run_queue` and `get_config_mgr` are the dependencies that fetch the run queue and config manager from the main module.

## Don't
- Don't expect per-user batches. The counter is one per server process and resets on restart; any credentialed caller can retire it.
- Don't ratify twice. An approved or rejected decision answers 400, an unknown id 404.
- Don't delete a decision that is not pending. The repository refuses and the route answers 400.

## Invariants
- A path or query user other than the caller gets 403; no credential gets 401.
