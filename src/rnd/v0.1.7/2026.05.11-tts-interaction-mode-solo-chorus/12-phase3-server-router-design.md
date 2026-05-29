# Phase 3 — Server Router Cleanup (`speakerphone.py`)

**Date**: 2026.05.12
**Status**: 📝 Design — not yet implemented
**Owner**: [LUPIN]
**Phase**: 3 of 8
**Prerequisites**: [Phase 1](10-phase1-ini-plumbing-design.md) (config helper) + [Phase 2](11-phase2-bridge-rename-design.md) (bridge renames).
**Companion docs**: [`00-index.md`](00-index.md), [`01` (May 12 canonical plan)](2026.05.12-tts-interaction-mode-solo-chorus.md), [`02-background-synthesis.md`](02-background-synthesis.md)
**Execution log**: [`93-phase3-execution-log.md`](93-phase3-execution-log.md) (TBD)

---

## 1. Goal

Rename `src/cosa/rest/routers/conversation_mode.py` to `speakerphone.py` and make the activate endpoint mode-aware:

- **Solo branch** — preserve today's behavior pixel-perfect: asyncio.Lock + scan-and-displace + activate self + broadcast.
- **Chorus branch** — skip the Lock and the scan; activate self + broadcast; return empty `displaced_sessions`.

Rename the HTTP endpoint, the WebSocket event, and the listener action uniformly. The renames apply in both modes; only the mutex behavior diverges.

---

## 2. Scope

### In scope

- File rename: `src/cosa/rest/routers/conversation_mode.py` → `src/cosa/rest/routers/speakerphone.py`.
- HTTP endpoint rename: `/api/cosa-voice/conversation-mode/{sid}` → `/api/cosa-voice/speakerphone/{sid}`.
- WebSocket event rename: `conversation_mode_changed` → `speakerphone_changed`.
- Listener action rename: `action:exit_conversation_mode` → `action:disable_speakerphone`.
- Activate path branched on `get_tts_interaction_mode()`:
  - Solo → today's full path.
  - Chorus → no-Lock, no-scan, activate-self-and-broadcast.
- Deactivate path unchanged in shape, but uses renamed helpers + event name.
- Wire-in update: `src/cosa/rest/main.py` or wherever the router is registered, point at new file/name.
- Unit tests covering both branches.
- Add the new event name to the WebSocket event allowlist (likely `lupin-app.ini` `websocket available events`).

### Out of scope

- MCP-side `_flip_conversation_mode` rename (Phase 4).
- Hook listener call-sites for the renamed action (Phase 5).
- Multiplexer UI event listener rename (Phase 7).
- WebSocket allowlist removal of old event name — handled via the same INI key update; no aliases needed per [[feedback_no_migration_code]].

---

## 3. Deliverables

### 3.1 File rename

```bash
git mv src/cosa/rest/routers/conversation_mode.py src/cosa/rest/routers/speakerphone.py
```

(Manual `mv` if not staged — keep history via Git's rename detection.)

### 3.2 Activate path branching

**Today's structure** (`conversation_mode.py:164-225` approximate):

```python
async with _conversation_mode_lock:
    # Scan for other active sessions
    others = find_active_conversation_sessions()
    displaced = []
    for other_sid in others:
        if other_sid == sid:
            continue
        set_conversation_mode( other_sid, False )
        await ws_manager.emit_to_user(
            user_email, "conversation_mode_changed",
            { "session_id": other_sid, "active": False, "displaced": True, "displaced_by": sid }
        )
        await cc_listener_action_push( other_sid, "action:exit_conversation_mode" )
        displaced.append( other_sid )
    # Activate self
    set_conversation_mode( sid, True )
    await ws_manager.emit_to_user(
        user_email, "conversation_mode_changed",
        { "session_id": sid, "active": True }
    )
return { "active": True, "displaced_sessions": displaced }
```

**After Phase 3**:

```python
mode = get_tts_interaction_mode()

if mode == "solo":
    async with _speakerphone_lock:
        others = find_active_speakerphone_sessions()
        displaced = []
        for other_sid in others:
            if other_sid == sid:
                continue
            set_speakerphone( other_sid, False )
            await ws_manager.emit_to_user(
                user_email, "speakerphone_changed",
                { "session_id": other_sid, "on": False, "displaced": True, "displaced_by": sid }
            )
            await cc_listener_action_push( other_sid, "action:disable_speakerphone" )
            displaced.append( other_sid )
        set_speakerphone( sid, True )
        await ws_manager.emit_to_user(
            user_email, "speakerphone_changed",
            { "session_id": sid, "on": True }
        )
    return { "on": True, "displaced_sessions": displaced }

else:  # chorus
    set_speakerphone( sid, True )
    await ws_manager.emit_to_user(
        user_email, "speakerphone_changed",
        { "session_id": sid, "on": True }
    )
    return { "on": True, "displaced_sessions": [] }
```

**Field rename in WS payload**: `active` → `on` (matches the new bridge field name).

**`displaced_sessions: []` in chorus**: kept in the response schema for shape stability — multiplexer UI doesn't need to special-case schema differences between modes.

### 3.3 Deactivate path

Mode-independent. Today's deactivate logic stays, with renames applied:

```python
set_speakerphone( sid, False )
await ws_manager.emit_to_user(
    user_email, "speakerphone_changed",
    { "session_id": sid, "on": False }
)
await cc_listener_action_push( sid, "action:disable_speakerphone" )
return { "on": False }
```

Note: deactivate fires `action:disable_speakerphone` on **self**, not on others. This signals the session's own listener that it should stop calling `notify()` and unpin its UI card.

### 3.4 INI: WebSocket event allowlist

**File**: `src/conf/lupin-app.ini`
**Key**: `websocket available events`

**Today** (assumed):
```ini
websocket available events = ..., conversation_mode_changed, ...
```

**After Phase 3**:
```ini
websocket available events = ..., speakerphone_changed, ...
```

Hard rename, no alias. Splainer entry needs no update (key purpose unchanged).

### 3.5 Wire-in (`main.py`)

The router import + registration needs updating from `from cosa.rest.routers import conversation_mode` (or similar) to `from cosa.rest.routers import speakerphone`. Tag/prefix in `app.include_router(...)` also updates.

### 3.6 Unit tests

**File**: `src/tests/unit/test_speakerphone_router.py` (new; replaces any `test_conversation_mode_router.py`)

| Test | Mode | Setup | Assertion |
|---|---|---|---|
| `test_activate_solo_no_others` | solo | Empty `SESSION_DIR` | Self activated; `displaced_sessions=[]`; one WS event emitted |
| `test_activate_solo_displaces_one` | solo | One other bridge with `speakerphone_on=true` | Other displaced; self activated; 2 WS events; 1 listener-action push |
| `test_activate_solo_displaces_many` | solo | 3 other bridges with `speakerphone_on=true` | All 3 displaced; self activated; 4 WS events; 3 listener-action pushes |
| `test_activate_solo_lock_held` | solo | Concurrent invocations | Lock serializes — no interleaved displacement |
| `test_activate_chorus_no_displacement` | chorus | One other bridge with `speakerphone_on=true` | Self activated; other NOT touched; `displaced_sessions=[]`; only 1 WS event |
| `test_activate_chorus_no_lock_held` | chorus | Concurrent invocations | Both activate independently; no Lock contention |
| `test_activate_chorus_returns_displaced_sessions_empty_list` | chorus | Any setup | Response shape includes `displaced_sessions: []` (not missing) |
| `test_deactivate_mode_independent` | both | Active session | Both modes: bridge flips to false, WS event emitted, listener action pushed |
| `test_event_name_speakerphone_changed` | both | Any activate | Emitted event name is `speakerphone_changed`, NOT `conversation_mode_changed` |
| `test_listener_action_disable_speakerphone` | both | Any displace or self-deactivate | Action string is `action:disable_speakerphone`, NOT `action:exit_conversation_mode` |
| `test_payload_field_on_not_active` | both | Any event | Payload has `"on": bool`, NOT `"active": bool` |

Use `pytest.mark.parametrize` over `mode = ["solo", "chorus"]` for tests that should pass in both. Mock `get_tts_interaction_mode()` and `ws_manager.emit_to_user`.

### 3.7 Integration smoke test

**File**: `src/tests/smoke/test_speakerphone_router_live.py` (new)

Live `:7999` smoke:

1. Login (use [[reference_auth_testing_contract]]).
2. Activate speakerphone via POST `/api/cosa-voice/speakerphone/{sid}` (mode=solo by default).
3. Verify bridge file has `speakerphone_on=true`.
4. Verify WS broadcast was received (use the WebSocket smoke-test framework if available, or just check that the bridge state is observable via `get_session_info`).
5. Deactivate.

Skip the chorus path in smoke — INI-flipping mid-test is awkward; cover that case in unit tests with mocks.

---

## 4. Implementation order

1. Read `src/cosa/rest/routers/conversation_mode.py` end-to-end (per `feedback_audit_plans_at_execute_time`).
2. `git mv` the file to `speakerphone.py`.
3. Apply all renames internal to the file (variable names, helper imports, endpoint path, event name, action string, payload fields).
4. Add the `mode` branching in activate path.
5. Update the wire-in in `main.py` (or wherever).
6. Update `lupin-app.ini` event allowlist.
7. `py_compile` the modified files.
8. Import chain check: `from cosa.rest.routers import speakerphone`.
9. Run new unit tests.
10. Run live `:7999` smoke.
11. Run full unit suite for regressions.

**Expected breakage at Phase 3 end**: MCP server still calls the old endpoint (`/api/cosa-voice/conversation-mode/{sid}`); listener still handles old `action:exit_conversation_mode`. Phases 4 + 5 fix these.

---

## 5. Verification matrix

| Layer | Check | Venue | Pass criteria |
|---|---|---|---|
| `py_compile` | `speakerphone.py` + `main.py` | local | Compiles |
| Import chain | `from cosa.rest.routers import speakerphone` | local | No error |
| Unit | `test_speakerphone_router.py` (~11 tests) | :7999 | 100% pass |
| Unit regression | Full suite | :7999 | Failures only in Phase 4/5/7 consumer code (expected; tracked in execution log) |
| Smoke (live) | `test_speakerphone_router_live.py` | :7999 | Bridge + WS state observable |
| WS smoke regression | `./src/scripts/run-websocket-smoke-tests.sh` | :7999 | No regressions (with renamed event in subscription list) |

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | CoSA-side file changes touch the `src/cosa/` submodule — git ops cannot be done from parent Lupin context per [[feedback_lupin_only_never_cosa]] | Edits are fine; only git commit/push must happen separately when working directly in the CoSA repo. Document explicitly in the execution log. |
| 2 | Phase 2 already renamed the bridge helpers; Phase 3 needs to import the renamed names | Confirmed — Phase 2 must merge before Phase 3, OR Phases 2–7 ship as one PR (recommended). |
| 3 | MCP tool's HTTP fallback (`cosa_voice_mcp.py:1295`) currently hits `/api/cosa-voice/conversation-mode/{sid}` — Phase 3 rename breaks the fallback until Phase 4 updates the MCP tool | Single PR. Or: deploy Phase 3 + Phase 4 atomically. |
| 4 | Multiplexer UI listens for `conversation_mode_changed` — Phase 3 rename means UI stops getting events until Phase 7 lands | Single PR for Phases 2–7 (already the plan). |
| 5 | Test fixture for `:7999` smoke may depend on user being logged in with a known session — see auth contract | Use [[feedback_auth_contract_lookup]] + reusable helpers (`reference_auth_testing_contract`). |
| 6 | Concurrent activate requests in solo mode (Lock test) may be hard to test deterministically | Use `asyncio.gather()` of two activate coroutines + assert ordering. |
| 7 | `find_active_speakerphone_sessions()` may have edge cases when bridge files exist for sessions that exited (stale bridges) | Verify Phase 2's helper handles stale bridges correctly (read returns `None` for malformed/old-format → skip). |

---

## 7. Cross-cutting concerns

### Memory check

- [[feedback_lupin_only_never_cosa]] — file lives in `src/cosa/` submodule. Edits allowed; git ops are user's domain. ✓
- [[feedback_cosa_edit_vs_manage_git]] — confirms above. ✓
- [[feedback_no_migration_code]] — no fallback for old event/action names. ✓
- [[feedback_no_defensive_programming]] — no `or False` defaults in helper consumption. ✓
- [[feedback_enumerate_all_activation_paths]] — both activation paths (POST + MCP fallback) reach this endpoint; chorus branch is uniform across both. ✓
- [[feedback_audit_plans_at_execute_time]] — step 1 of implementation order is the audit. ✓

### Naming

- Endpoint: `/api/cosa-voice/speakerphone/{sid}` — REST noun, matches resource semantics. ✓
- WS event: `speakerphone_changed` — past participle, matches `conversation_mode_changed` pattern. ✓
- Listener action: `action:disable_speakerphone` — verb form, matches `enable_speakerphone` / `disable_speakerphone` MCP tool names. ✓

### Documentation touchpoints (per CLAUDE.md table)

- `routers/*.py` endpoint decorators → `/docs` auto-updates; `src/scripts/generate-api-docs.sh` regenerates `src/docs/fastapi/`.
- `routers/websocket.py` → `src/docs/websocket-events.md`, `websocket-architecture.md` — update if anything cross-references the renamed event.
- `lupin-app.ini` `websocket available events` → `src/docs/websocket-events.md`, `websocket-configuration.md`.

Add to phase execution checklist.

---

## 8. Implementation timing

Estimated active work: 90–120 minutes including tests + auth-test wiring + docs touchpoint sweep.

---

## 9. Hand-off to Phase 4

Phase 4 (MCP tool rename + `_notify_impl` mode-conditional) will:
- Rename MCP tools `enter/exit_conversation_mode` → `enable/disable_speakerphone`.
- Point `_flip_speakerphone` (renamed) at the new endpoint `/api/cosa-voice/speakerphone/{sid}`.
- Add `tts_interaction_mode` field to `get_session_info()` response.
- Make `_notify_impl` cross-talk leak cue mode-conditional.

Phase 3 must leave the new endpoint and event names live. Phase 4 wires the MCP layer to consume them.
