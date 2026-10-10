> Part 7 of 8 of the [Lupin REST API Quick Reference](../rest-api-reference.md): task store promote and demote requests, and the CC transcript console (sections 26 and 27).

## 26. Task Store — Promote/Demote Requests (`/api/tasks/*`)

Managers ask Rick to move a row, and only Rick answers.

**Sword of Damocles**: while `sword_of_damocles_active` is on, an admit must pledge one live ticket the requester owns.
Rick's approval drops the pledge in the same transaction as the admit.
Ownership is checked against the persona the server resolves (approver account, else the session bridge), never the typed actor.
Plan: `src/rnd/v0.2.1/2026.09.14-sword-of-damocles-enforcement-plan.md`. Full schemas: `/docs`.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/tasks/{task_id}/request` | API Key / JWT (managers) | File a request. Body `{ move: admit\|demote, reason, actor, deletion_task_id? }`. 422 an admit with no pledge while the switch is on, a pledge on a demote, or a self/nonexistent pledge · 403 not a manager or not your ticket · 409 pledge finished or already pledged on another pending admit. A pending admit whose pledge died may be re-filed. |
| POST | `/api/tasks/{task_id}/unpark-ask` | API Key / JWT (managers) | Ask the operator to approve un-parking a parked row. Body `{ actor }`. The server makes the card (bound to this row and the move parked to queued) and returns `{ card_id, task_id, expires_at, pushed }` (`pushed` false means the card is saved but the push to the operator failed). After a yes the manager cites the id as the `approval_card` receipt on the `parked -> queued` transition. 403 not a manager · 404 unknown row or operator account · 409 the row is not parked, has no recorded park time, or an unanswered card for this row and park already exists (its id is in the message). |
| POST | `/api/tasks/{task_id}/request-verdict` | JWT (operator account) | Rick's verdict. `approved` performs the move and drops the pledge, both or neither. A dead pledge is 409 and the request stays pending. `denied` touches neither row. |
| GET | `/api/tasks/request-badges` | API Key / JWT | Pending counts `{ task_area, holding_area }` — never summed. |
| PATCH | `/api/tasks/approval-settings` | JWT (operator account) | Rick flips `{"sword_of_damocles_active": true\|false}`. Lands on the next request, no bounce. `GET` shows the value and its source. |

---

## 27. CC Transcript Console (`/api/cc-transcript/*`)

A read-only live window onto what a Claude Code seat is printing.
The source is the seat's **transcript JSONL file**, tailed by byte offset.
The live channel is the existing `/ws/queue` socket, not a new one.
Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`.
Deep-dive: [`websocket-events.md`](../websocket-events.md) § "CC Transcript Console Events".

**Status**: the contract is documented, and the routes land in the first build phase.

**Why `cc-transcript` and not `transcript`**: "transcript" already means speech-to-text on this API.
That covers `/api/v2/transcribe`, `/upload-and-transcribe-{mp3,wav}` and the `transcript` line of an STT NDJSON stream.
The `cc-` prefix cannot be read as speech.

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/cc-transcript/{cc_session_id}` | **Admin** | Backlog and gap repair. Returns `{ file_epoch, offset, next_offset, blocks[] }`. A `tool_call` block carries the tool's `name`, as on the WebSocket frame. A `tool_result` carries its call's `name` when that call is inside the same page, else no `name`. |
| GET | `/api/cc-transcript-roster` | **Admin** | Watchable-seat roster — a **projection** of `/api/arbiter/fleet-state` plus `project`, `last_ts` and `transcript_watchable`. |

**Why the roster is a sibling path and not `/api/cc-transcript/roster`**.
A literal segment under the same prefix collides with `{cc_session_id}`.
`/api/cc-transcript/roster` matches the parameterised route too, and which route wins depends on declaration order.
That resolves correctly today and breaks silently the first time someone reorders the decorators.
The symptom would be a roster request answered as a lookup for a seat literally named "roster".
A sibling path cannot collide at all.

**`cc_session_id` is the seat's `stable_session_id`** — the full id that survives a `/clear`, never the 8-character form used by `sender_id` or a DM's `recipient_session_hash8`.

### Reading the backlog — three query shapes, and one of them reads backwards

The backlog contract is "since the last `/clear`, capped near 64 KB, with load-earlier".
**A forward-only contract cannot express that**.
`?since_offset=0&max_bytes=65536` returns the **first** 64 KB of a file. And the contract wants the **last** 64 KB.
Hence an explicit tail mode and a backward page.

| Query | Direction | Use |
|---|---|---|
| `?tail_bytes=N` | **backward from EOF** | the open — the last N bytes |
| `?before_offset=N&max_bytes=M` | **backward from N** | "load earlier" |
| `?since_offset=N&max_bytes=M` | forward from N | gap repair after a dropped frame |

Every response lands on **complete-line boundaries**, and `next_offset` is always the end of a complete line.

**Every page makes progress; the byte cap is a target, not a hard limit**.
When a window holds no complete record because the record at its edge is larger than the cap, that one record is returned whole.
This holds for all three verbs.
Before that, a backward page came back empty at the same offset, and "load earlier" stayed stuck behind any record over 64 KB.
An empty `( [], 0, 0 )` from `before_offset` now means only one thing: the top of the file.

### The roster is a projection, and its gate is its own

`/api/arbiter/fleet-state` is guarded by `require_api_key_or_jwt`, which is **looser than admin**.
The console is admin-only, so the roster projection carries **its own `require_admin` gate** rather than inheriting fleet-state's.
Assert against the projection, never against `/arbiter/fleet-state`.

`transcript_watchable` is **false** for a seat with no live transcript, and false for a non-admin caller.

**An unreachable arbiter is not an empty fleet**.
`/arbiter/fleet-state` answers **HTTP 200** with `{ "status": "unreachable", … }` when `:8001` is down: the proxy is up and the upstream is not.
The projection must report *unreachable*, not an empty roster.
The two must be distinguishable in the response.

### Access, and what the stream carries

**Admin only, with no redaction in v1**.
Both surfaces enforce it, with **two different gates**.
`require_admin` guards these REST routes, and `websocket_manager.session_is_admin[ session_id ]` guards the WS verbs.
Both gates matter: a test that exercises one proves nothing about the other.

The stream carries everything the seat read — file contents, tool output, possibly secrets from a `.env` or a log. A hidden UI entry point is a courtesy, not a gate. Revisit before mobile goes off-LAN.

Warning: **The positive admin arm is proved at the override tier, not against the live auth stack**.
The only admin accounts are `admin@lupin.deepily.ai` and Rick's own, and **the fleet holds neither password**.
So no test in this repo has ever watched an admin *succeed*, only a non-admin fail.
Rick ruled that v1 ships on the `dependency_overrides[ require_admin ]` positive arm, with a dev-only test admin account as a separate follow-up.
That proves the route **wiring**, not the live gate. It is stated here, not rounded down to "tested".

### Configuration

Six INI keys, all in `src/conf/lupin-app.ini`.
Three carry Rick's ruled values. Three are defaults chosen by the implementer, to be moved without a code change.

| Key | Default | Source |
|---|---|---|
| `cc transcript poll interval seconds` | `0.25` | implementer default |
| `cc transcript watcher grace seconds` | `30` | implementer default |
| `cc transcript coalesce window ms` | `300` | **ruled** |
| `cc transcript backlog tail bytes` | `65536` | **ruled** (about 64 KB) |
| `cc transcript block budget bytes` | `8192` | implementer default; **`0` means unbounded**, not zero |
| `cc transcript ring buffer bytes` | `262144` | implementer default |

**The ring is bounded in bytes, not in records**.
`arbiter_state.FleetEventAccumulator` has the right *shape*: session id to a bounded per-session tail.
But it is bounded in records (`DEFAULT_TAIL_MAXLEN = 50`), and a record-count ring cannot answer a byte-offset question.
The server could not say which `from_offset` values it is able to serve.
The ring therefore carries the offset span it holds, and a `from_offset` outside that span is answered by pointing the client at REST.

---
