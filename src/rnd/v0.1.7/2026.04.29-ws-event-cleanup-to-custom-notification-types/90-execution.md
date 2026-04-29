# 90 — Execution log

**Plan**: `~/.claude/plans/voice-persona-assigned-is-a-prohibited-tender-fairy.md`
**Design**: `01-design.md` (paired)
**Started**: 2026-04-29
**Completed**: 2026-04-29 (single-session execution)

---

## Phase status

| Phase | Subject | Status | Notes |
|-------|---------|--------|-------|
| 0 | Documentation (`01-design.md` + this scaffold) | ✅ complete | Mermaid before/after diagram + migration matrix + decisions |
| 1 | Extend `valid_types` + add `payload` field to `NotificationItem` | ✅ complete | py_compile clean; round-trip schema check passes |
| 2 | Migrate 4 router callsites to `push_notification` | ✅ complete | py_compile + import-chain clean for both routers |
| 3 | Relocate client dispatch into `handleNotificationUpdate` | ✅ complete | Top-level case removed; 3 dispatches added; subscribed_events list pruned |
| 4 | Update affected tests + run unit/smoke regression on `:7999` | ✅ complete | 3773/3773 unit tests pass; 25/25 voice_persona helpers; 7/7 voice_persona allocation; 13/13 conversation_mode_router |
| 5 | Author + run automated WS-frame capture E2E verification | ✅ complete | 4/4 new WS-capture smoke tests pass against live :7999 |
| 6 | Mid-execution checkpoint (Phase 0–6) | ✅ complete | Architectural cleanup landed; user authorized inline Layer A + B continuation |
| 7 | Doc addendum: Layer A + B moved from out-of-scope to in-scope | ✅ complete | `01-design.md` §10 rewritten + §11 phase table extended |
| 8 | Layer A — client patches existing card DOM on voice_persona_assigned/released | ✅ complete | Added `_renderPersonaBadgeHTML` + `_setPersonaBadgeOnCard`; createSenderCard uses helper; 2 dispatch cases call the patch |
| 9 | Layer B — senders-visible carries `voice_persona` + client hydrates on page load | ✅ complete | Server stamps via `_voice_persona_for_sender_id`; client pre-hydrates `senderPersonaMap` in `loadConversationHistory` before card render |
| 10 | Tests for Layer A + B + final regression + combined commit proposal | ✅ complete | 5/5 WS event cleanup smoke tests pass (incl. new `test_senders_visible_carries_voice_persona`); 3780/3780 full unit + voice_persona allocation regression |

---

## Phase 4 results (regression sweep)

| Suite | Command | Result |
|-------|---------|--------|
| Unit (full) | `pytest src/tests/unit/` | **3773 passed**, 1 xfailed (expected), 0 failures, 149s |
| Unit (target) | `pytest src/tests/unit/test_conversation_mode_router.py -v` | 13/13 passed, 2.2s |
| Unit (target) | `pytest src/tests/unit/test_voice_persona_helpers.py -v` | 25/25 passed, 0.06s |
| Smoke (live :7999) | `pytest src/tests/smoke/test_voice_persona_allocation.py -v` | 7/7 passed, 0.36s |

---

## Phase 5 results (WS-frame E2E)

`src/tests/smoke/test_ws_event_cleanup.py` — 4 new tests, all pass against live :7999:

| Test | Asserts |
|------|---------|
| `test_allocate_emits_voice_persona_assigned_notification` | `notification_queue_update` envelope arrives with `notification.type === "voice_persona_assigned"` and `notification.voice_persona` populated; NO top-level `voice_persona_assigned` frame |
| `test_release_emits_voice_persona_released_notification` | `notification_queue_update` carries `notification.type === "voice_persona_released"`; NO top-level frame |
| `test_activate_emits_conversation_mode_changed_notification` | `notification_queue_update` filtered by `payload.session_id == ours` carries `payload.active === True` and `payload.displaced !== True`; NO top-level frame |
| `test_deactivate_emits_conversation_mode_changed_with_active_false` | `notification_queue_update` carries `payload.active === False`; NO top-level frame |

**Triggering observation during Phase 5**: the activate test caused mutex displacement of the user's other active conversation-mode session (one of their existing CC terminals). This is *correct migration semantics* — the original `emit_to_user` displace path is now `push_notification` displace path, identical effect. Test was updated to filter by `payload.session_id` to assert specifically on OUR session's activation event, not the displace event for the other session. Side effect noted: the user's previously-active CC session is no longer in conversation mode after this test runs; user must re-toggle if desired.

**Risk verified during Phase 5 (P2-1)**: `push_notification(user_id=X)` reaches the same WS sessions as the legacy `emit_to_user(X, ...)`. Confirmed because the test's WS connection (authenticated as the test user) receives the `notification_queue_update` envelope produced by the migrated push call.

---

## Files changed

**Parent Lupin** (will be staged):
- `src/fastapi_app/static/js/notifications.js` — relocate dispatch (Phase 3) + add `_renderPersonaBadgeHTML` + `_setPersonaBadgeOnCard` helpers + Layer A patches in dispatches + Layer B `senderPersonaMap` pre-hydration in `loadConversationHistory`
- `src/tests/unit/test_conversation_mode_router.py` — rewrite mock target ws_manager → notification_queue (179 lines changed)
- `src/tests/smoke/test_ws_event_cleanup.py` — NEW WS-frame capture E2E suite (5 tests including Layer B server-stamp verification)
- `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md` — NEW design doc with §10 Layer A + B addendum
- `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/90-execution.md` — NEW (this file)

**CoSA submodule** (edits made, no git ops from parent context per `feedback_lupin_only_never_cosa.md`):
- `src/cosa/rest/notification_fifo_queue.py` — added `payload: Optional[dict] = None` field to `NotificationItem.__init__`, `to_dict`, `push_notification` signature, and constructor invocation
- `src/cosa/rest/routers/notifications.py` — extended `valid_types` list with 3 new types (Phase 1) + Layer B server stamps `voice_persona` on each sender in `senders-visible` response
- `src/cosa/rest/routers/voice_persona.py` — replaced 2 ad-hoc `emit_to_user` callsites with `push_notification(type=...)`; swapped `ws_manager` Depends → `notification_queue` Depends
- `src/cosa/rest/routers/conversation_mode.py` — replaced 2 ad-hoc `emit_to_user` callsites with `push_notification(type=..., payload={...})`; swapped Depends; imported `build_sender_id_for_cc`

CoSA changes will need to be committed separately by the user from inside the CoSA context.

---

## Decision audit (recommendations from plan, ratified by approval)

| # | Question | Decision | Validated by |
|---|----------|----------|--------------|
| 1 | Re-broadcast on idempotent `/allocate`? | No — preserve current "first-time-only" behavior | Migration placed inside `if existing is None` branch; smoke `test_allocate_is_idempotent` passes (response shape unchanged) |
| 2 | Any of these response-required? | No — all fire-and-forget | All migrations use `response_requested=False`, `suppress_ding=True` |
| 3 | Generic `payload` dict vs one-off fields? | Generic `payload` (hybrid: typed fields for known shapes, `payload` for novel shapes) | `voice_persona_*` events use existing `voice_persona` field; `conversation_mode_changed` uses new `payload` field carrying `{ session_id, active, [displaced, displaced_by] }` |

---

## Out of scope (parking lot, return after this commit)

- **v2 visual theming** (6 ranked CSS changes against `--persona-color` custom property — card border tint, header gradient, active stripe, active dot, toggle border, outgoing bubble). Held for follow-up plan now that `senderPersonaMap` plumbing is canonical.
- **Persona hydration fix Layer A** (live `voice_persona_assigned` notification handler patches sender-card DOM in place — adds badge + sets `--persona-color` so existing cards rendered from history get the badge without a refresh).
- **Persona hydration fix Layer B** (`/api/notifications/senders-visible/{email}` carries `voice_persona` for refresh-survival).

All three depend on this cleanup. With `notification.type === "voice_persona_assigned"` now reliably arriving at the client, Layer A is straightforward.

---

## Pre-existing semantics noted (NOT in scope to fix here)

- `find_active_conversation_sessions()` scans ALL bridges in `~/.claude/sessions/` regardless of which user owns them. The mutex displacement therefore can cross user boundaries when multiple users share a host. The migration preserves this exact behavior — fix would belong in a separate plan focused on per-user mutex semantics.
- `notification_fifo_queue.py:71` defaults `sender_id` to `"claude.code@unknown.deepily.ai"` if not provided. Migrations explicitly compute `sender_id` via `build_sender_id_for_cc(session_id)` to keep notifications grouped under the right sender card.

---

## Commit proposal (awaiting user approval — do not auto-commit)

**Scope**: parent Lupin only. CoSA changes managed separately.

**Files to stage**:
```
src/fastapi_app/static/js/notifications.js
src/tests/unit/test_conversation_mode_router.py
src/tests/smoke/test_ws_event_cleanup.py
src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md
src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/90-execution.md
```

**Files NOT to stage** (other sessions / pre-existing untouched-by-me):
- `.claude-session.md` (parallel-session manifest — owned by other sessions)
- `TODO.md`
- `src/lupin_cli/notifications/notify_user_async.py`
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/*` (other session's work)
- `src/tests/smoke/test_deep_research_*.py`
- `src/tests/smoke/utilities/live_pipeline_base.py`

**Draft commit message**: see Phase 6 below or surfaced separately to user.
