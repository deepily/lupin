# Task-Store MCP Wrapper Spec — task_create / task_transition / task_query

**Date**: 2026.06.11 (EDT)
**Author**: Krishna 🦚 (Lane 2, task-store crew) — named MCP-wrapper owner (design C5)
**Status**: IMPLEMENTED 2026-06-12 (Sam 🎙️, held commits on `wt-sam-taskstore-mcp-2026.06.12`)
— **location correction**: there is NO standalone cosa-voice repo on the host (the
doc-viewer registry path `/var/external-projects/cosa-voice` is stale); the cosa-voice
MCP server lives IN-TREE at Lupin `src/lupin_mcp/`, and the implementation landed there
(`task_store_tools.py` transport + tool shims in `cosa_voice_mcp.py`) per Tiberius's
revised directive under Rick's D4 authorization. See §6 Amendments.
**Canonical design**: planning-is-prompting → `src/rnd/2026.06.11-unified-task-store-design.md` (v0.4) §2.2.

---

## 1. Purpose

Design §2.2: MCP wrappers so any session uses the task store as naturally as
`notify()`. Arbiter + hooks use REST directly; sessions get three thin tools.
Wrappers are TRANSPORT only — every structural rule lives server-side in
`cosa.rest.task_store_rules`; the wrapper never pre-validates (no rule
duplication, no drift).

## 2. Tool surface

All three call `:7999 /api/tasks/*` with the session's existing auth lane
(the cosa-voice server already holds credentials for `/api/notify` etc. —
same client, same key).

### 2.1 `task_create`

| Param | Type | Required | Maps to |
|---|---|---|---|
| `item_class` | str | yes | `POST /api/tasks` body `item_class` (task\|decision\|review_request\|bug\|gate) |
| `title` | str | yes | `title` |
| `project` | str | yes | `project` |
| `body` | str | no | `body` (decision framing payload lives here) |
| `owner_persona` | str | no | `owner_persona` |
| `accountable_manager` | str | no | `accountable_manager` |
| `gate_class` | str, default `"none"` | no | `gate_class` |
| `priority` | str, default `"P2"` | no | `priority` |
| `source_qid` | str | no | `source_qid` |
| `correlation_key` | str | no | `correlation_key` |
| `authority` | str, default `"standing"` | no | `authority` |

`created_by` is NOT a caller param — the wrapper stamps it from the session
bridge (`persona_name + " " + session_id`, e.g. `"krishna 38d15e3b"`), the
same identity stamping `commons_post` uses. A session cannot impersonate.

Returns: the serialized item dict (201 body) verbatim.

### 2.2 `task_transition`

| Param | Type | Required | Maps to |
|---|---|---|---|
| `task_id` | str (uuid) | yes | path `{task_id}` |
| `to_status` | str | yes | `to_status` |
| `receipt_refs` | dict | no (REQUIRED server-side for `done`) | `receipt_refs` |
| `next_chase_ts` | str ISO-8601 | no (REQUIRED server-side for `blocked`) | `next_chase_ts` |
| `blocked_by` | list of `{kind, id}` | no (REQUIRED server-side for `blocked`) | `blocked_by` |
| `reason` | str ≤4000 | no (REQUIRED server-side for `dropped` once Phase-2 C12 lands — §6 B) | `reason` |
| `authority` | str, default `"standing"` | no | `authority` |

`actor` stamped from the session bridge, same as `created_by` above.

Returns: `{ item, event }` (200 body) verbatim. A 422 surfaces the server's
`detail.errors` list VERBATIM in the tool error — the no-confabulation
rejection text reaches the model unedited.

### 2.3 `task_query`

| Param | Type | Required | Maps to |
|---|---|---|---|
| `owner_persona` | str | no | query param |
| `status` | str | no | query param |
| `gate_class` | str | no | query param |
| `accountable_manager` | str | no | query param |
| `project` | str | no | query param |
| `item_class` | str | no | query param |
| `correlation_key` | str | no | query param (exact match — §6 C) |
| `limit` / `offset` | int | no | query params |

Returns: `{ tasks, count }` verbatim. Convenience: `task_query()` with no
args = "everything, newest first" — the manager board glance.

## 3. Tier markers (cosa-voice docstring convention)

- `task_query` — **[READ]** always allowed.
- `task_create` / `task_transition` — **[SELF-DISCLOSURE]** tier (F4
  managers-first WRITE practice is enforced socially + by the audit trail,
  not by tool gating — design §2.2 role model, enforcement-light v1).

## 4. Failure modes

- `:7999` unreachable → tool returns explicit error; callers NEVER block a
  Stop-hook path on it (I1 — the oracle's fail-open is hook-side, not here).
- HTTP 422 → error carries `detail.errors` verbatim (see 2.2).
- HTTP 404 → "task {id} not found" verbatim.

## 5. Naming collision note

Phase-2+ backlog C-item already tracks `taskstore_*` tool-name-collision
review (harness has native TaskCreate/TaskList). The MCP tool names here are
snake_case (`task_create`) vs harness PascalCase (`TaskCreate`) — distinct
strings, but the collision review may still rename; this spec follows
whatever that review rules.

## 6. Amendments (2026-06-12, Tiberius-ruled GO, per Phase-2 contract §1.11)

The Phase-2 write-path build (`src/rnd/v0.1.8/2026.06.12-task-store-phase2-write-paths/01-build-plan.md`)
extends the REST surface this spec wraps. Ruled wrapper impact:

- **(B) `task_transition` gains optional `reason` (str, ≤4000)** — passes
  through verbatim. Server-REQUIRED non-empty for `→dropped` once the C12
  pull-forward lands; the pre-Phase-2 server ignores the field (backward-safe).
  Practice rule (task-store-discipline.md §4): give one on every `→dropped`
  regardless.
- **(C) `task_query` gains optional `correlation_key`** — exact-match filter,
  mirrors the REST addition; pre-Phase-2 server ignores it.
- **(A) `POST /api/tasks/{id}/correlate` wrapper exposure: DEFERRED to
  Phase-2.1** — no session-facing consumer named; the hook lane consumes it
  via REST directly. Recorded here so the gap is a decision, not a discovery.
