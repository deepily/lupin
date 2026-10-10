> Part 5 of 8 of the [Lupin REST API Quick Reference](../rest-api-reference.md): routes 17c to 19: commons, proxy, mock job.

## 17c. Inter-Session Commons (`/api/commons/*`)

> **Deep-dive**: See [`../rnd/v0.1.7/2026.05.09-inter-session-commons/`](../../rnd/v0.1.7/2026.05.09-inter-session-commons/) (design + execution log) and [`notification-types.md`](../notification-types.md) §`commons_broadcast_ack` for the ack notification contract.

The commons subsystem layers two related capabilities on the same file-backed transport (`<LUPIN_ROOT>/io/commons/*.md`):

1. **Session to session commons**. Claude Code instances post to and read from a shared blackboard.
   They use the 5 cosa-voice MCP tools: `commons_post`, `commons_read`, `commons_who`, `commons_ask_sync` and `commons_ask_async`.
2. **User to all sessions broadcast**. One message from the notifications UI fans out to every active CC session of the authenticated user.
   Directive parsing is persona-aware (`@PersonaName:` lines).

The endpoints below cover surface #2. The MCP tools are surface #1 and are not REST endpoints.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/commons/active-sessions`           | JWT | Returns same-user-scoped active CC sessions for the broadcast recipient preview. Same-user filter (per `user_id` on each bridge file) + freshness filter (`commons broadcast active session threshold seconds`, default 600). Response: `{ sessions: [{ session_id, sender_id, persona_name, persona_icon, persona_color, last_seen_iso, speakerphone_on }] }`. Never leaks bridge filesystem paths. `sender_id` (**added**) is the notification routing key `claude.code@<project>.deepily.ai#<hash8>`, derived from the bridge's `cwd` via `detect_project_for_path`. A client cannot rebuild it from `session_id` alone because the project segment differs per seat (`@lupin`, `@lupin-mobile`, `@plan`). It is `null` when the bridge carries no usable `cwd`, never a guess. Consumer: the phone seeds its focus rail from this roster so a live seat appears before it has ever notified the user. |
| POST | `/api/commons/broadcast-to-cc-sessions`  | JWT | Fans out a message to every active CC session belonging to the caller. Body: `{ message, broadcast_id?, require_ack=true, include_originator=true }`. Rate-limited at 1 broadcast per `commons broadcast rate limit seconds` (default 30) per `user_id`; exceeded → `HTTP 429` with `Retry-After` header. Body containing literal `<system-reminder>` / `</system-reminder>` substring → `HTTP 400`. Caller-supplied `broadcast_id` colliding with an in-flight broadcast → `HTTP 409`. Zero recipients → `HTTP 200` with `status="no-active-sessions"`. Success → `HTTP 200` with `{ broadcast_id, recipients, failed_recipients, filtered_out, status="queued" }`. `filtered_out[]` (** fanout receipts**) lists every enumerated session the recipient filter dropped. `{ session_id, reason }`, reason ∈ `bridge_unreadable` / `owner_mismatch` / `stale_bridge_mtime` (adds `age_seconds` + `threshold_seconds`) / `bridge_vanished` / `originator_excluded`. Present in both 200 shapes so a silent miss is visible to the sender. When `require_ack=true`, downstream `commons_broadcast_ack` notifications stream in via the existing `notification_queue_update` envelope as each recipient listener acks. |
| GET    | `/api/commons/broadcast-history`         | JWT | Aggregates entries across all commons topics and returns them newest-first, scoped to the authenticated user. The configurable blacklist defaults to `presence` and `system-events`. It powers the broadcast-card Recent Activity admin-oversight stream. Query params: `since` (ISO cutoff), `hours` (back-window from now) and `limit` (default 200, capped server-side by `commons traffic visibility max entries per response`, default 1000). Response: `{ entries: [{ ts, topic, topic_kind: "reserved"\|"free-form", sender_session_id, persona_name, persona_icon, persona_color, body, metadata }], since_used, next_cursor }`. When the master INI flag `commons traffic visibility enabled` is False, it returns `{ entries: [], since_used: null, next_cursor: null, disabled: true }`. Same-user scoping mirrors `/active-sessions`. Un-stamped legacy bridges degrade gracefully (`owner_user_id == None` passes through). |

### Broadcast directive parsing

`message` body is free-form text with optional `@PersonaName:` directive lines:

```text
Run the daily smoke check on master.
@Maria: also re-baseline the visual snapshots.
```

Default lines (no leading `@`) apply to every recipient. `@PersonaName:` lines apply only to sessions whose persona matches (case-insensitive + punctuation-tolerant per `commons_persona_matcher.match_persona`). `@all:` / `@everyone:` aliases match the default scope. Sessions whose persona doesn't match any `@` line — and the body has no default lines — ack with `status="skipped"`.

### Ack flow

When `require_ack=true`:

1. Server registers the `broadcast_id` in the `CommonsAckWatcher` in-flight tracker (5-min TTL).
2. Per-recipient fanout writes one entry to the `broadcasts` reserved topic + pushes one `user_initiated_message` notification with `title="action:broadcast_received"` to each listener.
3. Each listener's `_handle_action()` dispatcher routes to `broadcast_handler.handle_broadcast()`.
   That handler parses the directive and injects the effective text as a `<system-reminder>` block.
   It then posts an ack to the `broadcast-acks` reserved topic.
4. The `CommonsAckWatcher` daemon polls every `commons broadcast ack watch interval seconds` (default 1) and tails `broadcast-acks`.
   It dispatches one `commons_broadcast_ack` notification per ack to the originating user.
   [`notification-types.md`](../notification-types.md) gives the payload shape.

When `require_ack=false`, the first three steps still happen. No acks fan back to the user, and the watcher's in-flight tracking is skipped for this broadcast.

### INI configuration

| Key | Default | Effect |
|---|---|---|
| `commons broadcast rate limit seconds` | `30` | Per-user sliding-window rate limit |
| `commons broadcast active session threshold seconds` | `600` | Inactivity threshold (s) — sessions older than this are excluded from fanout |
| `commons broadcast ack watch interval seconds` | `1` | Poll period for the `CommonsAckWatcher` daemon |

Paired splainer entries are in `src/conf/lupin-app-splainer.ini`.

## 18. Decision Proxy (`/api/proxy/*`)

> **Deep-dive**: See [`proxy-admin-guide.md`](../proxy-admin-guide.md)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/proxy/acknowledge` | Credential | Retire current batch, start new one. Gated; no owner check — see the note below |
| GET | `/api/proxy/batch-id` | Credential | Get current proxy batch ID. Gated |
| GET | `/api/proxy/pending/{user_email}` | Owner | Get pending decisions. Owner-only — 401 without a credential, 403 if the path names another user. It was `Public`, and an uncredentialed call really did return 200 |
| POST | `/api/proxy/ratify/{decision_id}` | Owner (query) | Approve or reject decision. Owner-only — 401 without a credential, 403 if `?user_email=` names another user. `ratified_by` is taken from the credential, not from that parameter |
| DELETE | `/api/proxy/decision/{decision_id}` | Owner (query) | Hard-delete decision. Same gate as `/ratify`; `deleted_by` likewise comes from the credential |
| GET | `/api/proxy/trust/{user_email}` | Owner | Get trust state for user. Owner-only — same gate as `/pending` |
| GET | `/api/proxy/decisions/{domain}/{category}` | Credential | Decision history by domain/category. Gated |
| GET | `/api/proxy/mode` | JWT | Get current trust mode |
| PUT | `/api/proxy/mode` | JWT | Update trust mode |

✅ **All nine rows are gated, measured at the path**.
Driving the real router with no credential, every one of the nine now answers **401**.
Five did not before: `batch-id`, `acknowledge`, `ratify`, `decision` and `decisions/{domain}/{category}`.
Two of those five had reached the **database**.
A bare call to `ratify` or `decision` answered 422 for the missing `user_email`, which reads like a refusal and is not one.
A well-formed call returned "Decision … not found".
So an uncredentialed caller could ratify or hard-delete any decision by id, naming any victim's email in a **query** parameter.

Two things had to change together.
`require_path_identity_owner` reads `path_params` and raises 500 for a route naming no user in its path.
It cannot cover a `user_email` that arrives in the query string.
`require_query_identity_owner` is its sibling in the same module, with the same 401/403 semantics, reading `request.query_params`.
And `batch-id` had been left open because of one uncredentialed server-to-server caller in `swe_team/orchestrator.py`.
That caller now sends its API key, so the route could be gated.

Warning: **`acknowledge` carries no owner check, and that is a residue rather than a completed fix**.
It takes no identity parameter anywhere.
`_proxy_batch_state` is one process-global counter, not a per-user record, so nothing in the request can be owned.
Any credentialed caller can still retire another user's displayed batch.
Making the batch per-user is a design change.

Warning: **the `ratified_by` and `deleted_by` columns were writing a claim, not a fact**.
The ownership check alone does not repair that.
The guard accepts the caller's bare user id and compares email without regard to case.
So one person could write three different strings into the same column, and into the trust-state key.
A counter split across two spellings of one user is a wrong answer, not a cosmetic one.
Both handlers now take the audit identity from the credential.

## 19. Mock Job (`/api/mock-job/*`)

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/mock-job/submit` | — | 🪦 **Gone (410)**. Use `/api/v2/submit` with `"agent router go to mock job"` (args in `args`; `scheduled_at` / `monopolize` top-level; config comes back in `submit_details.config`). Remove by end of 2026. |
| GET | `/api/mock-job/health` | Public | Mock job subsystem health |
