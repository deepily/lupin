# `dm_send` ↔ `notify_peer` — Naming-Doctrine Analysis (source material)

**Date:** 2026-06-15 · **Produced by:** a Tiberius-spawned analysis worker · **Status:** analysis complete; feeds `01-build-plan.md`.
**Goal:** unify the divergent `dm_send` (MCP) and `notify_peer` (HTTP/arbiter) names onto a SINGLE function-revealing name at every layer — Rick's one-name doctrine ([[feedback_one_descriptive_name_everywhere_break_contract]]): no alias, no shim, "break everything and do it right." All consumers are in-tree, so this is achievable globally.

---

## 1. The two surfaces (exact locations)

**`dm_send` side (MCP / sender-facing):**
- MCP tool: `dm_send` — `src/lupin_mcp/cosa_voice_mcp.py:3126` (`@mcp.tool`)
- Testable core: `_dm_send_impl` — `src/lupin_mcp/cosa_voice_mcp.py:3061`; builds payload + POSTs to `f"{api_base_url}/api/notify-peer"` at line **3108**
- Unit test: `src/tests/unit/lupin_mcp/test_dm_send.py` (asserts URL ends `/api/notify-peer`, line 65)

**`notify_peer` side (HTTP / handler-facing):**
- HTTP route: `POST /api/notify-peer` — `src/cosa/rest/routers/notifications.py:2967` (decorator), async wrapper `post_notify_peer` at **:2971**
- Pure-logic core: `execute_notify_peer` — `src/cosa/rest/routers/notifications.py:2874`
- Request model: `NotifyPeerRequest` — `src/cosa/rest/routers/notifications.py:2815`
- DB persist helper: `_persist_peer_notification_sync` — `:2836`
- Recipient resolver (shared): `_resolve_dm_recipient` — `src/cosa/rest/routers/commons.py:901`; `RecipientResolutionError` model at `commons.py:162`
- Unit test: `src/cosa/tests/unit/rest/test_notify_peer.py`

**Arbiter (migrated TO notify-peer, commit `5ce5dba5`):**
- `NOTIFY_PEER_PATH = "/api/notify-peer"` — `src/lupin_arbiter_app/arbiter_live_notify.py:51`
- `build_notify_peer_payload` — `:302`; `make_dm_push_fn` (builds `dm_push(persona, thread_id, body)`) — `:334`, POSTs at `:364`
- Tests: `src/tests/unit/test_arbiter_live_notify.py`, `src/tests/unit/test_arbiter_outreach_receipts.py`

**Recipient-side (listener/hooks — `peer_dm` semantics):**
- `cc_notification_listener._handle_peer_dm` — `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py:358` (dispatched on `direction='ai_to_ai'`, line 315)
- `build_peer_dm_reminder` (single source of peer-DM framing + reply affordance) — `src/lupin_cli/claude_code/hooks/lib/hook_common.py:405`

## 2. Divergence table

| Layer | `dm_send`-side name | `notify_peer`-side name |
|---|---|---|
| MCP tool | `dm_send` | — |
| MCP core fn | `_dm_send_impl` | — |
| HTTP route path | (calls `/api/notify-peer`) | `/api/notify-peer` |
| HTTP async handler | — | `post_notify_peer` |
| HTTP pure-logic core | — | `execute_notify_peer` |
| Request model | (payload dict) | `NotifyPeerRequest` |
| DB persist helper | — | `_persist_peer_notification_sync` |
| Arbiter payload builder | — | `build_notify_peer_payload` |
| Arbiter push seam | `make_dm_push_fn` / `dm_push(...)` | `NOTIFY_PEER_PATH` |
| Recipient resolver | — | `_resolve_dm_recipient` (in commons) |
| Recipient listener handler | `_handle_peer_dm` | — |
| Recipient framing builder | `build_peer_dm_reminder` | — |
| **Request field: recipient** | `recipient` (MCP arg) | `recipient_persona` / `recipient_session_id` |
| **Request field: sender** | `session_id` → maps to | `asker_session_id` |
| Request field: body | `body` | `body` ✅ aligned |
| Threading fields | `reply_to`, `thread_id` | `reply_to`, `thread_id` ✅ aligned |
| DB column | — | `direction` (string), value `'ai_to_ai'` |
| Test files | `test_dm_send.py` | `test_notify_peer.py` |

**Three coexisting vocabularies:** `dm`/`dm_send` (MCP), `notify_peer`/`notify-peer` (HTTP+arbiter), `peer_dm` (listener/hooks). `body`/`reply_to`/`thread_id` already aligned; *recipient* and *sender* fields diverge.

## 3. Relationship verdict: TRANSPORT-OF (not parallel)

`dm_send` is the MCP front door; `notify_peer` is its HTTP transport. ONE implementation:

```
MCP dm_send (3126) → _dm_send_impl (3061) → POST /api/notify-peer (2967)
   → post_notify_peer (2971) → execute_notify_peer (2874)
   → _resolve_dm_recipient + _persist_peer_notification_sync + push_notification(direction='ai_to_ai')
```

The arbiter is a SECOND client of the same `/api/notify-peer` endpoint (via `make_dm_push_fn`), not a variant. **Unification = RENAME across the chain, not a merge.**

**Boundary finding:** the cosa-voice MCP server is **in-tree** — `src/lupin_mcp/cosa_voice_mcp.py`, and the live `claude mcp get cosa-voice` registration runs that exact file. **No external package boundary.** Every consumer lives in this one repo — global rename, no cross-repo shim.

## 4. Recommended canonical name: `dm_send` / `/api/dm-send` / "DM"

Rationale: "DM" names a directed, threaded peer message exactly (recipient + body + `reply_to`/`thread_id`); `notify_peer` reads fire-and-forget. `dm_send` is the preferred/newer surface (MCP docstrings say "PREFERRED") and already dominates the user-facing vocabulary (tool, reply affordance, listener handler, global CLAUDE.md). `notify_peer` survives only in the HTTP route + arbiter (the minority). **Converge UP to the `dm` vocabulary.** Canonical route → `POST /api/dm-send` (mirror the tool 1:1). Field doctrine: `recipient` (+`recipient_session_id`) and **`sender_session_id`** (rename `asker_session_id` — "asker" is leftover commons-question vocabulary).

## 5. Complete rename surface (ordered, ALL in-tree, no shim)

**A. HTTP endpoint + handler (`src/cosa/rest/routers/notifications.py`)**
- `:2967` route `"/notify-peer"` → `"/dm-send"`; summary/description text
- `:2971` `post_notify_peer` → `post_dm_send` (preserve its `# pragma: no cover`)
- `:2874` `execute_notify_peer` → `execute_dm_send`
- `:2815` `NotifyPeerRequest` → `DmSendRequest`; field `asker_session_id` → `sender_session_id`
- `:2836` `_persist_peer_notification_sync` → `_persist_dm_send_sync` (consistency)
- `:2817`, `:2885`, `:2805–2812` comment/docstring references

**B. MCP client (`src/lupin_mcp/cosa_voice_mcp.py`)**
- `:3108` `f"{api_base_url}/api/notify-peer"` → `/api/dm-send`
- `:3096` payload key `"asker_session_id"` → `"sender_session_id"`
- `:3093`, `:3054` docstring/error strings naming `/api/notify-peer`
- (tool `dm_send` + `_dm_send_impl` already canonical — keep)

**C. Arbiter (`src/lupin_arbiter_app/arbiter_live_notify.py`)**
- `:51` `NOTIFY_PEER_PATH = "/api/notify-peer"` → `DM_SEND_PATH = "/api/dm-send"`
- `:302` `build_notify_peer_payload` → `build_dm_send_payload`; `:327` payload key `asker_session_id` → `sender_session_id`
- `:18`, `:49`, `:310–354`, `:471–472` comments/docstrings
- caller in `arbiter_job.py` (`_emit_dm`) — update import + call site

**D. Tests (move + rename in lockstep — 100% coverage gate)**
- `src/cosa/tests/unit/rest/test_notify_peer.py` → `test_dm_send_endpoint.py`; `execute_notify_peer` → `execute_dm_send`
- `src/tests/unit/test_arbiter_live_notify.py:24,242,250` — builder rename + `test_dispatched_201_posts_notify_peer_with_body` rename
- `src/tests/unit/test_arbiter_outreach_receipts.py:285,289` — `"notify-peer"` → `"dm-send"`
- `src/tests/unit/lupin_mcp/test_dm_send.py:65` — URL assertion → `/api/dm-send`
- `src/tests/unit/commons/test_commons_ac14_registration.py:60` — comment
- `src/tests/smoke/test_ask_async_push_e2e.py:38,46` — comment strings

**E. Docs (in-repo)**
- `src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/02-*.md`, `03-*.md` — references
- `cosa_voice_mcp.py` `instructions` payload + docstrings (`:592`, `:711`) — only `/api/notify-peer` mentions

**F. OPTIONAL follow-up phase — recipient-side `peer_dm` normalization** (`_handle_peer_dm`, `build_peer_dm_reminder` → `_handle_dm`, `build_dm_reminder` + their tests `test_hook_voice_helpers.py`, `test_cc_notification_listener.py`). Largest blast radius; `peer_dm` is at least internally consistent. **Recommend SEPARATE phase.**

**Out of scope (do NOT rename):** DB `direction` column + `'ai_to_ai'` value (`postgres_models.py:567`) — naming-neutral provenance; renaming needs a data migration ([[feedback_no_migration_code]]).

## 6. Risks + sequencing

1. **MCP/HTTP deploy coupling** — HTTP route lands on `:7999` reload; the MCP tool lands only on an MCP-server restart. Rename route but old MCP path still POSTing → every `dm_send` 404s. No shim → rename everything in ONE commit, then bounce `:7999` AND restart the cosa-voice MCP server together.
2. **Arbiter just migrated TO notify-peer (`5ce5dba5`)** — runs as its own `:8001` app → a THIRD deploy unit. Three units (`:7999` HTTP, MCP server, arbiter `:8001`) flip together.
3. **Build on top of `5ce5dba5`** so the arbiter's brand-new `notify_peer` references are renamed in the same sweep.
4. **100% coverage gate** — test files move/rename in the same commit; preserve `# pragma: no cover` on the renamed route wrapper.
5. **No persisted-data risk** — only DB touchpoint is `direction='ai_to_ai'`, out of scope; no migration.

**Recommended order:** (1) HTTP route+handlers+model+field in `notifications.py`; (2) MCP client URL+payload key; (3) arbiter path/builder+caller; (4) move/rename 6 test files; (5) in-repo docs; (6) `py_compile` + import-chain + changed-surface pytest; (7) single coordinated cutover bounce (`:7999` + MCP server + arbiter `:8001`). Defer item F.

This is a rename fully owned in one repo — actionable in a single commit + a single three-unit cutover bounce.
