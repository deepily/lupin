# Phase 5b Execution Log — 4-Variant Rider Matrix + Brevity Migration

**Date**: 2026-05-12 (PM EDT)
**Owner**: [LUPIN] (Rio session 83ba1e51)
**Companion design doc**: [`14-phase5-hook-rider-design.md`](14-phase5-hook-rider-design.md)
**Predecessor commit**: `e17d7d7` ([LUPIN] Phase 5: Hook layer renames — speakerphone_* helpers + action handler)
**Status**: ✅ Complete — code landed on disk, tests green, awaiting Rick commit auth

---

## 1. Scope as executed

Phase 5 (commit `e17d7d7`) landed function-name renames only — the prose body inside
`_system_reminder_body` still said "Conversation mode is active." Phase 5b
landed the rest of the design doc:

- Replaced the 1-variant `_system_reminder_body(source)` private with a
  4-variant `_speakerphone_reminder_body(source, mode, speakerphone_on)`
  that branches on `(mode, speakerphone_on)`.
- Added three private helpers: `_source_preamble(source)`, `_brevity_rules()`,
  `_routing_reminder()`.
- Migrated CLAUDE.md brevity + routing content into the speakerphone-on rider
  variant (predecessor of the Phase 6 CLAUDE.md surgery).
- **Behavior change**: rider now fires on EVERY turn when session_id resolves.
  Before 5b, the rider was gated on `speakerphone_on=True`. After 5b, the
  rider always fires; content varies by `(mode, speakerphone_on)`. This
  matches `14-phase5` §3.2 explicitly.
- Sentinel rename: `_CONV_MODE_WRAP_SENTINEL = "Conversation mode is active. After your response"` →
  `_SPEAKERPHONE_WRAP_SENTINEL = "This session has speakerphone mode"` (matches both ON and OFF variants).
- `speakerphone_exit_reminder()` → `speakerphone_exit_reminder(mode)` —
  solo body covers displaced-or-toggled-off, chorus body omits displacement framing.
- Caller (`cc_notification_listener._inject_exit_conversation_reminder`) now passes
  `cu.get_tts_interaction_mode()` to the exit reminder.

## 2. Sweep audit (per `feedback_sweep_for_pattern_offenders`)

Pre-execution sweep across parent + CoSA + lupin_mcp:

```bash
grep -rn 'conv_mode_|conversation_mode|_CONV_MODE_WRAP_SENTINEL|enter_conversation_mode|exit_conversation_mode' \
    src/lupin_cli/ src/lupin_mcp/ src/cosa/ 2>/dev/null | grep -v 'pyc|__pycache__|history|2026.04|2026.05'
```

Hits and resolutions:

| File | Issue | Resolution |
|---|---|---|
| `src/lupin_cli/claude_code/hooks/lib/hook_common.py` | `_CONV_MODE_WRAP_SENTINEL`, `_system_reminder_body`, "conv-mode" comments | Renamed sentinel; rewrote body builder; updated comments to reference Phase 5 design doc |
| `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` | "Phase 2 — Layer 1 threading" comments referencing old design doc | Updated to reference Phase 5 design doc |
| `src/lupin_cli/claude_code/hooks/lib/session_bridge.py:600` | Docstring "conversation_mode toggle" | → "speakerphone toggle" |
| `src/cosa/rest/commons_rate_limiter.py:16` | Comment refs `_conversation_mode_lock` (stale Phase 2 sed) | → `_speakerphone_lock` |
| `src/cosa/rest/routers/voice_persona.py:57` | Comment refs `conversation_mode addendum §11` | → `_speakerphone_lock` reference |
| `src/cosa/rest/routers/speakerphone.py:233` | Historical rename note "renamed from conv_mode_exit_reminder in Phase 5" | Simplified to mode-aware body description |

## 3. Bug found mid-implementation (Phase 2 sed regression)

`session_bridge.set_speakerphone` had a botched Phase 2 sed-rename:

```python
data[ "speakerphone_on" ] = bool( on )
data[ "format_version" ] = BRIDGE_FORMAT_VERSION
data.pop( "speakerphone_on", None )   # ← popping what we just set!
```

The pop should target the legacy v1 key `conversation_mode_active`, not the
v2 key. This bug caused 7 pre-existing test failures in
`test_session_bridge_speakerphone.py` and `test_session_bridge_lookup.py::TestConversationMode`
that were silently masked by Phase 5's narrower test selection. Fixed by
restoring the legacy key name in the pop call (single-line change).

Per `feedback_fix_all_failing_tests` — never defer pre-existing failures
even when they're "out of phase scope."

## 4. Files touched

### Parent Lupin (will be committed)

- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` — Phase 5b body
  rewrite + always-fire rider + new private helpers + sentinel rename
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` — exit
  reminder caller passes mode; comment + docstring updates
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` — set_speakerphone
  pop-target bug fix + comment update
- `src/tests/unit/test_speakerphone_wrap.py` — full rewrite (52 tests
  parameterized over the 4-variant matrix)
- `src/tests/unit/test_speakerphone_wrap_threading.py` — RENAMED from
  `test_conv_mode_wrap_threading.py` + sed-replace of legacy names
- `src/tests/unit/test_user_prompt_submit_hook.py` — 2 tests renamed to
  reflect always-fire rider semantics
- `src/tests/unit/test_stop_hook.py` — 1 test method renamed (cosmetic);
  2 inject-qualifier tests patched with wrap-identity mock
- `src/tests/unit/test_idle_waiter.py` — 1 test method renamed (cosmetic)
- `src/tests/unit/test_session_bridge_lookup.py` — listener tmux test
  patched with wrap-identity mock
- `src/tests/unit/commons/test_commons_router.py` — sed-replaced
  `conversation_mode_active` → `speakerphone_on` to match `commons.py`
  response field (post-Phase-3 rename)
- `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/95-phase5b-execution-log.md` — this file

### CoSA submodule (edited; Rick handles git separately per `feedback_lupin_only_never_cosa`)

- `src/cosa/rest/commons_rate_limiter.py` — comment
- `src/cosa/rest/routers/voice_persona.py` — comment
- `src/cosa/rest/routers/speakerphone.py` — comment

## 5. Verification

| Layer | Result |
|---|---|
| `py_compile` (all touched parent files) | ✅ Pass |
| Phase 5b targeted unit tests (`test_speakerphone_wrap.py`) | ✅ 52/52 pass |
| Hook layer regression (idle_waiter, stop_hook, ups hook, notify_impl override, session_bridge round-trip, speakerphone router) | ✅ 259/259 pass |
| Full unit regression (`pytest src/tests/unit/`) | ✅ 4267 passed, 1 xfailed, 0 failures |

Test count delta: Phase 5 baseline was 150 hook-layer tests. After 5b
the targeted file alone has 52 tests, and full regression is 4267. The
~30-test growth in the targeted file covers the 4-variant matrix
(solo+speaker, solo+phone, chorus+speaker, chorus+phone), the unknown-mode
fallthrough, and the per-variant `_brevity_rules` / `_routing_reminder`
presence assertions.

## 6. Deviations from design doc

| Deviation | Rationale |
|---|---|
| Public `speakerphone_reminder_block` API kept 2-arg `(source, session_id)` instead of the 3-arg pure form in §3.1 | The §3.1 example was the BODY BUILDER; the public-API wrapper does the bridge + mode reads itself. The body builder is private as `_speakerphone_reminder_body(source, mode, speakerphone_on)`. Cleaner caller API (no mode-leaking to UPS hook) |
| `speakerphone_wrap` keeps the fail-closed gate when bridge or mode read errors out, instead of always-emitting on error | Preserves the F2-fix safety property: when state is uncertain, don't wrap. The 4-variant matrix only applies when state is known |
| Unknown mode falls through to the chorus body in `speakerphone_exit_reminder` | Matches the INI default (`chorus`) and the same default in `_get_default_speakerphone`. Test `test_unknown_mode_falls_through_to_chorus` pins this |
| Brevity rules trimmed slightly from CLAUDE.md verbatim — combined "60 words" + "80-120 words" into one sentence | Per design doc §6 Risk #2, token cost mitigation. Still preserves all rules; removes paragraph framing |

## 7. Outstanding follow-ups (handed off)

- **CoSA submodule git ops**: Rick commits `commons_rate_limiter.py`,
  `voice_persona.py`, `speakerphone.py` comment fixes separately.
- **Phase 6**: CLAUDE.md surgery + skill rename. The brevity-rules + routing
  content is now in the rider, so CLAUDE.md can be slimmed. Next phase.
- **Phase 7**: Multiplexer UI (biggest phase).
- **Phase 8**: Deferred per canonical plan.

## 8. Memory checks (per design doc §7)

- [[feedback_no_migration_code]] — no aliases for old function names; hard cut. ✓
- [[feedback_sweep_for_pattern_offenders]] — full grep audit done; all hits resolved. ✓
- [[feedback_enumerate_all_activation_paths]] — voice / typed / idle / permission sources all in the 4-variant matrix. ✓
- [[feedback_recraft_speech_dont_pipe_terminal]] — encoded in `_brevity_rules()`. ✓
- [[feedback_acknowledge_receipt_before_tool_work]] — encoded in `_brevity_rules()`. ✓
- [[feedback_no_duplicate_notify_in_conversation_mode]] — "speak only the closing turn" implicit in brevity rules. ✓
- [[feedback_fix_all_failing_tests]] — found and fixed 7 pre-existing bridge test failures. ✓
- [[feedback_lupin_only_never_cosa]] — edited CoSA comments; will NOT commit them from parent. ✓
- [[feedback_audit_plans_at_execute_time]] — discovered Phase 5 only landed function renames, executed the body matrix work on top. ✓
