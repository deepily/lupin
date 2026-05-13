# Phase 1 — INI Plumbing & Config Helper

**Date**: 2026.05.12
**Status**: 📝 Design — not yet implemented
**Owner**: [LUPIN]
**Phase**: 1 of 8 (foundation; smallest)
**Prerequisites**: None (this is the foundation phase)
**Companion docs**: [`00-index.md`](00-index.md), [`01` (May 12 canonical plan)](2026.05.12-tts-interaction-mode-solo-chorus.md), [`02-background-synthesis.md`](02-background-synthesis.md)
**Execution log**: [`91-phase1-execution-log.md`](91-phase1-execution-log.md) (TBD — drafted at phase-end)

---

## 1. Goal

Land the global `tts interaction mode` INI key and the canonical helper function that all downstream phases will call to read it. Default to `chorus` per the 2026-05-12 execution-kickoff override (see [`90-decisions-log.md`](90-decisions-log.md)) — the experiment is the work; opt into solo via INI override for today's monopoly fallback. Phases 2–7 can then assume the key exists and the helper works.

This phase touches **no behavior**. It only adds config plumbing. Today's system continues to behave identically until Phase 2+ wires the new helper into actual decision points. The chorus-as-default switch only changes the runtime mode once Phase 2+ branches off the helper return value.

---

## 2. Scope

### In scope

- New INI key `tts interaction mode` under `[Lupin: Baseline]` in `src/conf/lupin-app.ini`.
- Paired splainer entry in `src/conf/lupin-app-splainer.ini`.
- New helper function `get_tts_interaction_mode()` in `src/cosa/utils/util.py`.
- Unit tests covering: default-when-absent, valid values (`solo`, `chorus`), invalid-value fallback.
- Inline `quick_smoke_test()` block in the helper's host module.

### Out of scope

- Any consumer code that uses the helper (Phases 2–7).
- Caching the value in-process (deferred; first-call cost is ~1ms, negligible).
- Per-test override mechanism (deferred; tests can monkey-patch `ConfigurationManager`).
- Validation that flips `mode=chorus` actually changes downstream behavior (Phase 2+ scope).

---

## 3. Deliverables

### 3.1 INI key

**File**: `src/conf/lupin-app.ini`
**Section**: `[Lupin: Baseline]`
**Insertion point**: alphabetically after `tts generation strategy = local` (line 559 area) — the only existing `tts ` key in `[Lupin: Baseline]`. Alphabetic order: `generation` < `interaction`.

```ini
tts interaction mode = chorus
```

Values: `solo` | `chorus`. Default (initial deployment): `chorus` — per 2026-05-12 execution-kickoff override. Set to `solo` in the INI to invoke today's monopoly-mode fallback.

### 3.2 Splainer entry

**File**: `src/conf/lupin-app-splainer.ini`
**Same section + same key name** (splainer is flat — no section headers; insert near the existing `tts generation strategy` entry at line 40):

```ini
tts interaction mode = Selects between two permanent TTS interaction models for the cosa-voice MCP server. "chorus" (default) enables N sessions to be in speakerphone mode simultaneously; persona voices disambiguate at the listener's ear; no displacement, no asyncio.Lock. "solo" invokes today's monopoly behavior: one session at a time speaks via TTS, with asyncio.Lock + displacement when another session activates speakerphone, plus a green mic-monopoly pin in the multiplexer UI. Both modes are first-class and permanently maintained per the feature-flag preservation rule. Default: chorus (set to solo to revert to monopoly behavior). Room for future values like duet/trio/quartet if pair- or small-group-routing semantics become useful.
```

### 3.3 Helper function

**File**: `src/cosa/utils/util.py`
**Location**: near `get_project_root()` (existing canonical helper pattern) — i.e., insert right after `get_project_root()` ends around line 654.

```python
def get_tts_interaction_mode() -> str:
    """
    Get the global TTS interaction mode from configuration.

    Requires:
        - ConfigurationManager is importable
        - "tts interaction mode" key may or may not be set in lupin-app.ini

    Ensures:
        - returns "solo" or "chorus" (string)
        - returns "chorus" if key is absent (the new operational default per 2026-05-12 override)
        - returns "chorus" if key is present but has an invalid value (fail-closed to default)
        - never raises (config errors fall back to "chorus")

    Raises:
        - never
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        mode       = config_mgr.get( "tts interaction mode", default="chorus", return_type="string" )
    except Exception:
        return "chorus"
    if mode not in ( "solo", "chorus" ):
        return "chorus"
    return mode
```

**Naming rationale**: matches the snake_case convention. Bare function (not a class method) because there's no state to hold. Module-level — call sites use `from cosa.utils import util as cu; cu.get_tts_interaction_mode()` per the [[cu.get_project_root]] convention.

**Fail-closed rationale**: any config error or unrecognized value returns `"chorus"` (the new operational default). The reasoning: if config is broken or has a typo, the operator's expected state is the default; silently falling back to `"solo"` (the old default) would surprise operators who explicitly set `= chorus` but mistyped.

**Singleton instantiation**: passes `env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS"` to satisfy the singleton's first-call init contract per the CoSA CLAUDE.md memory ("The configuration manager always needs an environment variable when it's instantiated"). On subsequent calls (singleton already initialized), the kwarg is ignored by the singleton wrapper.

**Method name**: uses `.get()` (the actual ConfigurationManager API at `src/cosa/config/configuration_manager.py:745`), not the design-doc-time-speculated `.get_config_value()`. See [`90-decisions-log.md`](90-decisions-log.md) → "Execution-time correction" entry.

### 3.4 Unit tests

**File**: `src/tests/unit/test_tts_interaction_mode_helper.py` (new)

| Test | Setup | Assertion |
|---|---|---|
| `test_returns_chorus_when_key_absent` | Mock `.get()` to return its `default=` kwarg (i.e., `"chorus"`) | Returns `"chorus"` |
| `test_returns_solo_explicit` | Mock `.get()` to return `"solo"` | Returns `"solo"` |
| `test_returns_chorus_explicit` | Mock `.get()` to return `"chorus"` | Returns `"chorus"` |
| `test_returns_chorus_on_invalid_value` | Mock `.get()` to return `"monopoly"` | Returns `"chorus"` (fail-closed to default) |
| `test_returns_chorus_on_config_exception` | Mock ConfigurationManager constructor to raise | Returns `"chorus"` (never raises) |
| `test_returns_chorus_on_none_value` | Mock `.get()` to return `None` | Returns `"chorus"` (None is not in valid set) |
| `test_case_sensitivity_solo` | Mock `.get()` to return `"SOLO"` | Returns `"chorus"` (fail-closed; INI values are case-sensitive by convention) |
| `test_case_sensitivity_chorus` | Mock `.get()` to return `"Chorus"` | Returns `"chorus"` (fail-closed; case-sensitive) |

Use `unittest.mock.patch` on `cosa.config.configuration_manager.ConfigurationManager` (the patched name where the helper imports from) for isolation. No real INI file reads in unit tests.

### 3.5 Smoke test

**Inline** in `src/cosa/utils/util.py` `quick_smoke_test()` block (if one exists; otherwise add):

```python
if __name__ == "__main__":
    print( f"tts interaction mode: { get_tts_interaction_mode() }" )
```

Verifies the helper runs against the real INI file without raising.

---

## 4. Implementation order

1. Add the INI key (lupin-app.ini).
2. Add the splainer entry (lupin-app-splainer.ini).
3. Verify `ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get( "tts interaction mode" )` returns `"chorus"` via a one-line python -c smoke test against the actual INI (requires `LUPIN_CONFIG_MGR_CLI_ARGS` env var set; otherwise helper falls back to default `"chorus"`).
4. Add `get_tts_interaction_mode()` to `src/cosa/utils/util.py`.
5. Run `python -m py_compile src/cosa/utils/util.py` — must pass.
6. Run `python -c "import cosa.utils.util as cu; print(cu.get_tts_interaction_mode())"` — must print `"chorus"`.
7. Write unit tests; run `pytest src/tests/unit/test_tts_interaction_mode_helper.py -v` — all pass.
8. Run full unit test suite as regression check: `pytest src/tests/unit/ -v` — no regressions.

---

## 5. Verification matrix

| Layer | Check | Venue | Pass criteria |
|---|---|---|---|
| `py_compile` | `src/cosa/utils/util.py` | local | Compiles |
| Import chain | `from cosa.utils import util as cu; cu.get_tts_interaction_mode()` | local | No error; returns "chorus" |
| Unit | All 8 tests in `test_tts_interaction_mode_helper.py` | :7999 | 8/8 pass |
| Unit regression | Full `pytest src/tests/unit/` | :7999 | No new failures vs baseline |
| Manual INI flip | Edit INI to `tts interaction mode = solo`, run smoke command, edit back to `chorus` | local | Helper returns `"solo"` while INI says solo; returns `"chorus"` after revert |
| Manual invalid value | Edit INI to `tts interaction mode = banana`, run smoke command, revert | local | Helper returns `"chorus"` (fail-closed to default) |

No `:8000` testing needed for Phase 1 (no behavior change, no monopoly resource contention).

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | ConfigurationManager API differs from assumption (e.g., no `default=` kwarg) | Read `cosa/config/configuration_manager.py` first to confirm API; adapt if needed. Documented pattern in CLAUDE.md is `get_config_value( key )` — check whether `default=` exists or whether KeyError handling is needed. |
| 2 | Splainer file format differs (e.g., uses different delimiter) | Read existing splainer entries first to match format. |
| 3 | Helper placement causes circular import (util.py importing ConfigurationManager which may import util) | Defer `ConfigurationManager` import to inside the function body (already done in the draft above) to break cycles. |
| 4 | Tests assume monkey-patch path that doesn't exist | Read `ConfigurationManager` to find the correct mock target. Likely `cosa.config.configuration_manager.ConfigurationManager.get_config_value`. |

---

## 7. Cross-cutting concerns

### Memory check

- [[feedback_no_defensive_programming]] — helper does NOT use defensive `or ""` or `getattr` chains; it uses explicit value checks and explicit exception handling at the boundary. ✓
- [[feedback_audit_plans_at_execute_time]] — re-audit this design at execute time against memory. ✓ (this section is the audit)
- [[feedback_skip_rnd_doc_for_trivial_fixes]] — this phase IS trivial (~10 lines of code + tests), but it's part of a multi-phase plan, so the design doc is warranted as a phase-by-phase tracking artifact. ✓
- [[feedback_no_migration_code]] — no migration code; the new key has a default value, old configs simply pick up the default. ✓
- [[feedback_lupin_only_never_cosa]] — `src/cosa/utils/util.py` is in the CoSA submodule. Edit is fine; git ops on CoSA are NOT in scope. ✓
- [[feedback_cosa_edit_vs_manage_git]] — confirms above. ✓

### Path management

- Uses `from cosa.utils import util as cu` per the canonical convention. ✓
- Helper does not manipulate paths; just reads config. ✓

### Naming

- Function name: `get_tts_interaction_mode()` — snake_case, descriptive, matches `get_project_root()` precedent. ✓
- INI key: `tts interaction mode` — space-separated lowercase, matches existing convention (e.g., `app_debug`, `websocket available events`). ✓

---

## 8. Implementation timing

Estimated active work: 30–45 minutes including tests.

Suggested commit message format (when user authorizes):

```
[LUPIN] Phase 1: TTS interaction mode INI key + config helper

Add 'tts interaction mode = chorus' under [Lupin: Baseline] with splainer entry. New helper get_tts_interaction_mode() in cosa.utils.util returns "solo" or "chorus", defaults to "chorus" fail-closed on absent/invalid values per 2026-05-12 execution-kickoff override. 8 new unit tests; no behavior change (consumers wired in Phase 2+).
```

---

## 9. Hand-off to Phase 2

Phase 2 (bridge field rename + mode-aware defaults) will:
- Import `get_tts_interaction_mode` to set the per-session speakerphone default.
- Read the mode flag once per session-start when computing the default for `speakerphone_on`.

Phase 1 only needs to make the helper callable. Phase 2 owns the consumer logic.
