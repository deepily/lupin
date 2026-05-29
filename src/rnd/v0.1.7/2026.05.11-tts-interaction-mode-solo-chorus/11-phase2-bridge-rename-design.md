# Phase 2 — Bridge Field Rename + Mode-Aware Defaults

**Date**: 2026.05.12
**Status**: 📝 Design — not yet implemented
**Owner**: [LUPIN]
**Phase**: 2 of 8
**Prerequisites**: [Phase 1](10-phase1-ini-plumbing-design.md) (the `get_tts_interaction_mode()` helper must exist).
**Companion docs**: [`00-index.md`](00-index.md), [`01` (May 12 canonical plan)](2026.05.12-tts-interaction-mode-solo-chorus.md), [`02-background-synthesis.md`](02-background-synthesis.md)
**Execution log**: [`92-phase2-execution-log.md`](92-phase2-execution-log.md) (TBD — drafted at phase-end)

---

## 1. Goal

Rename the per-session bridge field from `conversation_mode_active` to `speakerphone_on` across the bridge layer. Bump the bridge file format version so old-format files get discarded on read. Make new-session defaults mode-aware: `false` in solo (today's behavior), `true` in chorus (at-distance default). Keep `find_active_conversation_sessions` renamed to `find_active_speakerphone_sessions` but **not deleted** — solo's displacement scan still uses it.

This phase preserves all behavior in solo mode and prepares the field for chorus-mode defaults.

---

## 2. Scope

### In scope

- Bridge schema field rename: `conversation_mode_active` → `speakerphone_on`.
- Helper renames in `src/lupin_cli/claude_code/hooks/lib/session_bridge.py`:
  - `get_conversation_mode` → `get_speakerphone`
  - `set_conversation_mode` → `set_speakerphone`
  - `find_active_conversation_sessions` → `find_active_speakerphone_sessions` (kept; still called by solo branch)
- Bridge format version bump (e.g., `format_version: 1` → `format_version: 2`).
- Old-format bridge handling: on read, discard + recreate with new defaults (no migration code per [[feedback_no_migration_code]]).
- Mode-aware default: new bridges default `speakerphone_on=false` in solo, `speakerphone_on=true` in chorus.
- Unit tests covering renames, default-per-mode, format-version handling.
- Smoke test (inline `quick_smoke_test()` in `session_bridge.py`) round-tripping the renamed helpers.

### Out of scope

- Consumer call-sites in `cosa_voice_mcp.py`, hooks, router (Phases 3–5 handle each consumer).
- Migration of old `conversation_mode_active` values into new bridges — explicitly NOT done per the no-migration-code rule. Old bridges are discarded and recreated with fresh defaults.
- Any visual / UI changes (Phase 7).
- The `last_autonarrated_turn_id` field added in three-layer enforcement Phase 4 — kept as-is; not part of this rename.

---

## 3. Deliverables

### 3.1 Bridge schema

**Before** (today's format):
```json
{
  "format_version": 1,
  "session_id": "83ba1e51",
  "stable_session_id": "83ba1e51-a354-4868-9544-e68ebbaabdd5",
  "conversation_mode_active": false,
  "last_autonarrated_turn_id": null,
  "session_topic": "...",
  "voice_persona": {...}
}
```

**After** (post-Phase 2):
```json
{
  "format_version": 2,
  "session_id": "83ba1e51",
  "stable_session_id": "83ba1e51-a354-4868-9544-e68ebbaabdd5",
  "speakerphone_on": false,
  "last_autonarrated_turn_id": null,
  "session_topic": "...",
  "voice_persona": {...}
}
```

The `speakerphone_on` default is computed at bridge-creation time by reading `get_tts_interaction_mode()` (Phase 1 helper):
- `solo` → `false`
- `chorus` → `true`

### 3.2 Helper renames (`session_bridge.py`)

| Old | New | Behavior |
|---|---|---|
| `get_conversation_mode(session_id)` | `get_speakerphone(session_id)` | Reads `speakerphone_on` from bridge; returns `False` if bridge missing/malformed (fail-closed). |
| `set_conversation_mode(session_id, active: bool)` | `set_speakerphone(session_id, on: bool)` | Writes `speakerphone_on` to bridge; creates bridge if missing. |
| `find_active_conversation_sessions()` | `find_active_speakerphone_sessions()` | Scans `SESSION_DIR` for bridges with `speakerphone_on=true`; returns list of session IDs. Kept because Phase 3's solo branch still uses it. |

All three are **hard renames** — no aliases. The old names disappear.

### 3.3 Format-version handling

**On read** (in helpers like `get_speakerphone`):

```python
def _read_bridge( session_id ):
    path = _bridge_path_for( session_id )
    if not path.exists():
        return None  # caller decides whether to create
    try:
        data = json.loads( path.read_text() )
    except Exception:
        # Malformed JSON — discard and recreate
        path.unlink( missing_ok=True )
        return None
    if data.get( "format_version" ) != 2:
        # Old format — discard and recreate with new defaults
        path.unlink( missing_ok=True )
        return None
    return data
```

**On create** (when bridge is missing or was just discarded):

```python
def _create_bridge( session_id, **session_context ):
    mode = get_tts_interaction_mode()
    default_speakerphone = ( mode == "chorus" )
    data = {
        "format_version"           : 2,
        "session_id"               : session_id,
        "speakerphone_on"          : default_speakerphone,
        "last_autonarrated_turn_id": None,
        # ... other fields preserved from session_context
    }
    _bridge_path_for( session_id ).write_text( json.dumps( data, indent=2 ) )
    return data
```

**Rationale**: per [[feedback_no_migration_code]], a format change discards rather than migrates. Old in-flight sessions lose their `conversation_mode_active` value on first read after the upgrade — acceptable cost since the rename is also a semantic boundary (new field, new default per new mode).

### 3.4 Unit tests

**File**: `src/tests/unit/test_session_bridge_speakerphone.py` (new)

Use `tempfile.TemporaryDirectory()` for storage isolation per [[Testing: Use tempfile.TemporaryDirectory() for storage isolation in tests]].

| Test | Setup | Assertion |
|---|---|---|
| `test_get_speakerphone_returns_false_when_bridge_missing` | Empty temp dir | Returns `False` |
| `test_set_speakerphone_creates_bridge_if_missing` | Empty temp dir | After `set_speakerphone(sid, True)`, bridge exists with `speakerphone_on=true, format_version=2` |
| `test_get_set_round_trip` | Set + immediately get | Round-trip preserves value |
| `test_default_solo_creates_false` | Mock `get_tts_interaction_mode` → `"solo"`; trigger bridge creation | New bridge has `speakerphone_on=false` |
| `test_default_chorus_creates_true` | Mock `get_tts_interaction_mode` → `"chorus"`; trigger bridge creation | New bridge has `speakerphone_on=true` |
| `test_old_format_v1_is_discarded` | Pre-write a v1-format bridge with `conversation_mode_active=true` | First read returns `False` (default — old bridge discarded) |
| `test_old_format_v0_is_discarded` | Pre-write bridge with no `format_version` field | First read returns `False` |
| `test_malformed_json_is_discarded` | Pre-write garbage bytes | First read returns `False` (file unlinked) |
| `test_find_active_speakerphone_sessions_scans_dir` | Create 3 bridges; 2 with `speakerphone_on=true` | Returns the 2 SIDs |
| `test_find_active_skips_v1_bridges` | Mix of v1 and v2 bridges | Only v2 bridges with `speakerphone_on=true` returned |
| `test_set_speakerphone_preserves_other_fields` | Pre-existing bridge with `session_topic` set; call `set_speakerphone(sid, True)` | `session_topic` unchanged after write |

### 3.5 Smoke test

Inline in `session_bridge.py` `quick_smoke_test()`:

```python
if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # Monkey-patch SESSION_DIR temporarily
        # ...
        set_speakerphone( "test", True )
        assert get_speakerphone( "test" ) is True
        set_speakerphone( "test", False )
        assert get_speakerphone( "test" ) is False
        print( "session_bridge speakerphone helpers: OK" )
```

---

## 4. Implementation order

1. Read `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` end-to-end to confirm the actual function signatures and the `SESSION_DIR` resolution path.
2. Apply renames: `conversation_mode_active` → `speakerphone_on`, all three helper functions.
3. Add format-version handling (discard-on-old-format).
4. Wire `get_tts_interaction_mode()` into bridge-creation default.
5. Update existing tests in `test_session_bridge.py` / `test_session_bridge_lookup.py` to use new names (rename calls but keep coverage).
6. Add new tests in `test_session_bridge_speakerphone.py`.
7. Run `python -m py_compile src/lupin_cli/claude_code/hooks/lib/session_bridge.py`.
8. Run `python -c "from lupin_cli.claude_code.hooks.lib import session_bridge; print('OK')"`.
9. Run new + existing bridge tests: `pytest src/tests/unit/test_session_bridge*.py -v`.
10. Run full unit suite for regressions: `pytest src/tests/unit/ -v`.

**Expected breakage at Phase 2 end**: every consumer of the old helpers (`get_conversation_mode`, `set_conversation_mode`, `find_active_conversation_sessions`, `conversation_mode_active`) will break. Phases 3–7 fix each consumer. **Phases 2–7 should land as a single PR** because partial merges leave the system in a half-renamed broken state.

---

## 5. Verification matrix

| Layer | Check | Venue | Pass criteria |
|---|---|---|---|
| `py_compile` | `session_bridge.py` | local | Compiles |
| Import chain | `from lupin_cli.claude_code.hooks.lib import session_bridge` | local | No error |
| Unit | `test_session_bridge_speakerphone.py` (new, 11 tests) | :7999 | 11/11 pass |
| Unit regression | All pre-existing bridge tests (with renamed call-sites) | :7999 | 100% pass |
| Unit regression (broader) | Full `pytest src/tests/unit/` | :7999 | Failures expected ONLY in tests that still call old names (Phases 3–7 fix); track them in the execution log |
| Manual smoke | Spin up dev session, verify bridge file has `format_version=2, speakerphone_on=false` | :7999 | Bridge file matches |
| Format-version discard | Pre-write a v1 bridge, start a session, verify file gets recreated as v2 | :7999 | New bridge replaces old |

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Bridge file is touched by other code paths (e.g., MCP server writing `session_topic`) — concurrent writes could miss the schema upgrade | All writers go through `_read_bridge` + `_create_bridge` helpers. Read returns `None` for old format → caller recreates. Atomic write via `Path.write_text`. No multi-process locking needed for the rename itself. |
| 2 | Old-format discard loses session_topic / voice_persona / autonarrate state on first read after upgrade | Acceptable. Sessions are short-lived; persona will re-allocate. Documented in the splainer entry or commit message. |
| 3 | Consumer call-sites in `cosa_voice_mcp.py` are NOT updated in this phase — every consumer call breaks | This is by design — Phases 2–7 ship together. Phase 2 alone is intentionally incomplete. |
| 4 | `find_active_conversation_sessions` is called from router via HTTP path — Phase 2 rename will break the router until Phase 3 lands | Same as above. Single-PR merge required. |
| 5 | Some persistent state we haven't enumerated lives in the bridge (e.g., `displaced_sessions` list, future fields) | Pre-Phase 2: grep parent + `src/lupin_mcp/` + `src/cosa/` for `["conversation_mode_active"]` + `'conversation_mode_active'` + `.conversation_mode_active` to enumerate every read and write site. Document findings in `92-phase2-execution-log.md`. |

---

## 7. Cross-cutting concerns

### Memory check

- [[feedback_no_migration_code]] — discard old format, don't migrate. ✓
- [[feedback_no_defensive_programming]] — fail-closed on bridge errors (return `False`), no `or {}` defaults. ✓
- [[feedback_sweep_for_pattern_offenders]] — Step 5 of "Implementation order" includes the grep audit. ✓
- [[feedback_lupin_only_never_cosa]] — `session_bridge.py` is in `src/lupin_cli/`, parent Lupin. ✓

### Naming

- `speakerphone_on` (snake_case bridge field, matches existing `format_version`, `session_topic` convention). ✓
- `get_speakerphone(session_id)` / `set_speakerphone(session_id, on)` — boolean state, named to match. ✓
- `find_active_speakerphone_sessions()` — verb-led, matches `find_session_path_by_id` precedent. ✓

### Path management

- All paths via `cu.get_project_root()` + relative paths. `SESSION_DIR` resolution lives in `session_bridge.py` itself per the existing pattern. ✓

---

## 8. Implementation timing

Estimated active work: 90–120 minutes including comprehensive tests + grep audit.

---

## 9. Hand-off to Phase 3

Phase 3 (server router cleanup) will:
- Import the renamed `find_active_speakerphone_sessions` helper for solo-branch displacement scan.
- Call `set_speakerphone(sid, true|false)` instead of `set_conversation_mode`.
- Read `get_tts_interaction_mode()` to branch activate logic.

Phase 2 must leave the renamed helpers callable. Phase 3 owns the consumer logic.
