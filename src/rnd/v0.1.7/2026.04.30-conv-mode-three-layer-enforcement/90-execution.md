# Conversation Mode — Three-Layer Mic-Monopoly Enforcement | Execution Log

**Companion to**: `01-design.md`
**Started**: 2026-04-30
**Session**: 406cadbf

---

## Phase 0 — R&D doc serialization + adversarial review

**Status**: ✅ complete (2026-04-30)
**Outcome**:
- `01-design.md` + `90-execution.md` serialized
- Adversarial review pass executed 2026-04-30 (post-serialization, pre-execution)
- 9 findings raised (F1-F9): 3 Critical, 3 Important, 3 Minor
- Design doc revised to incorporate all findings — see §7 Adversarial-review summary table for resolution mapping
- Major design changes:
  - **§2.4 + Phase 1**: wrapper format initially changed to append-only system-reminder (F2). **Superseded 2026-04-30 per user direction**: restored two-surface XML wrap (`<voice-message>` + `<system-reminder>`) + added `sanitize_for_wrap` that strips from first `</voice-message` or `<system-reminder` to EOS before substitution. User caught that append-only was overcorrecting (giving up legible XML framing); sanitization at the boundary is the better-shaped fix.
  - **§2.5 + Phase 3**: Layer 2 gate is now bidirectional with audible-ding cross-talk cue (F1 — actually fixes the original symptom)
  - **§2.3 + Phase 2**: injection-point taxonomy reframed as inbound-vs-outbound, not voice-vs-everything-else (F3)
  - **Phase 3**: dynamic session_id resolution + `_internal_call=True` exemption (F4, F5)
  - **§5 Risks**: F6 documented as known limitation + explicit OOS; F7-F9 added as risks 8-10
  - **Phase 5**: per-callsite integration test row added (F8)
  - **Phase 6**: verification matrix expanded from 5 rows to 10 — adds cross-talk cue (row 3), legitimate alert (row 6), internal-call bypass (row 7), idempotency (row 9), prompt-injection regression (row 10)

---

## Phase 1 — `conv_mode_wrap` helper + `sanitize_for_wrap`

**Status**: ✅ complete (2026-04-30)
**Files**:
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — added `sanitize_for_wrap`, `_system_reminder_body`, `conv_mode_wrap`, plus `_SANITIZE_MARKERS` and `_CONV_MODE_WRAP_SENTINEL` constants. New `# ── Conversation Mode Wrap (Layer 1) ──` section before the `__main__` smoke test.
- `src/tests/unit/test_conv_mode_wrap.py` (NEW) — 27 unit tests across 5 test classes.

**Verification**:
- [x] py_compile clean (hook_common.py + test file)
- [x] Import chain clean (`from lupin_cli.claude_code.hooks.lib.hook_common import sanitize_for_wrap, conv_mode_wrap, _CONV_MODE_WRAP_SENTINEL`)
- [x] Unit tests pass — **27/27 in 0.07s**:
  - `TestSanitizeForWrap` × 11: neither marker, only `</voice-message`, only `<system-reminder`, both (first wins, both orderings), case-insensitive (upper + mixed), marker at start, partial-marker no-match, malformed-marker still strips
  - `TestConvModeWrapGate` × 5: session_id None/empty, text empty, conv mode inactive, fail-closed on bridge read error
  - `TestConvModeWrapVoiceSource` × 5: voice-message tag present, attrs (priority/suppress-ding), reminder mentions "voice from distance", sanitization-before-wrap (both injection patterns)
  - `TestConvModeWrapNonVoiceSource` × 4: terminal-typed has no voice-message tag, terminal reminder is voice-agnostic, hook-idle-prompt and hook-permission-prompt source attributions
  - `TestConvModeWrapIdempotency` × 2: voice and terminal sources both safe under double-wrap

**Notes**:
- Helper signature is keyword-only for `source` and `session_id` (per design doc). Caller MUST pass session_id explicitly — helper does not implicitly resolve via `get_claude_session_id()` because the listener subprocess context can't always reach the resolver reliably.
- Idempotency check uses substring match on `_CONV_MODE_WRAP_SENTINEL = "Conversation mode is active. After your response"` — short, unique, present in every wrapped output.
- Sanitization is conservative (case-insensitive, `text.lower().find(...)`); no regex, no parsing — minimum-blast-radius per `feedback_sanitize_at_boundary_not_format_strip`.
- Fail-closed on bridge read error: pass through unwrapped rather than wrap on stale state.

**Commit**: `02af97b` (5 files, 916+/1-).

---

## Phase 2 — Thread helper through injection points

**Status**: ✅ complete (2026-04-30)
**Files**:
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — added `conv_mode_reminder_block(source, session_id)` helper for reminder-only emission (used by hooks that can't transform user prompt directly), threaded `conv_mode_wrap` into `inject_qualifier_via_tmux` with source="hook-idle-prompt"
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — `_inject_via_tmux` now wraps `message_text` via `conv_mode_wrap(text, source="voice", session_id=self.session_id_hash)` before tmux send-keys
- `src/lupin_cli/claude_code/hooks/user_prompt_submit.py` — emits `conv_mode_reminder_block("terminal-typed", session_id)` via `additionalContext`; combines with voice_ctx when both present
- `src/tests/unit/test_conv_mode_wrap.py` — extended with `TestConvModeReminderBlock` (8 tests) covering the new helper
- `src/tests/unit/test_conv_mode_wrap_threading.py` (NEW) — integration-style tests for each threading site (4 tests across 3 test classes)

**Verification**:
- [x] py_compile clean across all 3 touched files (`hook_common.py`, `cc_notification_listener.py`, `user_prompt_submit.py`)
- [x] Import chain clean (`from ...hook_common import conv_mode_wrap, conv_mode_reminder_block, sanitize_for_wrap` + listener import)
- [x] Phase 1 + Phase 2 unit + integration tests pass — **39/39 in 0.34s**
- [x] Existing test_cc_notification_listener.py + test_session_bridge_lookup.py regression — **93/93 in 0.16s** (no regression)
- [x] Combined Phase 1+2 + regression — **132 tests green**

**Sweep results** (per design doc §7 mandate):
- `cc_notification_listener._inject_via_tmux` → INBOUND, threaded ✅
- `inject_qualifier_via_tmux` (hook_common) → INBOUND, threaded ✅
- `user_prompt_submit.py` → INBOUND (via additionalContext), threaded ✅ (reminder-only path; hooks can't transform user's prompt text directly per Claude Code hook contract)
- `anything_else_ask.fire_anything_else_ask` → OUTBOUND (NotificationRequest sent to user UI for yes/no), NOT threaded ✅
- `permission_request.py` → OUTBOUND (TTS to user via send_tts/_forward_to_user), NOT threaded ✅
- `pre_tool_use.py` + `post_tool_use.py` → INBOUND (drain voice buffer + emit additionalContext), but **deferred from Phase 2** — adding the reminder per-tool-call would inject it dozens of times per turn, which is noisy. Reminder fires at user-prompt-submit (natural turn boundary) only. Revisit if discipline drift is observed at tool-use boundaries.
- Listener `_send_gist_response` (the path fixed in commit `2eaeffc` earlier today) → OUTBOUND TTS receipt, NOT threaded ✅

**Notes**:
- The Claude Code UserPromptSubmit hook contract does NOT allow transforming the user's typed prompt — only emitting `additionalContext` (appended) or `decision: block`. So `user_prompt_submit` uses `conv_mode_reminder_block` to emit the reminder block alongside the user's prompt rather than wrapping the prompt itself. Functionally equivalent: Claude sees the reminder when conv mode is active.
- `anything_else_ask` was listed in the design doc Phase 2 file list but audit shows it's outbound-only. The inbound path that flows from the "Anything else?" qualifier reply is `inject_qualifier_via_tmux`, which IS threaded. Design doc §7 sweep-check table updated.
- Voice content threaded via `source="voice"` (full XML wrap with `<voice-message>` tag); qualifier inject via `source="hook-idle-prompt"` (system-reminder-only since the qualifier is a typed-style reply, not raw voice).

**Commit**: TBD (filled in after commit lands).

---

## Phase 3 — `_notify_impl` param override

**Status**: ⏳ pending Phase 2
**Files**:
- `src/lupin_mcp/cosa_voice_mcp.py`
- `src/tests/unit/test_notify_impl_conv_mode_override.py` (NEW)

**Verification**:
- [ ] py_compile clean
- [ ] Unit tests: active overrides params, inactive passes through, code-block stripping correctness, internal callers (set_session_topic) not affected
- [ ] Existing MCP smoke test still passes

**Notes**: TBD on landing.

---

## Phase 4 — Stop-hook auto-narrate

**Status**: ⏳ pending Phase 3
**Files**:
- `src/lupin_cli/claude_code/hooks/stop.py`
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (extend)
- `src/tests/unit/test_stop_hook_auto_narrate.py` (NEW)
- extend `src/tests/unit/test_session_bridge_lookup.py`

**Verification**:
- [ ] py_compile clean
- [ ] Unit tests: dedup via turn id, skip when notify present, transcript parsing, code-block stripping
- [ ] Bridge round-trip + per-session isolation
- [ ] Idle-aware Stop hook coexistence verified (no double-fire, no interaction)

**Notes**: TBD on landing.

---

## Phase 5 — Comprehensive automated testing

**Status**: ⏳ pending Phase 4
**Files**:
- extend `src/tests/smoke/test_cc_notification_listener.py`
- `src/tests/smoke/test_conv_mode_three_layer_e2e.py` (NEW, dry-run-able on :7999)

**Verification**:
- [ ] All unit tests pass (Phases 1-4 union)
- [ ] Smoke tests pass on :7999
- [ ] WebSocket smoke test still passes (no conv-mode mutex regression)
- [ ] Combined test result tabulated

**Notes**: TBD on landing.

---

## Phase 6 — Live multi-session verification (USER GATE)

**Status**: ⏳ blocked on user confirmation per `feedback_e2e_two_phase_gate`

**User confirms**:
- [ ] No parallel CC sessions outside the test
- [ ] Conv mode currently OFF on all sessions
- [ ] :7999 acceptable for dev verification (or :8000 slot if needed)

**Verification matrix** (from design doc §4 Phase 6):
- [ ] Toggle A on → speak voice msg → A's Claude wraps input + narrates with priority=high
- [ ] Toggle B on (displaces A) → speak to B → A's bridge=false; A's UI unpinned; A's next turn does NOT auto-narrate
- [ ] Console-only response from A while in conv mode → Layer 3 synthesizes narration
- [ ] Claude calls `notify(priority="medium")` while in conv mode → Layer 2 forces priority="high", suppress_ding=True
- [ ] Conv mode OFF → speak → no wrapper applied (legacy behavior)

**Notes**: TBD on completion.

---

## Surprises / Deviations

(populated as work proceeds — items here only if reality diverges from design)

---

## Final Summary

(populated at session end / phase-6 close)
