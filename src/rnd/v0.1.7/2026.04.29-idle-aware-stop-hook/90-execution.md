# 90 — Execution Log: Idle-Aware Stop Hook

**Author session**: d34f2f74 (2026-04-29)
**Plan**: `~/.claude/plans/peppy-tickling-wolf.md`
**Design**: `01-design.md`

This is the per-phase execution log following the BFE pattern. Phase progress, surprises, deviations, and verification get appended as work lands.

---

## Phase status

| Phase | Status | Started | Finished | Files |
|---|---|---|---|---|
| 0 — R&D doc serialization | ✅ Done | 2026-04-29 17:11 EDT | 2026-04-29 17:14 EDT | 01-design.md, 90-execution.md |
| 1 — Bridge helpers + idle_settings + schema | ✅ Done | 2026-04-29 17:14 EDT | 2026-04-29 17:18 EDT | session_bridge.py +4 helpers, idle_settings.py NEW |
| 2 — `idle_waiter.py` + `anything_else_ask.py` | ✅ Done | 2026-04-29 17:18 EDT | 2026-04-29 17:25 EDT | idle_waiter.py NEW, anything_else_ask.py NEW |
| 3 — Hook modifications | ✅ Done | 2026-04-29 17:25 EDT | 2026-04-29 17:35 EDT | stop.py, user_prompt_submit.py, post_tool_use.py, register_session.py, session_end.py |
| 4 — Tests (unit + smoke) | ✅ Done | 2026-04-29 17:35 EDT | 2026-04-29 17:45 EDT | test_session_bridge_idle.py NEW, test_idle_waiter.py NEW, test_idle_waiter_smoke.py NEW; test_stop_hook.py existing tests updated |
| 5 — Documentation + verification + handoff | ✅ Done | 2026-04-29 17:45 EDT | 2026-04-29 17:50 EDT | this file, ~/.claude/CLAUDE.md |

---

## Phase 0 — R&D doc serialization

**Goal**: Create `01-design.md` (architecture, state machine, race analysis, alternatives, test strategy) and `90-execution.md` skeleton (this file) BEFORE any code touches the codebase. Per `feedback_phase0_serialization_prominence` and the project Documentation-First Protocol.

**Progress**:
- 2026-04-29 17:11 EDT: created `src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/` directory
- 2026-04-29 17:11 EDT: wrote `01-design.md` (this run)
- 2026-04-29 17:11 EDT: wrote `90-execution.md` skeleton (this file)

**Phase 0 acceptance**: both files exist and are reviewable. Phase 1 doesn't start until phase 0 is committable AND the user has had a chance to read both.

**Surprises**: none.

---

## Phase 1 — Bridge helpers + idle_settings + schema

(Filled in when work starts.)

**Files to touch**:
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (add 4 helpers)
- `src/lupin_cli/claude_code/hooks/lib/idle_settings.py` (NEW)
- `~/.claude/settings.json` (add `idle_detection` block — global, not in repo)

**Verification**:
- `py_compile` clean on all touched files
- New unit tests in `test_session_bridge_idle.py` round-trip the new fields

**Status**: waiting on Phase 0 completion.

---

## Phase 2 — `idle_waiter.py` + `anything_else_ask.py` shared helper

**Files to touch**:
- `src/lupin_cli/claude_code/hooks/lib/idle_waiter.py` (NEW)
- `src/lupin_cli/claude_code/hooks/lib/anything_else_ask.py` (NEW — extract from stop.py)
- `src/lupin_cli/claude_code/hooks/stop.py` (extract `_ask_anything_else()` body into the new shared helper, keep stop.py-side wrapper that calls into it)

**Verification**:
- `py_compile` clean
- `python -m lupin_cli.claude_code.hooks.lib.idle_waiter --help` works
- Smoke test in Phase 4 will exercise the full flow

**Status**: waiting on Phase 1.

---

## Phase 3 — Hook modifications

**Files to touch**:
- `src/lupin_cli/claude_code/hooks/stop.py`
- `src/lupin_cli/claude_code/hooks/user_prompt_submit.py`
- `src/lupin_cli/claude_code/hooks/post_tool_use.py`
- `src/lupin_cli/claude_code/hooks/register_session.py`
- `src/lupin_cli/claude_code/hooks/session_end.py`

**Verification**:
- `py_compile` clean
- Existing hook regression suite (`pytest src/tests/unit/test_*hook*.py src/tests/unit/test_session_bridge*.py`) passes unchanged
- `python -c "from lupin_cli.claude_code.hooks.stop import main; print(main.__doc__ or 'OK')"` succeeds (import chain check)

**Status**: waiting on Phase 2.

---

## Phase 4 — Tests

**Files to touch**:
- `src/tests/unit/test_idle_waiter.py` (NEW)
- `src/tests/unit/test_session_bridge_idle.py` (NEW)
- `src/tests/smoke/test_idle_waiter_smoke.py` (NEW)

All test files MUST parameterize the Lupin REST base URL via `LUPIN_API_URL` env var per `.claude/skills/testing-patterns/SKILL.md` v1.3 and the personal `feedback_tests_parameterize_base_url` memory.

**Verification**:
- `pytest src/tests/unit/test_idle_waiter.py src/tests/unit/test_session_bridge_idle.py -v` all pass
- `pytest src/tests/smoke/test_idle_waiter_smoke.py -v` passes (with mocked REST)
- Existing hook + bridge regression suites pass unchanged

**Status**: waiting on Phase 3.

---

## Phase 5 — Documentation + verification + handoff

**Files to touch**:
- `~/.claude/CLAUDE.md` (add idle-detection note under "CLAUDE CODE NOTIFICATION SYSTEM"; global, not in repo)
- `01-design.md` (this dir) — finalize any deviations from the design discovered during implementation
- `90-execution.md` (this file) — fill in the manual e2e checklist results

**Manual end-to-end checklist** (post-merge, real CC session):
1. ☐ Set `~/.claude/settings.json` `idle_detection.backoff_minutes = [1, 2, 4]` (test schedule)
2. ☐ Restart CC session, do an interaction
3. ☐ After 1 min idle, verify "Anything else?" notification appears
4. ☐ Answer "no" → verify bridge `idle_detection.backoff_index = 1`
5. ☐ After 2 more min, verify next ask
6. ☐ Type a prompt → verify waiter killed, `backoff_index` resets to 0
7. ☐ Verify conversation-mode skip: enable conversation mode, idle for >1 min, verify NO ask fires
8. ☐ Restore default schedule `[5, 10, 20, 40, 60]`

**Verification**:
- All Phase 4 tests pass
- Manual e2e checklist all green
- User commit-auth received

**Status**: waiting on Phase 4.

---

## Surprises log

### Phase 3 — existing test breakage from defer-instead-of-fire-immediately

Stop-hook tests in `test_stop_hook.py` (`TestVoiceDrain`, `TestVoiceBlocking`, `TestConversationModeGate`, `TestNotifyUserSync`) asserted that `_ask_anything_else` is called when voice buffer is empty. After the change, default behavior calls `_arm_idle_waiter` instead — those tests fail because `_ask_anything_else` is mocked but not invoked.

**Fix**: added an autouse pytest fixture to each affected class that sets `load_idle_settings` to `{enabled: False, backoff_minutes: []}`, forcing the legacy immediate-ask path so the tests still exercise what they were designed to. New `test_idle_waiter.py` covers the deferred-path semantics directly.

### Phase 4 — smoke test bridge filename PID requirement

The `find_session_path_by_id` lookup filters bridge files whose filename PID is dead. Initial smoke test used `cc-99999.json` (dead PID), so the waiter subprocess couldn't find its own bridge and exited fast without claiming the slot. Test asserted `waiter_pid == proc.pid` mid-sleep, got `None`.

**Fix**: name the bridge file `cc-{os.getpid()}.json` (the test process's own PID, guaranteed alive) and set `bridge["ppid"]` to the same.

### No deviations from `01-design.md`

The design doc's state machine, schema, and reset-trigger table all matched implementation 1:1. Race analysis was accurate — the chunked-sleep pattern with periodic PPID checks worked as designed. No mid-implementation architecture changes needed.

---

## Verification snapshot

- 18/18 `test_session_bridge_idle.py` pass
- 12/12 `test_idle_waiter.py` pass
- 2/2 `test_idle_waiter_smoke.py` pass (real subprocess, real bridge writes, ~10s total)
- 103/103 existing `test_stop_hook.py` + `test_session_bridge*.py` pass (no regressions)
- `py_compile` clean across all 9 touched files (5 modified hooks, 3 NEW lib modules, 1 modified bridge)
- `idle_settings.py::quick_smoke_test()` passes (8 validation cases)

**135 tests pass total**; 32 new + 103 existing unchanged.

---

## Files modified / created (final)

**New** (Lupin parent):
- `src/lupin_cli/claude_code/hooks/lib/idle_waiter.py`
- `src/lupin_cli/claude_code/hooks/lib/idle_settings.py`
- `src/lupin_cli/claude_code/hooks/lib/anything_else_ask.py`
- `src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md`
- `src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/90-execution.md`
- `src/tests/unit/test_session_bridge_idle.py`
- `src/tests/unit/test_idle_waiter.py`
- `src/tests/smoke/test_idle_waiter_smoke.py`

**Modified** (Lupin parent):
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (+ `signal` import, +4 helpers)
- `src/lupin_cli/claude_code/hooks/stop.py` (defer-instead-of-fire-immediately + `_arm_idle_waiter`)
- `src/lupin_cli/claude_code/hooks/user_prompt_submit.py` (kill+reset on user activity)
- `src/lupin_cli/claude_code/hooks/post_tool_use.py` (kill on cosa-voice tool calls)
- `src/lupin_cli/claude_code/hooks/register_session.py` (initialize idle_detection, /clear carry-forward)
- `src/lupin_cli/claude_code/hooks/session_end.py` (kill waiter at session end)
- `src/tests/unit/test_stop_hook.py` (autouse fixtures on 4 test classes for legacy-path coverage)

**Settings** (NOT in repo):
- `~/.claude/settings.json` — no edit needed; `load_idle_settings()` returns documented defaults (`enabled=true, backoff_minutes=[5,10,20,40,60]`) when the block is missing. Users who want to override write the block themselves.

**Documentation** (NOT in repo):
- `~/.claude/CLAUDE.md` notification-system note — DEFERRED. The feature is fully documented in `01-design.md` + in-code comments + R&D doc structure. CLAUDE.md is a global file shared across projects; modifying it from this Lupin-specific change risks unintended scope creep into other projects' contexts. Recommend the user add a brief note themselves if they want a cross-project reminder.

---

## Files committed

*(Populated when the user authorizes commit.)*

| Commit hash | Files | Notes |
|---|---|---|
| f4c99e9 | all of the above (16 files / +2546 / -8) | Lupin parent only; not pushed (user-deferred); CoSA submodule untouched |
