# Task Reassignment + Per-Worker Task Editing — Design & Implementation Plan

**Status**: 📋 Planning — DRAFT FOR REVIEW (no implementation yet; build deferred to ≥ 2026-06-22 after review)
**Date**: 2026-06-21
**Version / branch**: v0.1.9 / `wip-v0.1.9-2026.06.19-bug-fixing`
**Author**: planning session (Rick + Claude)
**Scope**: A two-phase plan to (1) give *manager agents* a reassignment primitive and (2) give *Rick* per-worker task editing in the multiplexer UI, both on top of the unified task-store.
**Canonical architecture context**: [`src/docs/fleet-liveness-and-task-store-architecture.md`](../../../docs/fleet-liveness-and-task-store-architecture.md) (§2 the store, §6 manager/worker lifecycle).

---

## 1. Context — why this exists

The fleet runs manager/worker Claude Code sessions against the **unified task-store**
(one durable store at `:7999 /api/tasks`; three readers: the Stop-hook self-poke,
the `:8001` arbiter, and the human UI card). Two needs are surfacing as Rick
returns to dev-server work:

1. **Managers need to reassign a task from one worker persona to another** — a
   programmatic primitive a manager *agent* can invoke (e.g. pull Tiffany off a
   queue and hand her in-flight work to Marcus).
2. **Rick (the human) needs to edit tasks per worker in the multiplexer client**
   — change priority, reassign owner, and remove (drop) task items — once the
   multiplexer becomes the live client.

This document sequences those into **Phase 1** (the manager primitive) and
**Phase 2** (the human UI), with **Phase 2b** (drag-reorder) explicitly deferred.

---

## 2. Current-state map (what the code already provides)

The store is more complete than expected. Reassignment at the HTTP layer **already
exists**; the gaps are the *agent-facing verb* and the *UI controls*.

### 2.1 The two layers, and the meaning of "PATCH"

There are two surfaces, and "verb" means a different thing in each.

**Layer 1 — HTTP endpoints** ([`src/cosa/rest/routers/tasks.py`](../../../cosa/rest/routers/tasks.py)) — all exist today:

| Endpoint | Method | Mutates | Discipline |
|---|---|---|---|
| `/api/tasks` | POST | creates a row | always `status=queued` |
| `/api/tasks/{id}/transition` | POST | **`status` only** (the state machine) | `→done` needs a receipt; `→blocked` needs `blocked_by`+`next_chase_ts`; `→dropped` needs a `reason` |
| `/api/tasks/{id}/correlate` | POST | **`correlation_key` only** | respawn-adoption re-stamp |
| `/api/tasks/{id}` | **PATCH** | **`title`/`body`/`priority`/`owner_persona`/`accountable_manager`/`gate_class`** | non-terminal only; **forbidden** from touching `status`/`blocked_by`/receipts/`correlation_key` (`extra='forbid'` → 422) |
| `/api/tasks` | GET | nothing (read) | the deterministic owed-work query |

"PATCH" is overloaded: it is both the **HTTP method** (REST "partially update some
fields") and the **name of the endpoint** that edits descriptive/ownership fields.
The deliberate design split — ratified by reviewer ruling 2026-06-15, *"PATCH can
NEVER bypass the transition oracle"* ([tasks.py:402](../../../cosa/rest/routers/tasks.py)) —
is: **`transition` owns `status`; `PATCH` owns everything descriptive that is not
`status`.** Therefore **reassigning an owner is a `PATCH owner_persona` operation**,
not a transition. The `PATCH` endpoint already row-locks, rejects terminal items,
and atomically appends a `patched` audit event with the field delta
([tasks.py:396–446](../../../cosa/rest/routers/tasks.py); repo `apply_patch`
[task_repository.py:210–251](../../../cosa/rest/db/repositories/task_repository.py);
validator `validate_patch` [task_store_rules.py:338–374](../../../cosa/rest/task_store_rules.py)).

**Layer 2 — cosa-voice MCP verbs** (what agents call; transport in
[`src/lupin_mcp/task_store_tools.py`](../../../lupin_mcp/task_store_tools.py), tools
registered in `src/lupin_mcp/cosa_voice_mcp.py`):

- `task_create` → POST /api/tasks ✅
- `task_transition` → POST …/transition ✅
- `task_query` → GET /api/tasks ✅
- (`task_correlate_impl` exists in transport — the narrow respawn seam)
- **PATCH → nothing.** No transport impl, no MCP verb. **This is the Phase-1 gap.**

### 2.2 The correctness hazard reassignment must avoid — and the global normalizer it must use

`validate_patch` treats `owner_persona`/`accountable_manager` as **un-normalized
free text** (*"nullable free text — no shape rule beyond max_length"*,
[task_store_rules.py:358](../../../cosa/rest/task_store_rules.py)). But the
owed-work oracle (the worker's Stop-hook and the arbiter) compares persona names
in a **normalized** form. A manager reassigning to a hand-supplied display name
(`"reassign to María"`) stored verbatim while the oracle queries the normalized
`"maria"` would match **zero** rows → **false-idle** (precisely the 2026-06-18 P0
class this guards against). **So the reassign path must normalize the target
persona to the same canonical form every other seam uses.**

> **⚠️ DEPENDENCY — defer to Rick's global persona-normalization process; do NOT
> invent a local one.** Rick already has a dedicated plan that establishes **one
> definitive, global persona-name normalization process**, to be used in *all*
> transactions that compare persona names (store write, owed-oracle read, arbiter
> role-match, DM routing, and this reassign path). This reassign work is a
> **consumer** of that process: it calls the single global normalizer at its write
> seam and must **not** add a second/parallel scheme.
> `canonical_persona_key` ([`src/lupin_mcp/persona_normalization.py:37`](../../../lupin_mcp/persona_normalization.py))
> appears to be the current incarnation/precursor of that process; the **global
> plan is the authority** on the final API, home, and semantics. Throughout this
> doc, read "normalize" as "call the global normalizer," whatever the global plan
> finalizes it to be — the exact seam is settled there, not here (§10 Q2).
>
> **Cross-instance coordination (tomorrow):** during plan review + implementation,
> the planning and implementation Claude Code instances will share knowledge of
> the finalized global-normalization process. The implementing agent should
> **confirm the current global seam from that shared context** before wiring §4.1,
> rather than hard-coding an assumption from this draft.

### 2.3 The UI substrate (Phase 2)

The multiplexer task card is **read-only** today but the scaffolding is in place:
- [`TaskListStore.ts`](../../../lupin_app/static/js/multiplexer/stores/TaskListStore.ts) — polls `GET /api/tasks?limit=500`, 60 s timer, in-flight debounce, auth/unreachable sentinels.
- [`TaskListRenderer.ts`](../../../lupin_app/static/js/multiplexer/render/TaskListRenderer.ts) + [`taskListTable.ts`](../../../lupin_app/static/js/multiplexer/render/templates/taskListTable.ts) — owner-grouped accordion, collapse persistence, 4 render states; filters to open tasks (`isOpenStatus`).
- [`ApiClient.ts`](../../../lupin_app/static/js/multiplexer/api/ApiClient.ts) — already has `patch<T>()` and `delete<T>()`, JWT injection, 401 handling.
- **Mutation precedent to clone**: [`JobsPaneRenderer.handleDeleteClick`](../../../lupin_app/static/js/multiplexer/render/JobsPaneRenderer.ts) — delegated `.closest()` listener that survives re-render, in-flight `Set` dedupe, optimistic store update with `{ restoreState }` rollback, inline error stripe, 404-as-success.
- **Mount**: `multiplexer.html` `#task-list-pane`; wired in `boot.ts`.
- **Priority helpers**: `taskPriorityClass` / `priorityRank` in [`taskListModel.ts`](../../../lupin_app/static/js/multiplexer/render/taskListModel.ts) (`P0/P1`=high, `P2`=mid, `P3+`=low).

**Crucial layering insight:** the Phase-2 UI is a TypeScript **browser** client; it
calls the HTTP endpoints **directly** via `ApiClient` (it cannot call MCP verbs).
So the UI's reuse target is the **HTTP PATCH endpoint**, not any MCP verb — which is
why a general `task_patch` MCP verb buys no Phase-2 reuse (see §3).

---

## 3. Locked design decisions (this planning session)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Phase-1 agent verb = dedicated `task_reassign`** (not a general `task_patch`) | Matches the domain-verb naming convention (`create`/`transition`/`correlate` — never an HTTP-method name); lets persona-normalization + a required `reason` be first-class rather than conditional; the only other PATCH consumer (the browser UI) calls HTTP directly, so a general verb buys no reuse. |
| D2 | **Phase-2 reorder = P0–P3 priority buckets now; drag-to-reorder deferred to 2b** | True intra-bucket reorder needs a new ordering column + migration + drag infra (none exists in the codebase). Buckets are backend-ready (PATCH `priority`). |
| D3 | **Delete = drop-with-reason** via existing `transition`→`dropped` | Preserves the append-only audit trail (who/why); no hard-delete endpoint, no breaking the store's core invariant. Dropped items leave the open-task view automatically (`isOpenStatus` filter). |
| D4 | **`task_reassign` changes ownership only — never `status`** | The store deliberately walls PATCH off from the state machine. If a handoff should also re-queue, that is a separate `task_transition`. Keeps the two orthogonal. |
| D5 | **Persona normalization happens at the server-side PATCH write seam, by delegating to Rick's global normalizer** — not a local/parallel scheme, and not only in the verb transport | One authoritative WRITE seam covers both the Phase-1 verb and the Phase-2 UI with no drift, and it **consumes the single definitive global persona-normalization process** (the normalizer for *all* persona-name comparisons — see the §2.2 dependency note). |

---

## 4. Phase 1 — Manager reassignment primitive (`task_reassign`)

Small, self-contained, independently shippable and testable. Hardens the shared
HTTP PATCH seam that Phase 2 also rides.

### 4.1 Harden the HTTP PATCH endpoint (server-side)
- **Add optional `reason`** to `TaskPatchIn` ([tasks.py:103](../../../cosa/rest/routers/tasks.py)): `reason: Optional[str] = Field(default=None, max_length=…)`. In `patch_task`, add `"reason"` to the `model_dump(..., exclude={"actor","authority"})` exclusion set so it is **not** treated as an editable field; pass it to `apply_patch`.
- **Thread `reason` through `apply_patch`** ([task_repository.py:210](../../../cosa/rest/db/repositories/task_repository.py)): add `reason=None`; when provided, the `patched` event records it (fall back to the auto-generated field-delta string when absent).
- **Normalize the target persona on write — via the global normalizer (§2.2 dependency).** Add `normalize_patch_fields(fields)` to [task_store_rules.py](../../../cosa/rest/task_store_rules.py) (a dedicated helper → testable to 100%) that **delegates to Rick's global persona-normalization process** (currently `canonical_persona_key`; bind to whatever seam the global plan finalizes — do **not** add a second normalizer) for `owner_persona`/`accountable_manager` **only when present and non-empty** — preserve an explicit `None` (clear-the-owner) rather than collapsing it to the empty sentinel. Call it in `patch_task` right after building `fields`. The global normalizer is idempotent → safe even if a caller pre-normalizes. **The implementing agent confirms the exact global seam from the shared cross-instance context before wiring this** (§2.2 coordination note).

### 4.2 Add the `task_reassign` MCP verb
- **Transport** ([task_store_tools.py](../../../lupin_mcp/task_store_tools.py)): add `task_reassign_impl(api_base_url, api_key, actor, task_id, new_owner_persona, reason, new_manager=None)` building a PATCH body `{owner_persona, accountable_manager?, reason, actor, authority}` and calling `task_store_request("PATCH", f"/api/tasks/{task_id}", …)`. Update `task_store_request`'s docstring contract to list **PATCH** alongside GET/POST (`requests.request` already supports it). Keep transport thin; normalization is server-side (§4.1, D5).
- **MCP tool** (`cosa_voice_mcp.py`, beside the existing task verbs): register `@mcp.tool task_reassign(task_id, new_owner_persona, reason, new_manager=None, authority="manager_relay")`. `actor` is **bridge-stamped** via `_task_store_identity()` — never a param (anti-impersonation, same lane as `task_transition`). Enforce **non-empty `reason`** at the verb. Docstring: changes ownership only; cannot change status (use `task_transition`); normalizes the target so the new owner's owed-query finds the row.

### 4.3 Tests (Phase 1)
- **Unit (:7999)** — `pytest src/tests/unit/`: `normalize_patch_fields` (present / absent / explicit-null / accented cases); the new `reason` on `TaskPatchIn` + `apply_patch`; `task_reassign_impl` with a mocked `task_store_request`. Extend the existing task-store rule/endpoint suite + [`test_persona_normalization.py`](../../../tests/unit/test_persona_normalization.py).
- **Smoke** — a `quick_smoke_test()` for `task_reassign_impl`.
- **Live E2E** (route to **:8000**, since it writes rows that outlive the test, or use the transactional test-DB fixture): create a task owned by A → `task_reassign` to B → assert `owner_persona == canonical_persona_key(B)`, the `patched` event carries the `reason`, A's owed-count drops and B's rises.

---

## 5. Phase 2 — Per-worker task editing in the multiplexer (UI)

Pure consumer of the now-hardened PATCH endpoint + the existing `transition`
endpoint. **No new backend endpoints.** Scope per D2/D3: per-row **priority edit
(P0–P3)**, **reassign owner**, **drop (with reason)**.

### 5.1 `TaskListStore` mutation methods (TS)
[TaskListStore.ts](../../../lupin_app/static/js/multiplexer/stores/TaskListStore.ts) — clone the optimistic `{ restoreState }` pattern from `JobStore.delete`:
- `patchTask(id, fields)` → `api.patch('/api/tasks/{id}', {...fields, actor, authority:'user_direct'})` (priority + owner edits).
- `dropTask(id, reason)` → `api.post('/api/tasks/{id}/transition', {to_status:'dropped', reason, actor, authority:'user_direct'})`.
- `actor` = the authenticated human's display identity (e.g. `"rick (multiplexer)"`); `authority='user_direct'`. Optimistic local update; `restoreState()` on failure.

### 5.2 Renderer + template controls (TS)
- [taskListTable.ts](../../../lupin_app/static/js/multiplexer/render/templates/taskListTable.ts): per-row actions affordance — a **priority control** (P0–P3 dropdown/segmented; reuse `taskPriorityClass`), a **reassign control** (owner dropdown), a **drop button**. All DOM via `createElement` + `textContent` (no `innerHTML`), matching the existing templates.
- [TaskListRenderer.ts](../../../lupin_app/static/js/multiplexer/render/TaskListRenderer.ts): delegated click handling cloning [`JobsPaneRenderer.handleDeleteClick`](../../../lupin_app/static/js/multiplexer/render/JobsPaneRenderer.ts) — `.closest()` delegation surviving re-render, in-flight `Set` dedupe, optimistic store call, `restoreState()` + error-stripe on `ApiError`, 404-as-success. Drop prompts inline for a reason (the `→dropped` rule requires non-empty).
- **Owner dropdown roster**: populate from the same persona source the fleet-status card consumes (`renderFleetStatusTable(model, personas)`), so reassign targets are real personas, not free text.

### 5.3 Tests (Phase 2)
- **TS unit (`c8 --100`)**: new store methods (mock `ApiClient`); renderer click-delegation + optimistic/rollback (clone existing TaskListRenderer/JobsPaneRenderer tests); template rendering of the new controls.
- **E2E UI (Playwright, :8000 scheduled)**: functional test editing priority, reassigning owner, dropping a task from the card; visual snapshots for the new controls.

---

## 6. Phase 2b — Deferred (out of scope now)

True intra-bucket **drag-to-reorder per worker**: requires a new fine-grained
ordering column on `task_items` (DB field + backend write path + Alembic-style
migration) plus drag-and-drop UI. Revisit once the editable card (5.1/5.2) is
proven in use.

---

## 7. Cross-cutting notes

- **Auth / roles**: endpoints are authenticated-only by design (social + audit
  enforcement, design F4) — **no new role gate**. The verb rides the existing
  X-API-Key lane (`authority='manager_relay'`); the UI rides JWT
  (`authority='user_direct'`). The `authority` field is how provenance is
  distinguished in the audit trail.
- **Propagation**: there is **no** WebSocket emission on task change today.
  Reassigned work reaches the new owner via their Stop-hook owed-query + the
  arbiter (not instant); other UI viewers see edits on the 60 s poll, while the
  editing client sees them instantly via optimistic update. This matches the
  existing fleet-status card — **no new real-time infra in scope** (possible
  future enhancement; note it for review).
- **Docs touchpoints (per CLAUDE.md)**: after Phase 1, run
  `src/scripts/generate-api-docs.sh` (PATCH gains `reason`); update the store-API
  + MCP-verb sections of `src/docs/fleet-liveness-and-task-store-architecture.md`
  and the cosa-voice verb list with `task_reassign`.
- **100% coverage mandate**: both phases hit 100% lines/branches/functions
  (`pytest --cov-fail-under=100`; `c8 --100`).

---

## 8. Sequencing rationale

Phase 1 first: it is the smaller primitive, independently valuable (managers can
reassign immediately via the verb), and its server-side work (persona
normalization + `reason` on PATCH) is a **dependency Phase 2 reuses**, not
throwaway. Phase 2 then adds only UI consumers of the hardened PATCH endpoint and
the existing `transition` endpoint — no backend endpoints, lower risk. Phase 2b
(drag-reorder) is deferred because it is the only piece that touches the DB schema.

---

## 9. Verification summary

| Layer | Phase 1 | Phase 2 |
|---|---|---|
| Python unit (:7999) | rules helper, `reason`, `task_reassign_impl` (mocked) | — |
| TS unit (`c8 --100`) | — | store methods, renderer delegation, templates |
| Live E2E | :8000 — create→reassign→assert owner/audit/owed-counts | :8000 Playwright — edit priority / reassign / drop from card + visual snapshots |
| Manual API (:7999) | `task_reassign` via MCP on a scratch task; confirm `patched` event + canonical owner | exercise the card in-browser |

---

## 10. Review checklist / open questions (to settle before build)

1. **Human `actor` string** for UI edits — confirm the exact identity stamp (e.g. `"rick (multiplexer)"` vs. derive from the authed user/email).
2. **Global persona-normalization seam (owned by Rick's normalization plan, not decided here)** — confirm the exact global-normalizer entry point this work binds to (the §2.2 dependency), via the shared cross-instance context. Sub-question for that plan: is the *create* path (`task_create`, which does not normalize today) brought onto the same global process in the same effort, or tracked as the global plan's own work item? This reassign work simply consumes whatever the global plan establishes.
3. **`reason` max length** on `TaskPatchIn` — pick a cap consistent with `transition`'s `reason` (≈4000).
4. **Drop reason UX** in the card — inline text input vs. a small modal/confirm; is there an existing confirm pattern to reuse?
5. **Owner dropdown source** — confirm the persona roster the fleet-status card uses is the right list for reassignment targets (active personas only? include "Sam" overflow?).
6. **`new_manager` semantics** on `task_reassign` — when omitted, leave `accountable_manager` unchanged (recommended) vs. default it to the caller.
