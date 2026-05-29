# Next Steps — Voice Persona /clear Preservation

**Author session**: claude.code@lupin.deepily.ai#aacd24b4 (2026-05-03 AM)
**Predecessor docs**: `01-design.md` · `90-execution-log.md`
**Checkpoint commit**: `2000cb4` (parent Lupin) — Phases 1.1 + 1.5 + 2 + 3

## 1. Where we are

Phases 1.1, 1.5, 2, and 3 are committed. Full unit suite green (3950 passed,
2 xfailed, 0 failures in 132s). Phase 1.2/1.3/1.4 still pending — they need
a user-driven `/clear` to harvest gate diagnostics.

The CoSA-side edit to `src/cosa/rest/routers/voice_persona.py` is uncommitted
and lives in the CoSA submodule's `git status` alongside any other CoSA work.

## 2. Outstanding work, by owner

### 2.1 User-owned

#### Step A — Commit the CoSA-side `/allocate` endpoint changes

From a CoSA-context session (`cd src/cosa`):

```bash
git status                                       # confirm only my edit + your own work
git add rest/routers/voice_persona.py            # ONLY this file from my work
git commit -m "Voice-persona /allocate: previous_persona_name query param + re-assigned announcement (paired with parent 2000cb4)"
```

Parent Lupin commit `2000cb4` is the documenting reference for this CoSA edit.

#### Step B — Phase 1.2 repro: harvest the gate diagnostics

Phase 1.1's stderr instrumentation is live on `:7999` (auto-reload picked
up the hook edit). The next time a SessionStart hook fires for a `/clear`
on a planning session, three stderr lines should appear:

| Line | When |
|---|---|
| `[register_session] gate-result: is_context_clear=… old_sid=… new_sid=…` | Inside the `if os.path.exists(session_file)` branch — fires whenever a bridge file is read |
| `[register_session] preserve-check: is_context_clear=… old_data_present=… vp_is_dict=…` | Inside the `if session_id:` branch — fires unconditionally |
| `[register_session] gate-2-fail: <ExcType>: <msg>` | Only if the bridge JSON parse raised |

**To repro**:

1. Start a planning CC session with a persona allocated (any session that
   has spoken at least one notification will have one).
2. Hit `/clear`.
3. Find the hook stderr. Open question from `90-execution-log.md`: does
   stderr land in `~/.claude/projects/-mnt-DATA01.../.../<UUID>.jsonl`,
   or somewhere else? If the JSONL doesn't carry it, check
   `~/.claude/sessions/cc-listeners.log` and any project-level hook log.
4. Paste the three lines (or whichever subset fires) into the next session
   so Phase 1.3 can be cut.

#### Step C — (optional) live endpoint smoke for Fix 3

Unit tests cover Fix 3, but a live curl is cheap and proves the wire-up:

```bash
# Pick an active session bridge that does NOT already have a persona
SID="$(jq -r 'select(.voice_persona == null) | .stable_session_id' \
        ~/.claude/sessions/cc-*.json 2>/dev/null | head -1)"
TOKEN="$(curl -sX POST http://localhost:7999/auth/login \
          -H 'Content-Type: application/json' \
          -d "{\"email\":\"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL\",\"password\":\"$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD\"}" \
          | jq -r .tokens.access_token)"
curl -sX POST "http://localhost:7999/api/cosa-voice/voice-persona/$SID/allocate?previous_persona_name=Foo" \
     -H "Authorization: Bearer $TOKEN"
```

Expected: response `newly_allocated=true`, plus a notification card on the
notifications UI showing "Voice re-assigned: Foo → <NewPersona>" spoken in
the new voice.

### 2.2 Claude-owned (after Step B lands data)

#### Step D — Phase 1.3 minimal gate patch

Apply the smallest change in `register_session.py:637-646` that explains
the diagnostic data from Step B. Three pre-ranked candidates per design
§3 Step 1.3:

1. **Most likely**: gate-3 fails because the hook double-fires on /clear
   (documented at `register_session.py:608-609`). The first invocation
   reads the legacy bridge with `old_session_id == legacy stable id`
   (gate-3 fires → preservation works). The second invocation reads the
   bridge the FIRST invocation just wrote, where `session_id` is now the
   NEW transient id (gate-3 sees equality → fails → no preservation in
   the second pass; the second pass overwrites the first's preserved
   bridge).

   **Fix shape**: broaden gate-3 to accept membership in
   `old_data["session_ids"][]`:

   ```python
   if old_session_id and old_session_id != session_id:
       is_context_clear = True
   elif stable_session_id in old_data.get( "session_ids", [] ) and stable_session_id != session_id:
       # Legacy: bridge.session_id was already overwritten with the new
       # transient by an earlier hook fire (documented double-fire on
       # /clear). The lockfile-stored stable id is still in session_ids[]
       # so we can detect the carry-forward case from the side channel.
       is_context_clear = True
   ```

   The xfail at `test_legacy_session_ids_match_preserves` will flip to
   xpass on this change.

2. Bridge JSON parse failure (gate-2). Diagnose via the new gate-2-fail
   line; usually a write-race signature. If it's a known-quantity race,
   defer fix to the file-locking work; if surprising, file as a separate
   bug.

3. Bridge file missing (gate-1). Diagnose via absence of the gate-result
   line entirely. Indicates the bridge was deleted between the prior
   session's writes and this hook fire — most likely a bug in stale-file
   purge.

Apply only the candidate that the diagnostic data actually fingers. Do
not over-fit.

#### Step E — Phase 1.4 sweep

The same `is_context_clear AND old_data AND isinstance(...)` carry-forward
pattern lives at `register_session.py:699-703` for `idle_block.backoff_index`:

```python
if is_context_clear and old_data and isinstance( old_data.get( "idle_detection" ), dict ):
    old_idle = old_data[ "idle_detection" ]
    if isinstance( old_idle.get( "backoff_index" ), int ):
        idle_block[ "backoff_index" ] = old_idle[ "backoff_index" ]
```

If Step D broadens gate-3 (candidate 1), this block automatically benefits
(both branches read the same `is_context_clear`). Verify by inspection
after Step D's diff is applied — no separate code change needed unless
the gate fix is structurally different.

If Step D's fix is gate-2 or gate-1 specific, the idle backoff carry-forward
suffers the same failure mode but a sweep may not be applicable. Re-evaluate.

#### Step F — Remove the diagnostic prints

Once Steps D + E land and the manual `/clear` repro confirms preservation
fires, the three stderr prints in `register_session.py` are dead weight.
Remove them as a single-line cleanup commit referencing this doc.

Diagnostic locations to remove:
- After line 643 (gate-result print)
- Around line 645 (the `as e` exception bind + gate-2-fail print → revert
  to bare `except (...): pass`)
- Around line 682 (preserve-check print)

#### Step G — Final verification matrix

After Step F:

| Layer | Command |
|---|---|
| py_compile | `python -c "import py_compile; py_compile.compile('src/lupin_cli/claude_code/hooks/register_session.py', doraise=True)"` |
| Import chain | `PYTHONPATH=src python -c "from lupin_cli.claude_code.hooks import register_session"` |
| Unit (this fix) | `pytest src/tests/unit/test_register_session_preservation.py -v` (xfail should now xpass; remove the marker) |
| Full unit suite | `pytest src/tests/unit/ -q` |
| WS smoke | `./src/scripts/run-websocket-smoke-tests.sh` |
| Manual /clear | One `/clear` on a planning session, hear the same persona post-clear |

Remove the `@pytest.mark.xfail` from `test_legacy_session_ids_match_preserves`
once Step D lands.

## 3. Adjacent unfinished items (not on this fix's critical path)

These are separate work, surfaced here so they don't get lost:

- **Frontend Fix 4 (PARKED)** — `notifications.js:5611-5631, 5664-5666,
  9555-9575`. Stale-badge propagation. User owns notifications.js during
  the WS refactor lane. With Fixes 2 + 3 landed, the desync window is
  much smaller (`voice_persona_released` → `senderPersonaMap.delete` →
  fresh hydration on next notification). Re-evaluate priority once the
  WS refactor settles.
- **Restoring "Mr Radio" specifically to session 0022baba** — out of
  scope per design §8. Would need a future
  `POST /api/cosa-voice/voice-persona/{sid}/set` endpoint that accepts a
  pool name. Not in this round.
- **Archive `history.md`** — sits at 17,138 tokens (just over the 17k
  WARNING threshold). Skipped this session at user direction. Run
  `/history-management mode=check` first; archive when convenient.
- **2026.05.01 19:00 EDT all-test-suite post-mortem follow-ups** — see
  `src/rnd/v0.1.7/2026.05.01-postmortem-test-suite-19h00.md`. Cheapest-first
  sequence at end of doc; steps 1-3 alone should drop the 10-failure
  count to ~3.

## 4. Cross-references

- Design: `01-design.md` (root cause, gate walkthrough, fix plan, sweep, audit)
- Execution log: `90-execution-log.md` (per-phase outcomes, side-fix writeup)
- Predecessor: `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` §5 (preservation contract)
- Voice reference page (built earlier 2026-05-02): `src/fastapi_app/static/html/test/voice-persona-reference.html`
- Sample endpoint: `POST /api/cosa-voice/voice-persona/sample` in `src/cosa/rest/routers/voice_persona.py`
- Parent checkpoint commit: `2000cb4`
