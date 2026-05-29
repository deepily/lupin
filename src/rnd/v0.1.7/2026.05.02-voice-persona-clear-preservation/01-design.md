# Voice Persona /clear Preservation — Design Doc

**Author session**: claude.code@lupin.deepily.ai#4ede5bad (2026-05-02)
**Status**: Design approved 2026-05-02 evening; execution scheduled for 2026-05-03 AM
**UPDATE 2026-05-05 PM (Session d5e3cf21)**: Root cause overturned — see §0 below. The Fix 1 work in `register_session.py` (Phases 1.1, 1.5) is preserved as instrumentation; the actual fix is a 3-line guard in `session_end.py`.
**Predecessor**: `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` (original per-session voice persona feature; §5 covers the /clear preservation contract this doc fixes)

## 0. UPDATE — Root cause overturned (2026-05-05 PM, Session d5e3cf21)

**TL;DR**: The bug is NOT in `register_session.py` gate-3 (the suspect ranked #1 in §3 Step 1.3 below). It is in `session_end.py:224-226`, which unconditionally releases the voice persona on EVERY SessionEnd hook fire — including `/clear`, not only on process exit.

### 0.1 What changed the picture

Phase 1.2 diagnostic capture from session 532b16e1's /clear at ~18:12 EDT (memory file mis-stated as 22:12 EDT — that was the UTC `assigned_at` timestamp confused with local time):

```
[register_session] gate-result: is_context_clear=True old_sid='e3ae75cc-…' new_sid='d9aac370-…'
[register_session] preserve-check: is_context_clear=True old_data_present=True vp_is_dict=False
```

Compared against session d5e3cf21's /clear at 19:14 EDT today:

```
[register_session] gate-result: is_context_clear=True old_sid='d5e3cf21-…' new_sid='a4e62678-…'
[register_session] preserve-check: is_context_clear=True old_data_present=True vp_is_dict=False
```

**Both diagnostics are identical.** Both report `vp_is_dict=False`. Yet:
- Session 532b16e1: persona changed Tiberius → Domi (failure observed)
- Session d5e3cf21: persona "preserved" as Tiberius (success appeared)

The d5e3cf21 success was lottery — that sub-session was a fresh start with no prior persona allocated, so the post-/clear `/allocate` happened to draw Tiberius from the pool. Both sessions actually hit the same bug; only random pool draws differed.

### 0.2 Real root cause

`src/lupin_cli/claude_code/hooks/session_end.py:209-269` runs Phase 1.5:

```python
def main():
    payload = read_hook_input()
    session_id = payload.get( "session_id", "" )

    # ── Phase 1.5: Release voice persona (best-effort) ────────────────────
    if session_id:
        try:
            _release_voice_persona( session_id )
        except Exception as e:
            print( f"[session_end] WARNING: voice persona release wrapper failed (...)", file=sys.stderr )
```

There is **no check on `payload["reason"]`**. Claude Code's SessionEnd hook fires on:
- `clear` — user pressed `/clear`
- `compact` — user pressed `/compact` (or auto-compact triggered)
- `logout` — user logged out
- `prompt_input_exit` — Ctrl+D
- `other` — process termination

`_release_voice_persona` (`session_end.py:82-166`) calls the helper, which:
1. Logs in via hook credentials
2. POSTs `/api/cosa-voice/voice-persona/{stable_session_id}/release`
3. Server-side `release_voice_persona_endpoint` (`src/cosa/rest/routers/voice_persona.py:248-269`) calls `set_voice_persona( session_id, None )`
4. `set_voice_persona` (`src/lupin_cli/claude_code/hooks/lib/session_bridge.py:925-964`) reads the bridge JSON, sets `data["voice_persona"] = None`, writes the bridge back

So the sequence on `/clear` is:
1. **SessionEnd hook fires** with `reason="clear"` → POST `/release` → server writes `voice_persona: null` to bridge
2. **SessionStart hook fires** for the new transient session_id → reads bridge, sees `voice_persona: null`, `vp_is_dict=False` → carry-forward gate (line 770) correctly skips → Phase 4.5 `/allocate` rolls a fresh random persona

The carry-forward in `register_session.py:770` is **doing exactly what it should** — declining to carry forward a `None` value. The bug is upstream in SessionEnd nulling the field on /clear.

### 0.3 Why the gate-3 hypothesis (§3 Step 1.3 candidate 1) is disproved

The gate-3 candidate predicted `is_context_clear=False` because the double-fire would overwrite the bridge with the new transient before the second SessionStart read it. The captured diagnostic shows `is_context_clear=True` in both cases — gate-3 fired correctly. The failure point is downstream of gate-3, not at it.

### 0.4 Revised fix plan

Replace the §3 Fix 1 work in `register_session.py` (already landed as instrumentation in Phases 1.1, 1.5) with a single edit in `session_end.py`:

**File**: `src/lupin_cli/claude_code/hooks/session_end.py`
**Change shape**: ~3 lines around line 224.

```python
# ── Phase 1.5: Release voice persona (best-effort) ────────────────────
# Only release on actual session termination — NOT on /clear or /compact,
# which are intra-session lifecycle events the user expects to be
# transparent to the persona system. SessionEnd fires for both, so we
# discriminate by the `reason` field in the hook payload.
# See: src/rnd/v0.1.7/2026.05.02-voice-persona-clear-preservation/01-design.md §0
reason = payload.get( "reason", "" )
if session_id and reason not in ( "clear", "compact" ):
    try:
        _release_voice_persona( session_id )
    except Exception as e:
        print( f"[session_end] WARNING: voice persona release wrapper failed (...)", file=sys.stderr )
```

Rationale for the allowlist of skipped reasons:
- `"clear"` — user-initiated context clear, persona must persist
- `"compact"` — same intent as clear (intra-session continuity)
- `"logout"` and `"prompt_input_exit"` and `"other"` — actual termination, release is correct

**New unit tests** at `src/tests/unit/test_session_end.py` (NEW — no tests exist for `session_end.py` today):

| Test | Setup | Assertion |
|---|---|---|
| `test_session_end_skips_release_on_clear` | mock payload `reason="clear"` | `_release_voice_persona` NOT called |
| `test_session_end_skips_release_on_compact` | mock payload `reason="compact"` | `_release_voice_persona` NOT called |
| `test_session_end_releases_on_exit` | mock payload `reason="other"` (or omitted) | `_release_voice_persona` called once |

**Verification matrix**: same shape as §5, with `session_end.py` added to py_compile + import chain.

### 0.5 Disposition of pre-existing fix work

| Phase | Original target | Disposition under §0 finding |
|---|---|---|
| Phase 1.1 | Diagnostic prints in `register_session.py` | KEEP for now — proved the instrumentation works; remove in Phase 1F cleanup once §0 fix lands |
| Phase 1.2 | Reproduce + identify failed gate | DONE — gate identified, but the diagnosed gate (vp_is_dict=False) was a *symptom*, not the cause. Cause is upstream in session_end. |
| Phase 1.3 | Apply gate fix in register_session.py | OBSOLETE — replaced by §0.4 fix in session_end.py |
| Phase 1.4 | Sweep idle-block carry-forward | RE-EVALUATE — §0 finding does not change idle-block carry-forward behavior unless session_end also nulls idle state (it does not, by inspection). Probably NO-OP. |
| Phase 1.5 unit tests | `test_register_session_preservation.py` (xfail on `test_legacy_session_ids_match_preserves`) | KEEP existing 8 passing tests. REPLACE the xfail test (it's pinned to the wrong hypothesis) with `test_session_end_skips_release_on_clear` lineage. |
| Phase 2 | Release-on-overwrite helper in `register_session.py` | KEEP — defense-in-depth still useful for corrupted-bridge cases, even though §0 fix prevents the common path from triggering it |
| Phase 3 | Re-assigned announcement on /allocate | KEEP — useful UX even when re-allocations are legitimate (e.g., post-logout) |
| Phase 1F | Remove diagnostic prints | DEFER until §0 fix verified live |

## 1. Context

### 1.1 Symptom
On 2026-05-02 the user heard a notification from session `0022baba` carrying the **Mr Radio** persona badge but spoken in **Tiberius's** voice. The user identified Tiberius unambiguously by playing it back against the new dev-tools voice-reference page (`/static/html/test/voice-persona-reference.html`, landed earlier this session). Hitting browser refresh re-rendered the sender card; the badge then matched the voice (Tiberius). So Tiberius was the *correct* persona for the bridge state at the moment of the leak — the badge was the stale element.

### 1.2 Trigger
The user did `/clear` on the planning session. After /clear, the bridge `cc-13599.json` had a fresh `voice_persona = Tiberius` written by the SessionStart hook → `/allocate` chain. The user expected the persona to carry forward (per design doc §5: "/clear should be invisible to the persona system"). It did not.

### 1.3 Root cause (confirmed)
The carry-forward at `src/lupin_cli/claude_code/hooks/register_session.py:682-683`:

```python
if is_context_clear and old_data and isinstance( old_data.get( "voice_persona" ), dict ):
    session_data[ "voice_persona" ] = old_data[ "voice_persona" ]
```

…did not fire. One of `is_context_clear`, `old_data`, or `old_data["voice_persona"]` was falsy at that line. Server-side stamping of subsequent notifications was correct (Tiberius's voice_id stamped fresh on each new outbound envelope). The frontend's `senderPersonaMap` cached the OLD Mr Radio persona under that sender_id (because no `voice_persona_released` event fired for the outgoing persona — the hook silently overwrites the bridge), and the existing sender-card DOM kept the old badge until the page was refreshed.

### 1.4 Why this matters
/clear is supposed to be invisible to the persona system. When preservation breaks silently, the user gets a randomly-different voice mid-session AND a stale badge that pretends nothing changed. This is exactly the failure mode that the dev-tools voice-reference page was built earlier today to disambiguate.

### 1.5 Hypothesis status (updated)
- **H1**: /clear preservation didn't fire → **CONFIRMED** (this doc fixes it)
- **H2**: stale persisted envelope carrying old voice_id → **disproved** (refresh syncs to current state, so envelopes are correct)
- **H3**: `find_session_path_by_id` returned wrong bridge → **disproved** (no 8-char prefix collision in current state)
- **H4**: suffix-less sender_id with stale senderPersonaMap → **disproved** (MCP always passes #suffix)

## 2. Detection logic walkthrough

`is_context_clear` defaults to False (function-local at line 597). It's set True only at line 643, conditional on a chain of gates:

```python
old_data         = None       # line 596
is_context_clear = False      # line 597
...
try:
    with open( stable_lockfile, "x" ) as f:    # line 614 — first SessionStart for this PID
        ...
except FileExistsError:                         # line 617 — subsequent (clear/compact/resume/--continue)
    try:
        with open( stable_lockfile ) as f:
            stable_session_id = f.read().strip()
    except OSError as e:
        ...

    if os.path.exists( session_file ):                              # ← gate 1
        try:
            with open( session_file ) as f:
                old_data = json.load( f )                           # ← gate 2 (parse)
            old_session_id = old_data.get( "session_id", "" )
            if old_session_id and old_session_id != session_id:     # ← gate 3
                is_context_clear = True
                _cleanup_old_listener( old_data, session_id )
        except ( json.JSONDecodeError, OSError ):
            pass                                                     # ← swallows failure silently
```

For preservation to fail at line 682, ONE of:
- **Gate 1**: bridge file missing (no `os.path.exists`)
- **Gate 2**: bridge JSON parse fails (catches OSError too — silent `pass`)
- **Gate 3**: `old_session_id` empty OR equal to new session_id
- **`voice_persona`**: not a dict (e.g., None, missing key, type mismatch)

We don't yet know which gate failed for the user. Step 1.1 below plants the print() statements that will tell us on the next /clear.

## 3. Fix plan

### Fix 1 — Diagnose and repair `/clear` preservation

**File**: `src/lupin_cli/claude_code/hooks/register_session.py`

**Step 1.1 — Add diagnostic prints** (CLI hook → stderr; `:7999` auto-reload not relevant since hook is a separate process):

| Line | Insert |
|---|---|
| After line 643 | `print(f"[register_session] gate-result: is_context_clear={is_context_clear} old_sid={old_session_id!r} new_sid={session_id!r}", file=sys.stderr)` |
| Just before line 682 | `print(f"[register_session] preserve-check: is_context_clear={is_context_clear} old_data_present={old_data is not None} vp_is_dict={isinstance((old_data or {}).get('voice_persona'), dict)}", file=sys.stderr)` |
| Inside `except` at line 645-646 | Replace `pass` with `print(f"[register_session] gate-2-fail: {type(e).__name__}: {e}", file=sys.stderr)` (and update the `except` to bind `e`). |

**Step 1.2 — Reproduce + patch**: ask user to do one /clear after Step 1.1 lands. Hook stderr lands in Claude Code's transcript log, accessible via `~/.claude/projects/-mnt-DATA01.../<UUID>.jsonl` or stderr capture wherever the hook redirects. Identify which gate failed; patch with the minimal change.

**Step 1.3 — Likely candidates** (rank-ordered):

1. **`old_session_id` was actually the stable_session_id (legacy bridge)**. Older bridges may have `session_id` populated with the stable id form. Then gate 3 sees `old_session_id != session_id` (true — different format) → fires. Or: bridges written *during* /clear by a parallel hook may have the NEW transient already → gate 3 fails (`old_session_id == session_id`). Mitigation: broaden gate 3 to also accept membership in `old_data["session_ids"][]`.
2. **Hook double-fire**. The `--continue` documented double-fire (line 608-609 comment) may also fire on /clear. The first invocation's lockfile create succeeds; second invocation reads its own freshly-written bridge → `old_session_id == session_id` → gate 3 fails. Same broadening as above mitigates.
3. **Bridge JSON parse failure** during a write race with another tool. Step 1.1's logging-on-exception gives us this signal directly.

**Step 1.4 — Sweep check**: the same `is_context_clear AND old_data AND isinstance(...)` carry-forward pattern is at lines 699-703 for `idle_block.backoff_index`. Same failure mode → same lost state. If gate 3 broadens, both carry-forwards benefit; verify both use the same fixed gate after Step 1.2.

**Step 1.5 — Unit tests** at `src/tests/unit/test_register_session_preservation.py` (new) covering:
- Fresh start (no lockfile, no bridge) → preservation N/A, `is_context_clear=False`
- /clear with persona (lockfile present, bridge with old transient session_id + voice_persona dict) → `is_context_clear=True`, persona preserved
- /clear without persona (lockfile present, bridge with old session_id, no voice_persona field) → no preservation
- /clear with corrupted bridge (bad JSON) → log warning via Step 1.1's exception logging, `is_context_clear=False`
- Legacy match: stable_session_id present in `old_data["session_ids"][]` but NOT as `old_data["session_id"]` → preservation fires (verifies Step 1.3 candidate 1's mitigation)

### Fix 2 — Emit `voice_persona_released` on hook overwrite without preservation

**File**: `src/lupin_cli/claude_code/hooks/register_session.py`

When old_data had a `voice_persona` dict AND `session_data["voice_persona"]` is unset after the carry-forward block (i.e., we're about to overwrite the bridge with no persona), call `/api/cosa-voice/voice-persona/{stable_session_id}/release` BEFORE writing the new bridge.

**Implementation**:
1. Add helper `_release_voice_persona_via_http( server_url, project, stable_session_id )` mirroring `_allocate_voice_persona_via_http` at lines 507-578 (login → POST /release → fail-soft on errors).
2. After the preservation block (line 683) and before the bridge write (lines 705-707):
   ```python
   if not session_data.get( "voice_persona" ) and old_data and isinstance( old_data.get( "voice_persona" ), dict ):
       _release_voice_persona_via_http( server_url, project, stable_session_id )
   ```

This guarantees the `voice_persona_released` event fires for the outgoing persona whenever Fix 1 *can't* preserve. The frontend's `senderPersonaMap.delete(sender_id)` at `notifications.js:5625` runs, so the next notification under that sender_id re-hydrates the map with the fresh stamp.

If Fix 1 is fully correct, Fix 2 fires only on legitimate non-preservable overwrites (corrupted bridge recovery, etc.) — defense-in-depth.

### Fix 3 — "Voice re-assigned" announcement on realloc

**File**: `src/cosa/rest/routers/voice_persona.py:135-211` (allocate endpoint).

Add an optional `previous_persona_name` query parameter. When `newly_allocated=True` AND the param is non-empty, push a user-facing notification right after the existing `voice_persona_assigned` broadcast at lines 191-200:

```python
if previous_persona_name:
    try:
        notification_queue.push_notification(
            message            = f"Voice re-assigned: {previous_persona_name} → {persona[ 'display_name' ]}",
            type               = "task",
            priority           = "medium",
            user_id            = authenticated_user_id,
            sender_id          = build_sender_id_for_cc( session_id ),
            voice_persona      = persona,
            suppress_ding      = False,
            response_requested = False
        )
    except Exception as ws_err:
        print( f"[VOICE-PERSONA] ⚠️ Re-assigned announcement push failed for session {session_id}: {ws_err}" )
```

The hook (register_session.py) captures `old_data["voice_persona"]["display_name"]` BEFORE writing the new bridge, threads it to the `/allocate` call as `previous_persona_name`. User hears the announcement spoken in their newly-assigned voice via TTS — pre-empts the "wait, why does this sound different?" confusion that triggered this whole investigation.

### Fix 4 — Frontend stale-badge propagation [PARKED]

**File**: `src/fastapi_app/static/js/notifications.js`

Locations (current line numbers, file is 16,797 lines as of 2026-05-02):
- `voice_persona_assigned`/`released` handlers: lines 5611-5631
- senderPersonaMap hydration on regular notification: lines 5664-5666
- `getVoiceIdForSender`: lines 8997-9000
- TTS playback voice_id selection: lines 13214-13220
- Mismatched-key bug context: lines 9555-9575 (referenced by the comment at line 5640)

**Fix shape**: when `voice_persona_assigned`/`released` arrives, walk persisted notifications + sender-card DOM under that sender_id; normalize session_id keys (full UUID ↔ 8-char prefix) consistently.

**Status**: PARKED. User is doing heavy WebSocket refactor on this file; we don't touch notifications.js this round. With Fixes 2 + 3 landed server-side, the frontend desync window collapses dramatically (`voice_persona_released` → `senderPersonaMap.delete` → fresh hydration on next notification) — this is no longer urgent.

## 4. Critical files

| File | Fix | Lines |
|---|---|---|
| `src/lupin_cli/claude_code/hooks/register_session.py` | 1 (diagnose+repair), 2 (release-on-overwrite) | 596-647 detection · 682-683 preservation · 699-703 idle carry-forward · 507-578 alloc helper · 705-707 bridge write |
| `src/cosa/rest/routers/voice_persona.py` | 3 (re-assigned announcement) | 135-211 (allocate endpoint) |
| `src/tests/unit/test_register_session_preservation.py` | 1 (unit tests) | NEW |
| `src/cosa/rest/voice_persona_helpers.py` | 5 (smoke extension) | `quick_smoke_test()` — extend with `_voice_persona_for_sender_id` 4-shape coverage |
| `src/fastapi_app/static/js/notifications.js` | 4 (PARKED) | 5611-5631 · 5664-5666 · 9555-9575 |

## 5. Verification

| Layer | Command / step |
|---|---|
| py_compile | `python -c "import py_compile; py_compile.compile('src/lupin_cli/claude_code/hooks/register_session.py', doraise=True); py_compile.compile('src/cosa/rest/routers/voice_persona.py', doraise=True)"` |
| Import chain | `PYTHONPATH=src python -c "from cosa.rest.routers import voice_persona; from lupin_cli.claude_code.hooks import register_session"` |
| Helper smoke | `PYTHONPATH=src python -m cosa.rest.voice_persona_helpers` |
| Unit test (new) | `pytest src/tests/unit/test_register_session_preservation.py -v` |
| Endpoint smoke | curl `/api/cosa-voice/voice-persona/{sid}/allocate?previous_persona_name=Foo` with JWT, confirm a `task` notification with re-assigned message arrives |
| Manual /clear repro | User does one /clear on a planning session. Expected: persona preserved (no announcement, no badge change). If still mis-firing, diagnostic prints (Step 1.1) tell us which gate failed → patch from there. |

## 6. Sweep check

Searched register_session.py for the same `is_context_clear AND old_data AND isinstance(...)` carry-forward pattern:
- **Line 682-683**: `voice_persona` (this fix)
- **Lines 699-703**: `idle_block.backoff_index` (same failure mode — fix together if Fix 1 broadens gate logic)

Searched cosa for similar bridge-preservation logic — none found outside register_session.py and the predecessor design doc reference.

## 7. Plan compliance audit

Re-checked against feedback memories:
- `feedback_phase0_serialization_prominence` ✅ — this R&D doc IS Phase 0; execution day's plan opens with "Read this doc"
- `feedback_plans_include_tracking_docs` ✅ — paired `90-execution-log.md` skeleton lives alongside
- `feedback_audit_plans_at_execute_time` ✅ — to be re-audited tomorrow before each fix is applied
- `feedback_lupin_only_never_cosa` ✅ — Fix 3 edits `src/cosa/rest/routers/voice_persona.py` but no git ops in src/cosa from parent context
- `feedback_cosa_edit_vs_manage_git` ✅ — editing CoSA source is allowed
- `feedback_never_auto_commit_push` ✅ — no commits planned
- `feedback_no_defensive_programming` ✅ — fix gate logic at source, not consumer
- `feedback_comprehensive_automated_testing` ✅ — py_compile + import chain + helper smoke + unit tests + endpoint smoke + manual repro all listed
- `feedback_fastapi_auto_reload` ✅ — no bounce volunteered
- `feedback_sweep_for_pattern_offenders` ✅ — sweep section above
- `feedback_explicit_attribute_access` ✅ — no `getattr` chains in proposed code
- `feedback_skip_rnd_doc_for_trivial_fixes` — N/A (this is non-trivial; user explicitly directed serialization)

## 8. Out of scope

- Restoring "Mr Radio" specifically to session 0022baba — separate user-driven action, not part of this fix. May be addressed by a future `POST /api/cosa-voice/voice-persona/{sid}/set` endpoint accepting a pool name (not in this round).
- Frontend stale-badge propagation (Fix 4) — PARKED for the JS refactor lane.
- Persona-pool changes, color/icon adjustments, or new voices.
