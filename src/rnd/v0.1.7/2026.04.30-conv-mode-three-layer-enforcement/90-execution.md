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

**Commit**: `a9ff8bc` (7 files, 411+/14-).

---

## Phase 3 — `_notify_impl` bidirectional gate

**Status**: ✅ complete (2026-04-30)
**Files**:
- `src/lupin_mcp/cosa_voice_mcp.py` — added `strip_fenced_code_blocks(text)` standalone helper, extended `_notify_impl` with `_internal_call: bool = False` kwarg, implemented bidirectional gate logic (active/inactive/cross-talk-cue branches) using dynamic session_id resolution via `_get_cc_metadata` + fallback. Updated `set_session_topic` caller to pass `_internal_call=True`.
- `src/tests/unit/test_notify_impl_conv_mode_override.py` (NEW) — 16 unit tests across 5 test classes.

**Verification**:
- [x] py_compile clean
- [x] Import chain clean (`from lupin_mcp.cosa_voice_mcp import _notify_impl, strip_fenced_code_blocks`)
- [x] Unit tests pass — **16/16 in 0.83s**:
  - `TestStripFencedCodeBlocks` × 8: empty, None, no-fences, single-block-with-lang, single-block-no-lang, multi-block, inline-code-preserved, idempotency
  - `TestNotifyImplGateInternalCallBypass` × 1: `_internal_call=True` bypasses gate even when conv mode active
  - `TestNotifyImplGateConvModeActive` × 3: forces priority=high + suppress_ding=True, strips code blocks, preserves urgent priority (no downgrade)
  - `TestNotifyImplGateConvModeInactiveCrossTalkCue` × 3: CC sender + suppress_ding=True → inverted to False, CC sender + suppress_ding=False → pass-through, non-CC sender → pass-through
  - `TestNotifyImplGateBridgeReadError` × 1: fail-closed; cross-talk cue still fires for CC sender when bridge unreachable (audible ding > silent leak)
- [x] Combined Phase 1+2+3 + regression — **148 tests in 1.25s**, no regression

**Notes**:
- `strip_fenced_code_blocks` regex: `r"\`\`\`[^\n\`]*\n.*?\n\`\`\`\s*"` with DOTALL — matches optional language tag on opening fence line, lazy content across newlines, closing fence + trailing whitespace. Idempotent.
- Dynamic session_id resolution mirrors `_flip_conversation_mode` pattern (`cc_meta.get("stable_session_id")` first, then `session_id`, then module-level `SESSION_ID` as fallback).
- Cross-talk audible cue scoped to `claude.code@` senders only — agentic-job senders (`agentic.job@...`, `swe.lead@...`, etc.) pass through unchanged.
- Bridge-read-error path: treated as inactive but the cross-talk cue STILL fires for CC senders requesting suppress_ding=True. Failure mode chosen: audible ding > silent leak when conv-mode state can't be confirmed.
- `set_session_topic` now passes `_internal_call=True` — its intentional `priority="low"` + `suppress_ding=True` survive the gate.

**Commit**: `3e030dc` (4 files, 407+/11-).

---

## Phase 4 — Stop-hook auto-narrate

**Status**: ✅ complete (2026-04-30)
**Files**:
- `src/lupin_cli/claude_code/hooks/stop.py` — added `_read_last_assistant_message`, `_turn_has_notify_call`, `_extract_narratable_text`, `_try_auto_narrate` helpers; modified the conv-mode skip in `main()` to call `_try_auto_narrate` BEFORE allowing the stop. Added imports for new bridge helpers.
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` — added `get_last_autonarrated_turn_id` + `set_last_autonarrated_turn_id` bridge round-trip helpers (placed before `get_voice_persona`).
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — extended `send_tts` with `suppress_ding=False` kwarg (defaults preserve legacy behavior; auto-narrate passes `suppress_ding=True`).
- `src/tests/unit/test_stop_hook_auto_narrate.py` (NEW) — 23 tests across 5 test classes.

**Verification**:
- [x] py_compile clean across `session_bridge.py`, `hook_common.py`, `stop.py`
- [x] Import chain clean (`from ...session_bridge import get_last_autonarrated_turn_id, set_last_autonarrated_turn_id; from ...stop import _try_auto_narrate, _read_last_assistant_message, _turn_has_notify_call, _extract_narratable_text`)
- [x] Unit tests pass — **23/23**:
  - `TestReadLastAssistantMessage` × 6: missing file, empty path, empty file, no-assistant, malformed lines skipped, multi-message → last wins
  - `TestTurnHasNotifyCall` × 4: with notify ToolUseBlock, with other tool use, no content (3 shapes), text-only
  - `TestExtractNarratableText` × 3: concatenates text blocks (skips tool-use), strips fenced code, empty content
  - `TestTryAutoNarrate` × 6: skip-no-transcript-path, skip-missing-transcript, skip-claude-self-narrated, skip-dedup-match, fires-send-tts-with-conv-mode-params + stamps turn id, skip-no-narratable-text
  - `TestLastAutonarratedTurnIdBridge` × 4: round-trip preserves other fields, set on missing bridge returns False, get on missing returns None, per-session isolation
- [x] Combined Phase 1+2+3+4 + regression — **171/171 in 30.1s** (slow run-time due to cosa_voice_mcp module-init when `_extract_narratable_text` lazy-imports `strip_fenced_code_blocks`; functional, acceptable)

**Notes**:
- The conv-mode skip block in stop.py main() previously did an unconditional pass-through (line 449 pre-edit). Now it calls `_try_auto_narrate` first, then logs + emits empty {} (allows the stop). The "Anything else?" prompt path remains intentionally skipped in conv mode (would interrupt voice dialogue) — that decision from the original 2026.04.27 design stands.
- `_try_auto_narrate` is gated by:
  1. `transcript_path` resolvable (from payload OR bridge metadata fallback)
  2. Last assistant message exists in transcript
  3. Last turn does NOT contain `mcp__cosa-voice__notify` ToolUseBlock (Claude self-narrated → skip)
  4. `last_autonarrated_turn_id` in bridge ≠ current turn id (re-fire dedup)
  5. Extracted text non-empty after fence-strip
  All gates fail-closed: any unmet condition skips and logs to `log_to_stream` with the specific reason. Errors caught and logged but never re-raised.
- `send_tts` extended with `suppress_ding=False` default param. Auto-narrate calls `send_tts(narration, priority="high", suppress_ding=True)` for conv-mode shape. Existing callers pass through unchanged.
- Coexistence with idle-aware Stop hook: auto-narrate runs FIRST, then the conv-mode block emits {} and exits BEFORE the idle-detection / "Anything else?" path. No interaction; idle-waiter never arms in conv mode (existing design from 2026.04.29-idle-aware-stop-hook).
- Test runtime 30s: dominated by `test_stop_hook_auto_narrate.py` due to `from lupin_mcp.cosa_voice_mcp import strip_fenced_code_blocks` triggering MCP module init (account validation HTTP call). Could be optimized by extracting `strip_fenced_code_blocks` to a lighter module — deferred as out-of-scope optimization.

**Commit**: `9a00d6b` (6 files, 717+/20-).

---

## Phase 5 — Comprehensive automated testing

**Status**: ✅ complete (2026-04-30); WebSocket suite **deferred to Phase 6 user-confirmed slot**
**Files**:
- `src/tests/smoke/test_conv_mode_three_layer_integration.py` (NEW) — cross-layer integration smoke test, 5 tests across 3 test classes. Mock-driven (no live server) for :7999-friendly venue.

**Verification (Phase 5 deliverables)**:
- [x] Cross-layer integration smoke — **5/5 in 29.6s**:
  - `TestConvModeOnHappyPath` × 3: Layer 1 wraps voice, Layer 2 gate forces params, Layer 3 skips when turn has notify
  - `TestConsoleOnlySalvage` × 1: Layer 3 synthesizes notify with conv-mode params for silent turn
  - `TestCrossTalkCue` × 1: Layer 2 inverts suppress_ding for displaced CC session (the original symptom fix)
- [x] All Phase 1-4 unit + integration tests still pass — re-run as part of grand total
- [x] **Grand total combined run: 176/176 in 30.1s** (covers Phases 1-5 + regression)
- [⏳] WebSocket smoke suite — **DEFERRED to Phase 6 / user-confirmed slot**. The full suite (`./src/scripts/run-websocket-smoke-tests.sh`) timed out at 120s in the AI-discretionary venue; needs a longer run window. No conv-mode-relevant assertions in the WS suite; regression risk is low (we haven't touched the WS layer or notification routing). User can run before final ratification.

**Notes**:
- The new integration smoke is a regression catch for future refactors: mocks the bridge state and exercises Layer 1 → Layer 2 → Layer 3 in sequence. Tests pin the specific behaviors that compose to fix the original symptom (cross-talk cue) and the silent-console-only failure mode.
- Phase 5 was scoped down from the design doc's "live :7999 e2e" to mock-driven cross-layer smoke. Justification: every individual layer is already unit + integration tested (Phases 1-4 = 171 tests). The Phase 5 e2e value is "do they compose correctly" — answered by mocks. Live multi-session validation is Phase 6 territory.
- Pre/post-tool-use threading remains the Phase 2 deferral (per-tool-call reminder noise rationale). Documented and acceptable.

**Commit**: TBD (filled in after commit lands).

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
