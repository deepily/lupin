---
capability: commons-and-dm
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.routers.dm.execute_dm_send@cbaf166922
  - cosa.rest.routers.dm.execute_dm_list@abb50bbea6
  - cosa.rest.routers.dm.get_dm_tutor_config@2742482adc
  - cosa.rest.dm_experiment.is_suspended@8c79f0a3f4
  - cosa.rest.routers.commons.execute_broadcast@0dc3cdefd1
  - cosa.rest.commons_rate_limiter.CommonsBroadcastRateLimiter.check_and_record@a165857116
  - cosa.rest.commons_ack_watcher.CommonsAckWatcher.register_broadcast@5bc5f28af0
  - cosa.rest.commons_topic_watcher.CommonsTopicWatcher@47427345f1
---
# Commons and DM (REST side)

The server half of cross-session messaging: the operator's broadcast to Claude Code sessions, and AI-to-AI direct messages. The MCP tools that call these routes are in [[mcp-commons-and-dm]].

## What it does
- `routers.commons` serves `GET /api/commons/active-sessions`, `POST /api/commons/broadcast-to-cc-sessions` and `GET /api/commons/broadcast-history`. `execute_broadcast` posts to the `broadcasts` topic and pushes a `broadcast_received` action to each recipient.
- `CommonsAckWatcher` tails `broadcast-acks` and pushes an ack notification to the user who sent a broadcast. `CommonsActivityWatcher` tails every topic except the excluded ones and pushes a `commons_activity` event per entry. Both subclass `CommonsTopicWatcher`, which owns the daemon thread, the lock and the in-flight registry.
- `routers.dm` serves `POST /api/dm/send`, `/respond`, `GET /api/dm/get`, `/list`, and three audit routes (`project-audit`, `length-audit`, `quality-audit`). A DM is an ordinary notification with `direction="ai_to_ai"` and its body inline, routed by `job_id` to the recipient's listener.
- On the baseline path, which is the only live one while the pilot is suspended, `/api/dm/send` runs the DM tutor first: a body over the claim trigger (`dm tutor trigger claims`) is distilled by a model before it is stamped, stored and pushed. It runs only when `dm tutor enabled` is true: the code default is false, and `[Lupin: Baseline]` sets it true. The `routers.peer` routes (`/api/admin/peer-queue*`) are an admin-only proxy that lets `:7999` read and watch the queues of a peer server.

## Invariants
- A send resolves the recipient within the caller's own account. An unresolved recipient answers 422, and a send with no `sender_project` also answers 422, because the server cannot know the caller's project.
- A 201 from `/api/dm/send` means persisted and queued, never read: `dispatched` is true and `delivery_confirmed` is false. `recipient_session` is the full session id and `recipient_session_hash8` the 8-character form that `/api/dm/list` filters on; they are different values.
- The quality grade is queued to a worker and pushed back to the sender later, so the 201 has no `quality` key. The tutor rewrite is the one model call that does run before the send.
- `/api/dm/list` answers 400 for a malformed `since` or a `session_id` shorter than 8 characters, and 422 for a `scope` that is not `session` or `account`. Without a usable `session_id` the read is account-wide, and the response's `scope` field says so.
- The broadcast rate limit is per user and held in one process's memory (`commons broadcast rate limit seconds`, 30 in the INI). A second worker would give each its own window. A refusal is HTTP 429 with `Retry-After`.
- The ack watcher keeps a broadcast in flight for 300 seconds by default. `register_broadcast` raises `ValueError` on an id already in flight.
- The two-arm DM pilot is off while `dm experiment suspended` is true, which is its default and also the result of any config-read failure. A missing or malformed schedule file makes it inactive, never an error.

## How to extend
- Write a new topic watcher as a subclass of `CommonsTopicWatcher`: provide the cursor seed and `tick()`, and dispatch outside the lock.
- Keep route handlers thin and put the logic in a pure `execute_*` function that takes its dependencies as arguments.
