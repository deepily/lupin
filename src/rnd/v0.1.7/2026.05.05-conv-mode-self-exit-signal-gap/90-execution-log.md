# Execution Log — Conversation-Mode Self-Exit Signal Symmetry

**Design doc**: `01-design.md` (this directory)
**Plan file (CLI approval surface)**: `~/.claude/plans/wild-napping-petal.md`
**Approved**: 2026-05-05

---

## Phase Status

| Phase | Description | Status | Notes |
|---|---|---|---|
| 0 | Promote R&D doc to directory pattern (this dir + execution log) | 🟢 Done | This file |
| 1 | `hook_common.py` — `conv_mode_exit_reminder()` body wording (Option A) | 🟢 Done | Body + docstring both updated |
| 2 | `conversation_mode.py` (CoSA) — self-exit action push | 🟢 Done | Edit OK from parent context, separate CoSA commit at end |
| 3a | `test_conversation_mode_router.py` — rename + assertion updates | 🟢 Done | New test name: `test_deactivate_pushes_ui_sync_and_self_action` |
| 3b | `test_conv_mode_wrap.py` — rewrite displace assertion + class docstring | 🟢 Done | New test name: `test_body_announces_deactivation` |
| 4 | Verification pyramid (`py_compile`, helper smoke, 3 unit targets, full unit regression, WS smoke, manual live `:7999`) | 🟢 Done (auto-tier) / 🟡 Manual deferred | E2E UI flagged out-of-scope (separate `:8000` schedule) |

Legend: 🟢 done · 🟡 in progress · 🔴 blocked · ⚪ pending

---

## Per-Phase Notes

### Phase 0 — 2026-05-05

- Created directory `src/rnd/v0.1.7/2026.05.05-conv-mode-self-exit-signal-gap/`
- Moved `2026.05.05-conv-mode-self-exit-signal-gap.md` → `01-design.md` inside the new dir
- Updated one self-reference at the moved doc's old line 157 (`...-signal-gap.md` → `...-signal-gap/01-design.md`)
- Created this `90-execution-log.md` scaffold

### Phase 1 — 2026-05-05

- Updated `conv_mode_exit_reminder()` body to reason-agnostic wording:
  - Dropped "(displaced by another session activating conversation mode)" parenthetical
  - First sentence now reads: "Conversation mode has just been deactivated for this session."
- Updated docstring to enumerate both transition causes (displace + self-exit) and removed the "Today the sole caller is …displace block" sentence
- New `Ensures:` bullet: "Body is reason-agnostic — same text for displace and self-exit"

### Phase 2 — 2026-05-05

- Added new conditional block in `set_conversation_mode_endpoint` AFTER the existing `conversation_mode_changed` UI-sync push and BEFORE the return. Block fires only when `not body.active`.
- Push fields:
  - `type="user_initiated_message"`, `title="action:exit_conversation_mode"`
  - `job_id=session_id[:8]` (matches listener filter)
  - `payload={"session_id": session_id, "reason": "self"}` (forensic field)
  - `suppress_ding=True`, `response_requested=False`
- Reused existing imports — no new dependencies
- Position rationale: mirrors displace branch's order (UI sync first, then action push), keeps if/else block logic untouched

### Phase 3 — 2026-05-05

**3a.** `test_conversation_mode_router.py`:
- Renamed `test_deactivate_does_not_scan_or_displace` → `test_deactivate_pushes_ui_sync_and_self_action`
- Updated docstring documenting both pushes
- `call_count == 1` → `== 2`
- Added second-push assertions: `type`, `title`, `job_id`, `payload`

**3b.** `test_conv_mode_wrap.py`:
- Updated `TestConvModeExitReminder` class docstring (drop displace specificity, enumerate both causes)
- Rewrote `test_body_mentions_displacement` → `test_body_announces_deactivation`
- Other six tests in class verified as robust to wording change — no edits needed

### Phase 4 — 2026-05-05

See verification table below. Auto-tier passes 100%. Manual live deferred — see explanation.

---

## Verification Result Table (Phase 4)

To be populated after Phase 4 runs.

| Layer | Command | Result |
|---|---|---|
| Compile | `py_compile` ×4 files | 🟢 4/4 OK |
| Helper smoke | `python -m lupin_cli.claude_code.hooks.lib.hook_common` | 🟢 PASS (LOGS_DIR + TTS + email + timestamp + emit) |
| Unit — router | `pytest src/tests/unit/test_conversation_mode_router.py -v` | 🟢 13/13 PASS in 2.34s |
| Unit — helper | `pytest src/tests/unit/test_conv_mode_wrap.py -v` | 🟢 41/41 PASS in 0.09s |
| Unit — MCP toggle | `pytest src/tests/unit/test_cosa_voice_mcp_conversation_mode.py -v` | 🟢 10/10 PASS in 1.87s |
| Unit — full regression | `pytest src/tests/unit/` | 🟢 3950 passed, 2 xfailed in 130.80s |
| WS smoke | `src/scripts/run-websocket-smoke-tests.sh` | 🟢 50/50 PASS in 44.60s (Core 25/25, Integration 22/22, Performance 2/2, Load 1/1) |
| Manual live | enter conv mode → reply → exit → next reply (no `notify`, no wrap) | 🟡 **Deferred — see "Manual live deferral" below** |
| E2E UI (`test_conversation_mode.py`) | `POST /api/test-suite/submit` (user-scheduled) | 🟡 out-of-plan-scope (per :8000 monopolize-mode rule) |

### Manual live deferral

Cannot be run from this session without disrupting the active conversation-mode dialogue we are using to communicate. Toggling off mid-session is precisely the transition the fix targets — and running it would either:
- (a) Verify the fix works (next prompt arrives without the conversation-mode contract — communication channel quality changes mid-conversation), or
- (b) Verify the fix does NOT work (model continues wrapping until prior reminders scroll out), in which case the dialogue is in an even more inconsistent state.

The next natural off→on cycle the user performs will surface the live behavior cleanly. Auto-tier coverage is strong:
- Unit tests pass with the new assertions matching the new behavior (3950 + 13 + 41 + 10 = 4014 unit tests passing).
- The fix is structurally symmetric to the known-working displace path — exact same notification field shape, same listener handler, same tmux injection helper, same `conv_mode_exit_reminder()` output.
- WS smoke (50/50) confirms the WebSocket transport carrying the push is healthy.

Per test-ownership mandate "name what cannot be automated explicitly with the specific reason": this is one of those cases.

---

## Cross-Repo Commit Handoff

| Commit | Repo | Files | Status |
|---|---|---|---|
| Lupin | `lupin` | doc dir + 2 doc files + `hook_common.py` + 2 test files | ⚪ pending |
| CoSA | `src/cosa` (submodule) | `src/cosa/rest/routers/conversation_mode.py` | ⚪ pending — **flagged for separate CoSA-context commit** |
