# Execution Log — Voice Persona /clear Preservation Fix

**Design doc**: `01-design.md` (read first)
**Scheduled execution**: 2026-05-03 AM
**Author of design**: claude.code@lupin.deepily.ai#4ede5bad (2026-05-02)

## Phase status

| Phase | Subject | Started | Completed | Outcome | Session |
|---|---|---|---|---|---|
| 1.1 | Diagnostic prints in register_session.py (Steps 1.1) | 2026-05-03 AM | 2026-05-03 AM | ✅ landed | aacd24b4 |
| 1.2 | Reproduce + identify failed gate (user does /clear) | 2026-05-05 PM | 2026-05-05 PM | ✅ captured: `vp_is_dict=False` in BOTH success (d5e3cf21) and failure (532b16e1) cases — proved the gate-3 hypothesis WRONG; pointed to upstream bridge mutation | d5e3cf21 |
| 1.3 | Apply minimal patch to gate logic | 2026-05-05 PM | — | ❌ OBSOLETE — root cause overturned (see 01-design.md §0). Replaced by §0.4 fix in `session_end.py` | d5e3cf21 |
| 1.4 | Sweep check + patch lines 699-703 if same gate change applies | 2026-05-05 PM | 2026-05-05 PM | NO-OP — §0 finding does not affect idle-block carry-forward (session_end does not null idle state) | d5e3cf21 |
| 1.5 | Unit tests at src/tests/unit/test_register_session_preservation.py | 2026-05-03 AM | 2026-05-03 AM | ✅ 8 passed + 1 xfailed (the xfail `test_legacy_session_ids_match_preserves` is pinned to the wrong hypothesis — being replaced by `test_session_end_skips_release_on_clear`) | aacd24b4 |
| 2 | Add `_release_voice_persona_via_http` helper + invoke before bridge overwrite | 2026-05-03 AM | 2026-05-03 AM | ✅ landed (kept as defense-in-depth per §0.5 disposition) | aacd24b4 |
| 3 | Add `previous_persona_name` query param to /allocate + push announcement | 2026-05-03 AM | 2026-05-03 AM | ✅ landed (router edit + hook threaded `previous_persona_name` kwarg through `_allocate_voice_persona_via_http`) | aacd24b4 |
| §0.4 | Apply reason-guard fix in session_end.py | _pending_ | | _in progress — d5e3cf21_ | d5e3cf21 |
| §0.4 tests | New unit tests at src/tests/unit/test_session_end.py | _pending_ | | _in progress — d5e3cf21_ | d5e3cf21 |
| 1F | Remove diagnostic prints from register_session.py once §0 fix verified | _pending_ | | _will land after live verification_ | d5e3cf21 |
| Verify (§0) | py_compile + import chain + new unit tests + full unit suite + WS smoke | _pending_ | | _in progress — d5e3cf21_ | d5e3cf21 |

## Notes

(append per-phase findings, decisions, and any drift from the design as it lands)

### Phase 1.1 — Diagnostic prints

✅ Landed in Session aacd24b4 (2026-05-03 AM). Three stderr print statements added in `register_session.py`:
- **gate-result** — fires inside the FileExistsError → `if os.path.exists(session_file)` branch right after the `if old_session_id and old_session_id != session_id:` body, regardless of whether gate-3 fired. Prints `is_context_clear`, `old_sid`, `new_sid`.
- **gate-2-fail** — replaces the silent `pass` in the `except (json.JSONDecodeError, OSError)` handler. Binds `e` and prints `type(e).__name__: e`.
- **preserve-check** — fires unconditionally inside the broader `if session_id:` branch, immediately before the carry-forward `if`. Prints `is_context_clear`, `old_data_present`, `vp_is_dict`.

py_compile + import chain pass. Verified via two new tests in `TestPhase1Diagnostics`.

### Phase 1.2 — Reproduce + identify failed gate

✅ Completed in Session d5e3cf21 (2026-05-05 PM). Two diagnostic captures collected from `~/.claude/projects/-mnt-DATA01.../<UUID>.jsonl` files:

| Source | Diagnostic |
|---|---|
| Session 532b16e1 /clear (fail case, persona changed Tiberius→Domi) | `gate-result: is_context_clear=True ... vp_is_dict=False` |
| Session d5e3cf21 /clear (apparent success, persona stayed Tiberius) | `gate-result: is_context_clear=True ... vp_is_dict=False` |

**Both diagnostics are identical.** The "success" was random pool draw — d5e3cf21 was a fresh sub-session with no prior persona, so the post-/clear `/allocate` happened to redraw Tiberius. The shared `vp_is_dict=False` overturns the gate-3 hypothesis: the gate was NOT failing; the bridge truly had no `voice_persona` field at hook-read-time, because something nulled it BEFORE the SessionStart hook fired.

**Tracing the upstream null**: searched for all callers of `set_voice_persona( sid, None )` and found `session_end.py:224-226` calls `_release_voice_persona( session_id )` unconditionally on every SessionEnd hook fire — including `/clear` (which fires SessionEnd with `reason="clear"`). This is the bug. See `01-design.md §0` for the full root-cause writeup.

### Phase 1.3 — Patch gate logic

❌ OBSOLETE per Phase 1.2 finding. The gate is not the problem. Replaced by §0.4 fix in `session_end.py`.

### Phase 1.4 — Sweep idle_block carry-forward

NO-OP. The §0 root cause does not affect idle-block carry-forward — `session_end.py` does not null idle state on /clear, so the existing `register_session.py:806-810` carry-forward continues to work correctly. Verified by inspection of session_end.py main() — only `_release_voice_persona` and `kill_idle_waiter` fire; neither touches the bridge's `idle_detection` block.

### Phase 1.5 — Unit tests

✅ Landed at `src/tests/unit/test_register_session_preservation.py`. **9 tests across 3 classes**, all green except the planned xfail:

| Class | Test | Result |
|---|---|---|
| TestPreservationCases | test_fresh_start_no_lockfile_no_bridge | ✅ PASS |
| TestPreservationCases | test_clear_with_persona_preserves | ✅ PASS |
| TestPreservationCases | test_clear_without_persona_no_preservation | ✅ PASS |
| TestPreservationCases | test_clear_corrupted_bridge_no_preservation | ✅ PASS |
| TestPreservationCases | test_legacy_session_ids_match_preserves | ⚠️ XFAIL — pinned to Phase 1.3 |
| TestPhase1Diagnostics | test_gate_result_logs_after_clear_detected | ✅ PASS |
| TestPhase1Diagnostics | test_preserve_check_logs_with_state | ✅ PASS |
| TestReleaseAndReAssignWiring | test_no_persona_on_old_bridge_skips_release | ✅ PASS |
| TestReleaseAndReAssignWiring | test_alloc_receives_no_previous_name_when_no_old_persona | ✅ PASS |

Mocking strategy: `monkeypatch.setenv("HOME", tmp_path)` redirects `~/.claude/sessions`. All side-effect helpers in `register_session` (`_resolve_cc_pid`, `_spawn_listener`, `send_tts`, `_allocate_voice_persona_via_http`, `_release_voice_persona_via_http`, `log_payload`, `emit_json`, `_check_cosa_voice_status`, `detect_project`, `_find_tmux_session`, `_cleanup_old_listener`) are replaced with `MagicMock`. Tests run main() end-to-end and assert against the resulting bridge file + mock call records.

The xfail `test_legacy_session_ids_match_preserves` documents the contract Phase 1.3 will enforce (gate-3 broadens to accept `stable_session_id` membership in `old_data["session_ids"][]`). It will auto-flip to xpass once Phase 1.3 lands; remove the marker at that point.

### Phase 2 — Release-on-overwrite helper

✅ Landed in Session aacd24b4 (2026-05-03 AM):
- New `_release_voice_persona_via_http(server_url, project, stable_session_id) -> bool` mirrors the alloc helper: hook credentials login → `POST /api/cosa-voice/voice-persona/{sid}/release` → fail-soft. Same exception catalog, same 2s timeouts, returns `True/False`.
- Invocation in `main()`: right after the carry-forward conditional, before `idle_block` init. Fires when `not session_data.get("voice_persona") and old_data and isinstance(old_data.get("voice_persona"), dict)` — i.e., the carry-forward declined AND the old bridge had a persona. Computes project + server_url locally (separate from Phase 4.5's identical compute, by design — keeps the change scoped to Fix 2 only).

py_compile + import chain pass. Covered by `test_no_persona_on_old_bridge_skips_release` (negative case: release MUST NOT fire when old bridge had no persona).

### Phase 3 — Re-assigned announcement

✅ Landed in Session aacd24b4 (2026-05-03 AM):
- `src/cosa/rest/routers/voice_persona.py` — `allocate_voice_persona_endpoint` gained an `Optional[str]` `previous_persona_name` query parameter. After the existing `voice_persona_assigned` push (only on `newly_allocated=True`), conditionally pushes a `task`-typed notification "Voice re-assigned: {previous_persona_name} → {persona['display_name']}" with `priority=medium, suppress_ding=False, response_requested=False`, voice_persona = the new persona, sender_id = `build_sender_id_for_cc(session_id)`. Same try/except hygiene as the assigned push.
- `register_session.py` — `_allocate_voice_persona_via_http` gained an optional `previous_persona_name=None` kwarg that URL-encodes (`urllib.parse.quote`) and appends as `?previous_persona_name=…`. New `previous_persona_name` local in `main()` is captured from `old_data["voice_persona"]["display_name"]` at the same conditional that fires the release call, then threaded into the Phase 4.5 alloc call.

py_compile + import chain pass.

### Verify

| Layer | Result |
|---|---|
| py_compile (3 files) | ✅ OK |
| Import chain (cosa.rest.routers.voice_persona + lupin_cli.claude_code.hooks.register_session) | ✅ OK |
| Helper smoke (`python -m cosa.rest.voice_persona_helpers`) | ✅ all assertions passed |
| New unit tests (test_register_session_preservation.py) | ✅ 8 passed + 1 xfailed |
| Full unit suite (`pytest src/tests/unit/`) | ✅ 3950 passed, 2 xfailed, 0 failures in 132s |
| Endpoint smoke (curl `/allocate?previous_persona_name=Foo`) | ⏸ pending user — needs an allocatable session bridge that doesn't already have a persona |
| Manual /clear repro | ⏸ pending user — needs one /clear on a planning session to harvest the gate diagnostics |

### Side fix — flake in `test_voice_persona_helpers.py`

The first full-suite run surfaced a pre-existing structural flake in `TestAllocatePersonaForSession::test_picks_unallocated_when_pool_partially_occupied` (and the sibling `test_borrows_when_pool_fully_occupied` is fragile in the same way). Both write bridge files keyed by `os.getpid() + N` as synthetic PIDs. On host-side runs `_can_trust_host_pids()` returns True, so `find_active_voice_persona_sessions` filters out bridges whose synthetic PIDs are dead — undercounting the occupied set. The "fix" pre-this-session: those `getpid()+N` PIDs *happened* to be alive at the moment the suite ran (likely owing to subprocess churn from earlier tests). Adding the new `test_register_session_preservation.py` shifted timing enough to flip the dice.

Repaired with a **class-level autouse fixture** in `TestAllocatePersonaForSession` that patches `_can_trust_host_pids` to return False — bypassing the alive-PID filter for that class only, mirroring the in-container path. Per `feedback_sweep_for_pattern_offenders` the fixture covers both broken tests in the class. `TestFindActiveVoicePersonaSessions::test_skips_dead_pid_bridges` deliberately exercises the dead-PID-skip path; it explicitly patches `_can_trust_host_pids → True` inside its own scope and is unaffected.

File touched: `src/tests/unit/test_voice_persona_helpers.py` (added 14-line class-level autouse fixture).

## Open questions tomorrow's session may need to answer

- Where exactly does the SessionStart hook stderr land? (Hook process is launched by Claude Code; verify whether stderr is captured in `~/.claude/projects/.../<UUID>.jsonl` or a separate log.)
- Does the `--continue` double-fire pattern (line 608-609 in register_session.py) also fire on /clear? If yes, the second invocation reading its own freshly-written bridge is the most likely root cause and gate 3 needs the `session_ids[]` membership check.
- Are there existing unit tests for register_session.py that the new preservation tests should colocate with? Check `src/tests/unit/test_register_session*.py` first.

## Cross-references

- Predecessor design: `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` (§5 covers /clear preservation contract)
- Voice reference page (built earlier 2026-05-02): `src/fastapi_app/static/html/test/voice-persona-reference.html`
- Sample endpoint (built earlier 2026-05-02): `POST /api/cosa-voice/voice-persona/sample` in `src/cosa/rest/routers/voice_persona.py`
