# Build Plan — `notify_peer` → `dm_send` Global Rename

**Date:** 2026-06-15 · **Author:** cosa-voice session `05fc8fb3` (Tiberius-spawned plan-doc author) · **Status:** ready for implementer crew.
**Builds on:** [`00-naming-analysis.md`](./00-naming-analysis.md) (verdict: RENAME not merge; all in-tree; canonical `dm_send` / `POST /api/dm-send`; field `asker_session_id` → `sender_session_id`; three-unit coordinated cutover, NO shim).
**Baseline commit:** `5ce5dba5` (`cosa-voice Phase 4 — comment-out legacy commons-DM machinery + arbiter→notify-peer migration`). Build directly on top of this so the arbiter's brand-new `notify_peer` references are renamed in the same sweep.
**Related design docs (token-reduction lineage this rename completes):**
- [`../2026.06.13-cosa-voice-token-reduction/01-dm-body-in-push-phase1-design.md`](../2026.06.13-cosa-voice-token-reduction/01-dm-body-in-push-phase1-design.md) — body-inline DM push (Phase 1).
- [`../2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md`](../2026.06.13-cosa-voice-token-reduction/02-notification-native-aixai-design.md) — notification-native AI↔AI design.
- [`../2026.06.13-cosa-voice-token-reduction/03-phase4-legacy-commons-dm-retirement-proposal.md`](../2026.06.13-cosa-voice-token-reduction/03-phase4-legacy-commons-dm-retirement-proposal.md) — Phase-4 legacy-commons-DM retirement.

---

## 1. Context & Goal

The notification-native AI↔AI DM path currently wears **three divergent vocabularies** across its single transport chain:

- `dm_send` / `dm` — MCP tool + reply affordance + listener handler + global CLAUDE.md (the user-facing, newer, "PREFERRED" surface).
- `notify_peer` / `notify-peer` — the HTTP route + arbiter client (the minority, legacy surface).
- `peer_dm` — the recipient-side listener/hook framing (internally consistent; **out of scope** for Phase 1 — see §8).

There is exactly **one implementation** behind these names (transport-of relationship, [`00`](./00-naming-analysis.md) §3):

```
MCP dm_send → _dm_send_impl → POST /api/notify-peer
   → post_notify_peer → execute_notify_peer
   → _resolve_dm_recipient + _persist_peer_notification_sync + push_notification(direction='ai_to_ai')
```

The arbiter (`:8001`) is a **second client** of the same `/api/notify-peer` endpoint.

**Goal:** converge the divergent `notify_peer`/`notify-peer` HTTP+arbiter vocabulary UP onto the canonical `dm_send` / `POST /api/dm-send` name at every layer, with **no alias, no shim, no back-compat route** — one global rename in one commit, landed by one coordinated three-unit cutover.

---

## 2. One-Name Doctrine & Chosen Canonical Name

Rick's one-name doctrine ([[feedback_one_descriptive_name_everywhere_break_contract]]): **ONE function-revealing name at every layer** — class / field / log / route / contract — with **no mapping, alias, or shim**. When we own all consumers (we do — [`00`](./00-naming-analysis.md) §3 boundary finding: the MCP server `src/lupin_mcp/cosa_voice_mcp.py` is in-tree and IS the live `claude mcp get cosa-voice` registration), we rename the bad contract **globally**. "Break everything and do it right."

**Canonical choices:**

| Concern | Canonical name | Why |
|---|---|---|
| Verb / concept | **`dm` / "DM"** | Names a *directed, threaded peer message* (recipient + body + `reply_to`/`thread_id`) exactly. `notify_peer` reads fire-and-forget — wrong shape. |
| MCP tool | `dm_send` (already canonical — **keep**) | Dominant user-facing vocabulary; docstrings already say "PREFERRED". |
| HTTP route | **`POST /api/dm-send`** | Mirror the tool 1:1. |
| Sender field | **`sender_session_id`** (rename `asker_session_id`) | "asker" is leftover *commons-question* vocabulary — wrong domain for a DM. |
| Recipient field | `recipient` (+ `recipient_session_id`) — already canonical, **keep** | |
| Body / threading | `body`, `reply_to`, `thread_id` — already aligned, **keep** | |

**Converge UP to `dm`.** `dm_send` already dominates (tool, reply affordance, listener handler, global CLAUDE.md); `notify_peer` survives only in the HTTP route + arbiter — the minority renames to match the majority.

---

## 3. Ordered Rename Checklist (by phase)

> Verified against the working tree at `5ce5dba5` on 2026-06-15. Line numbers are anchors — implementers should re-grep each symbol before editing (the checklist below pairs each phase with a verification grep).

### Phase A — HTTP endpoint + handlers (`src/cosa/rest/routers/notifications.py`)

| Line | Current | Rename to | Notes |
|---|---|---|---|
| `:2815` | `class NotifyPeerRequest( BaseModel )` | `class DmSendRequest( BaseModel )` | |
| `:2817` | docstring `POST /api/notify-peer …` | `POST /api/dm-send …` | |
| `:2826` | field `asker_session_id` | **`sender_session_id`** | Pydantic field rename — drives B + C payload keys. |
| `:2836` | `def _persist_peer_notification_sync(` | `def _persist_dm_send_sync(` | consistency rename. |
| `:2874` | `def execute_notify_peer(` | `def execute_dm_send(` | pure-logic core. |
| `:2885` | docstring `POST /api/notify-peer …` | `POST /api/dm-send …` | |
| `:2893` | docstring `body is a NotifyPeerRequest` | `body is a DmSendRequest` | |
| `:2897` | docstring `build_sender_id( asker_session_id )` | `build_sender_id( sender_session_id )` | |
| `:2922` | `build_sender_id( body.asker_session_id )` | `build_sender_id( body.sender_session_id )` | call-site of renamed field. |
| `:2967` | route `"/notify-peer"` + summary/description | `"/dm-send"` | the route string + OpenAPI summary/description text. |
| `:2971` | `async def post_notify_peer(   # pragma: no cover` | `async def post_dm_send(   # pragma: no cover` | **PRESERVE the `# pragma: no cover`** on the wrapper (see §5). |
| `:2972` | `body: NotifyPeerRequest` | `body: DmSendRequest` | |
| `:2996` | `execute_notify_peer,` | `execute_dm_send,` | reference inside the wrapper. |
| `:3002` | `persist_fn = _persist_peer_notification_sync,` | `persist_fn = _persist_dm_send_sync,` | |

**Verify A:** `grep -n "notify.peer\|NotifyPeer\|asker_session_id\|_persist_peer_notification_sync" src/cosa/rest/routers/notifications.py` → must return **zero** hits after Phase A.

### Phase B — MCP client (`src/lupin_mcp/cosa_voice_mcp.py`)

| Line | Current | Rename to | Notes |
|---|---|---|---|
| `:3054` | comment `direction='ai_to_ai' … (POST /api/notify-peer)` | `… (POST /api/dm-send)` | |
| `:3093` | error string `… cannot reach /api/notify-peer` | `… cannot reach /api/dm-send` | |
| `:3096` | payload key `"asker_session_id" : session_id` | `"sender_session_id" : session_id` | **must match Phase A field rename.** |
| `:3108` | `url = f"{api_base_url}/api/notify-peer"` | `f"{api_base_url}/api/dm-send"` | the live POST target. |
| `:592`, `:711` | `instructions` payload + docstring `/api/notify-peer` mentions | `/api/dm-send` | only the `/api/notify-peer` literal mentions. |

> The tool `dm_send` (`:3126`) and `_dm_send_impl` (`:3061`) are **already canonical — keep**.

**Verify B:** `grep -n "notify-peer\|asker_session_id" src/lupin_mcp/cosa_voice_mcp.py` → zero hits.

### Phase C — Arbiter (`src/lupin_arbiter_app/`)

`arbiter_live_notify.py`:

| Line | Current | Rename to | Notes |
|---|---|---|---|
| `:18` | comment `the DM PUSH hop … POST /api/notify-peer` | `… POST /api/dm-send` | |
| `:49` | comment `POST /api/notify-peer — §3.3` | `POST /api/dm-send — §3.3` | |
| `:51` | `NOTIFY_PEER_PATH = "/api/notify-peer"` | `DM_SEND_PATH = "/api/dm-send"` | module constant — drives `:364`. |
| `:302` | `def build_notify_peer_payload(` | `def build_dm_send_payload(` | |
| `:307`, `:338` | param `asker_session_id` | `sender_session_id` | both signatures (builder + `make_dm_push_fn`). |
| `:310`, `:313`, `:322` | docstrings naming `notify-peer` | `dm-send` | |
| `:327` | payload key `"asker_session_id"` | `"sender_session_id"` | **must match Phase A field rename.** |
| `:364` | `url = f"…{NOTIFY_PEER_PATH}"` | `f"…{DM_SEND_PATH}"` | |
| `:368`, `:370` | call `build_notify_peer_payload( … asker_session_id=… )` | `build_dm_send_payload( … sender_session_id=… )` | |
| `:471–472` | comment `/api/notify-peer` + `build_notify_peer_payload( … asker_session_id=… )` | `dm-send` / `build_dm_send_payload( … sender_session_id=… )` | |

**Caller correction (vs `00` §C):** the consumer of `make_dm_push_fn` / `build_*_payload` is **`src/lupin_arbiter_app/app.py:397–420`** (`from lupin_arbiter_app.arbiter_live_notify import ( make_notify_transport, make_live_notify_fn, make_dm_push_fn, … )` then `dm_push_fn = make_dm_push_fn( … )`), **not** `arbiter_job.py` as `00` stated. Update the import line + the `make_dm_push_fn(...)` call site in `app.py` (the import list pulls `make_dm_push_fn`, which is unchanged in name; only verify no `build_notify_peer_payload`/`NOTIFY_PEER_PATH` symbols are imported there).

**Verify C:** `grep -rn "notify.peer\|NOTIFY_PEER\|build_notify_peer_payload\|asker_session_id" src/lupin_arbiter_app/` → zero hits.

### Phase D — Tests (move + rename in lockstep)

| Action | From | To |
|---|---|---|
| **git mv + rename symbols** | `src/cosa/tests/unit/rest/test_notify_peer.py` | `src/cosa/tests/unit/rest/test_dm_send_endpoint.py` |
| edit | `src/tests/unit/test_arbiter_live_notify.py:24,242,250` | builder import rename + rename `test_dispatched_201_posts_notify_peer_with_body` → `…_posts_dm_send_with_body` |
| edit | `src/tests/unit/test_arbiter_outreach_receipts.py:285,289` | `"notify-peer"` → `"dm-send"` |
| edit | `src/tests/unit/lupin_mcp/test_dm_send.py:65` | URL assertion `/api/notify-peer` → `/api/dm-send` |
| edit | `src/tests/unit/commons/test_commons_ac14_registration.py:60` | comment |
| edit | `src/tests/smoke/test_ask_async_push_e2e.py:38,46` | comment strings |

Inside the moved `test_dm_send_endpoint.py`: `execute_notify_peer` → `execute_dm_send`, `NotifyPeerRequest` → `DmSendRequest`, `_persist_peer_notification_sync` → `_persist_dm_send_sync`, `asker_session_id` → `sender_session_id`, and any `/api/notify-peer` URL literals → `/api/dm-send`.

**Use `git mv`** for the file move so history follows the rename.

### Phase E — Docs (in-repo)

| File | Action |
|---|---|
| `src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-*.md`, `03-*.md` | update `/api/notify-peer` / `notify_peer` references to `/api/dm-send` / `dm_send` |
| `src/lupin_mcp/cosa_voice_mcp.py` `instructions` payload + docstrings | covered in Phase B (`:592`, `:711`) |
| `src/docs/` notification/websocket touchpoints | grep for `notify-peer`; update any endpoint reference (per CLAUDE.md DOCUMENTATION TOUCHPOINTS — `routers/notifications.py` architecture → `src/docs/notification-api.md`; run `src/scripts/generate-api-docs.sh` to refresh `src/docs/fastapi/` if the OpenAPI route changed) |
| `src/rnd/README.md` | add a link to this build plan (per the "new R&D doc → link in README" rule) |

**Verify E (global sweep):** `grep -rn "notify-peer\|notify_peer\|NotifyPeer\|asker_session_id" src/ --include="*.py" --include="*.md"` → only acceptable survivors are `peer_dm` listener/hook names (Phase F, out of scope) and the DB `direction='ai_to_ai'` provenance (out of scope). **Zero `notify_peer`/`notify-peer`/`asker_session_id` survivors.**

---

## 4. Three-Unit Coordinated Cutover (NO shim)

The rename touches **three independently-deployed units** that all speak the same route. Because there is **no shim/alias**, the moment the HTTP route becomes `/api/dm-send`, any client still POSTing `/api/notify-peer` **404s**. Therefore all three flip **together**, after the single commit lands:

```mermaid
sequenceDiagram
    participant C as Commit (5ce5dba5 + rename)
    participant H as :7999 HTTP (notifications.py route)
    participant M as cosa-voice MCP server (_dm_send_impl POST target)
    participant A as arbiter :8001 (DM_SEND_PATH POST target)
    C->>H: route /api/notify-peer → /api/dm-send
    Note over H,A: ⚠️ between commit and full cutover, mixed state = 404s
    C->>H: bounce :7999 (docker restart lupin-rest-dev) — route now /api/dm-send
    C->>M: restart cosa-voice MCP server — client now POSTs /api/dm-send
    C->>A: restart lupin-arbiter-app :8001 — client now POSTs /api/dm-send
    Note over H,M,A: all three aligned → dm_send works end-to-end
```

**Cutover steps (run together, in this order, after the commit is in the working tree / on the held branch):**

1. **`:7999` HTTP** — bounce via `docker restart lupin-rest-dev` (per skill `server-lifecycle`; `:7999` `--reload` may pick up the route on file-save, but a clean bounce removes ambiguity). This makes `/api/dm-send` the live route.
2. **cosa-voice MCP server** — restart so `_dm_send_impl` POSTs the new `/api/dm-send` path. (The live registration runs the in-tree `src/lupin_mcp/cosa_voice_mcp.py` — [`00`](./00-naming-analysis.md) §3.) A session restart / MCP reload is required for the tool change to take effect.
3. **arbiter `:8001`** — restart `lupin-arbiter-app` so `DM_SEND_PATH` POSTs `/api/dm-send`. (Note from active investigations: the arbiter app must be restarted to pick up new code — it does not hot-reload.)

**Coupling rule:** never land the HTTP route rename without immediately following with both client restarts. If the cutover must be staged across a maintenance gap, keep `:7999` on the OLD code until both clients are ready, then flip all three within the same window. **Do not deploy a back-compat dual-route** — that violates the one-name doctrine; the whole point is no shim.

**Gating:** the commit is **held** (not pushed) per standing discipline; the live cutover bounce of `:7999` + MCP + `:8001` is **Rick's gate** (shared-infra restart, blast-radius). The implementer crew builds + verifies on `:7999` dev to the extent possible without a coordinated production flip, reports receipts, and holds.

---

## 5. 100% Coverage Gate

Per the Lupin-wide **100% COVERAGE MANDATE** (lines AND branches AND functions; `pytest --cov --cov-fail-under=100`):

- **Preserve `# pragma: no cover`** on the renamed route wrapper `post_dm_send` (`notifications.py:2971`). The wrapper is the thin FastAPI shim; the testable logic is `execute_dm_send` — the pragma stays exactly as it was on `post_notify_peer`. **Do not drop or relocate it.**
- The moved `test_dm_send_endpoint.py` must continue to exercise `execute_dm_send`, `DmSendRequest`, `_persist_dm_send_sync` at 100% lines/branches/functions — a pure rename should preserve existing coverage 1:1. Re-run with `--cov` scoped to the changed modules.
- Arbiter tests (`test_arbiter_live_notify.py`, `test_arbiter_outreach_receipts.py`) must keep `build_dm_send_payload` + `DM_SEND_PATH` at 100%.
- **No new `# pragma: no cover`** may be introduced. If a rename surfaces a newly-uncovered branch, write the test — never widen the pragma.

**Changed-surface scope** (the modules this rename touches):
```bash
pytest --cov=cosa.rest.routers.notifications \
       --cov=lupin_arbiter_app.arbiter_live_notify \
       --cov-branch --cov-report=term-missing \
       src/cosa/tests/unit/rest/test_dm_send_endpoint.py \
       src/tests/unit/test_arbiter_live_notify.py \
       src/tests/unit/test_arbiter_outreach_receipts.py \
       src/tests/unit/lupin_mcp/test_dm_send.py
```
(MCP module `cosa_voice_mcp` coverage via its existing unit suite.) All four/five suites green at 100%.

---

## 6. Verification Sequence (implementer runs ALL of these)

1. **`py_compile`** every edited `.py`:
   ```bash
   python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in [
     'src/cosa/rest/routers/notifications.py',
     'src/lupin_mcp/cosa_voice_mcp.py',
     'src/lupin_arbiter_app/arbiter_live_notify.py',
     'src/lupin_arbiter_app/app.py']]; print('OK')"
   ```
2. **Import-chain** (the symbols the rename touches resolve):
   ```bash
   PYTHONPATH=src python -c "from cosa.rest.routers.notifications import execute_dm_send, DmSendRequest, _persist_dm_send_sync, post_dm_send; print('OK')"
   PYTHONPATH=src python -c "from lupin_arbiter_app.arbiter_live_notify import build_dm_send_payload, DM_SEND_PATH, make_dm_push_fn; print('OK')"
   ```
3. **Grep sweeps** (Phase A–E "Verify" lines above) — zero `notify_peer`/`notify-peer`/`asker_session_id`/`NotifyPeer`/`_persist_peer_notification_sync` survivors anywhere under `src/` except the out-of-scope `peer_dm` (§8) and DB `direction` provenance.
4. **Changed-surface pytest** (§5 command) — 100% lines/branches/functions, all green.
5. Report results in a **tabular pass/fail-per-tier** summary (py_compile / import-chain / grep-clean / pytest-coverage).

All `:7999`-venue (no persistent-state mutation, < 2 min, no monopoly). No `:8000` scheduling needed for a pure rename's unit/compile verification.

---

## 7. Risks & Rollback

| Risk | Mitigation |
|---|---|
| **Mixed-state 404s** — HTTP route flips before clients | §4 cutover rule: all three units restart together; never land route-rename without immediate client restarts. No dual-route shim. |
| **Arbiter just migrated TO `notify-peer` (`5ce5dba5`)** — fresh references | Build on top of `5ce5dba5` so the arbiter's new refs are renamed in the same sweep (Phase C). |
| **Field rename desync** — `sender_session_id` in model but `asker_session_id` still in a payload key | Phases A/B/C rename the field + both payload keys (MCP `:3096`, arbiter `:327`/`:474`) in lockstep; grep-verify zero `asker_session_id`. |
| **Coverage regression** — moved test loses a branch | §5 changed-surface `--cov-branch` gate; a pure rename preserves coverage 1:1. |
| **Missed doc/OpenAPI reference** | §3 Phase E global grep sweep + `generate-api-docs.sh` refresh. |
| **No persisted-data risk** | Only DB touchpoint is `direction='ai_to_ai'` (out of scope, no migration — [[feedback_no_migration_code]]). |

**Rollback:** the change is a single held commit on `wip-v0.1.8` (not pushed). If cutover reveals a problem, `git revert`/reset the commit and re-bounce all three units back to the `5ce5dba5` code. Because there is no data migration and no shim, rollback is a clean code-only revert + three-unit restart.

---

## 8. Out of Scope (Phase 1) — recipient-side `peer_dm` normalization

Per [`00`](./00-naming-analysis.md) §F, the recipient-side `peer_dm` vocabulary is a **separate follow-up phase**, deliberately deferred:

- `cc_notification_listener._handle_peer_dm` (`src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py:358`) → `_handle_dm`
- `build_peer_dm_reminder` (`src/lupin_cli/claude_code/hooks/lib/hook_common.py:405`) → `build_dm_reminder`
- + their tests `test_hook_voice_helpers.py`, `test_cc_notification_listener.py`

**Why deferred:** largest blast radius (live enabled hooks — [[feedback_enabled_hook_runs_working_tree]]), and `peer_dm` is at least *internally consistent* (not divergent the way `notify_peer` is). It does not block the HTTP/MCP/arbiter convergence. **Do NOT touch it in Phase 1.**

**Also out of scope (never rename):** DB `direction` column + `'ai_to_ai'` value (`postgres_models.py:567`) — naming-neutral provenance; renaming would require a data migration.

---

## 9. Acceptance Criteria

A Phase-1 implementation is **done** iff ALL hold:

- [ ] **AC1 — built on `5ce5dba5`.** The rename commit's parent is `5ce5dba5`.
- [ ] **AC2 — one name everywhere.** Zero `notify_peer` / `notify-peer` / `NotifyPeerRequest` / `execute_notify_peer` / `post_notify_peer` / `_persist_peer_notification_sync` / `build_notify_peer_payload` / `NOTIFY_PEER_PATH` / `asker_session_id` survivors under `src/` (grep-clean), except the out-of-scope `peer_dm` (§8) and DB `direction` provenance.
- [ ] **AC3 — no alias / no shim.** No dual-route, no back-compat `/api/notify-peer`, no field alias. Single canonical `/api/dm-send` + `sender_session_id`.
- [ ] **AC4 — pragma preserved.** `# pragma: no cover` remains on the renamed route wrapper `post_dm_send`; no new pragmas introduced.
- [ ] **AC5 — py_compile green** on all edited `.py` (§6.1).
- [ ] **AC6 — import-chain green** for all renamed symbols (§6.2).
- [ ] **AC7 — changed-surface pytest at 100%** lines AND branches AND functions (§5 command, `--cov-branch`).
- [ ] **AC8 — tests moved via `git mv`** with symbols renamed in lockstep (Phase D); history follows the rename.
- [ ] **AC9 — docs updated** (Phase E) incl. `src/rnd/README.md` link to this plan; OpenAPI refreshed if route metadata changed.
- [ ] **AC10 — cutover documented + held.** The three-unit cutover (§4) is the deploy step; the commit is held (not pushed), the live `:7999`+MCP+`:8001` flip is Rick's gate.
- [ ] **AC11 — Phase F deferred.** Recipient-side `peer_dm` rename NOT attempted in this phase.

---

*Cross-links:* [`00-naming-analysis.md`](./00-naming-analysis.md) (source analysis) · token-reduction lineage `../2026.06.13-cosa-voice-token-reduction/{01,02,03}-*.md`. Doctrine: [[feedback_one_descriptive_name_everywhere_break_contract]], [[feedback_no_migration_code]], [[feedback_enabled_hook_runs_working_tree]].
