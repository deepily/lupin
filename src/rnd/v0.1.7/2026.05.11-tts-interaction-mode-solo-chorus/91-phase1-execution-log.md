# Phase 1 — INI Plumbing & Config Helper — Execution Log

**Date**: 2026.05.12 PM EDT
**Status**: ✅ **Implementation complete; all verification layers green**
**Owner**: [LUPIN]
**Session**: 83ba1e51 (Rio ⚡, resumption after Rick's walk)
**Companion docs**: [`00-index.md`](00-index.md), [`10-phase1-ini-plumbing-design.md`](10-phase1-ini-plumbing-design.md), [`90-decisions-log.md`](90-decisions-log.md)

---

## 1. Summary

Phase 1 of the TTS Interaction Mode (Solo / Chorus) refactor landed. Three production code surfaces:

- New INI key `tts interaction mode = chorus` under `[Lupin: Baseline]` in `src/conf/lupin-app.ini`
- Paired splainer entry in `src/conf/lupin-app-splainer.ini`
- New helper `get_tts_interaction_mode()` in `src/cosa/utils/util.py` — returns `"solo"` or `"chorus"`, fail-closes to `"chorus"` (the new operational default)

Plus 9 new unit tests (8 per the updated design doc + 1 contract-verification test), and a pre-existing test-env bug surfaced during the regression and fixed inline.

**No production behavior change.** The helper is added but no consumer wires into it yet — Phase 2+ scope.

---

## 2. Files changed

| File | Status | Purpose |
|---|---|---|
| `src/conf/lupin-app.ini` | MODIFIED (+11 lines) | Added `tts interaction mode = chorus` under `[Lupin: Baseline]`, alphabetically after `tts generation strategy = local` |
| `src/conf/lupin-app-splainer.ini` | MODIFIED (+1 line) | Added splainer entry adjacent to existing `tts generation strategy` entry |
| `src/cosa/utils/util.py` | MODIFIED (+30 lines) | Added `get_tts_interaction_mode()` helper after `get_project_root()` |
| `src/tests/unit/test_tts_interaction_mode_helper.py` | NEW (~150 lines) | 9 unit tests covering valid values + fail-closed paths + never-raises contract |
| `src/tests/unit/commons/test_commons_mcp_subprocess.py` | MODIFIED (1 line + comment) | **Pre-existing bug fix**: `_SRC = parents[2]` → `parents[3]` so spawned subprocess can find `lupin_mcp` |
| `src/tests/unit/commons/test_commons_mcp_config_toggle_subprocess.py` | MODIFIED (1 line + comment) | **Same pre-existing bug fix** — sister file with identical issue |
| `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/90-decisions-log.md` | MODIFIED (+45 lines) | Appended 2 entries: (a) default flipped `solo → chorus`; (b) execution-time API correction `.get_config_value()` → `.get()` |
| `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/00-index.md` | MODIFIED (line 65) | Status snapshot reflects new chorus default |
| `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/10-phase1-ini-plumbing-design.md` | MODIFIED (~25 lines across 7 hunks) | Helper code, INI value, splainer text, test table, commit message all updated to chorus default + `.get()` API |
| `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/2026.05.12-tts-interaction-mode-solo-chorus.md` | MODIFIED (2 hunks) | §The switch and §Phased landing updated to chorus default |
| `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/91-phase1-execution-log.md` | NEW (this file) | Per BFE execution-log pattern |

**Nested-repo note**: `src/cosa/utils/util.py` is in the CoSA submodule (per `feedback_lupin_only_never_cosa` + `feedback_cosa_edit_vs_manage_git`: editing is fine; git ops on CoSA are out of scope for this session).

---

## 3. Execution-time audit findings

The audit-at-execute-time pass (per `feedback_audit_plans_at_execute_time`) surfaced four divergences between the design doc and the actual codebase. All four were folded into the implementation and reflected in the updated design doc:

| # | Design doc said | Reality | Fix applied |
|---|---|---|---|
| 1 | `ConfigurationManager().get_config_value(...)` | Method is `.get(...)` at `src/cosa/config/configuration_manager.py:745` | Helper uses `.get( key, default="chorus", return_type="string" )` |
| 2 | Default = `solo` everywhere | Rick overrode at Phase 1 kickoff: chorus is the new default | All default + fail-closed paths return `chorus` |
| 3 | `ConfigurationManager()` with no args | Singleton `__init__` raises `ValueError` if first call has no `env_var_name` (docstring line 110) | Helper passes `env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS"` (no-op if already initialized) |
| 4 | Mock patch target ambiguous | Helper does inside-function `from cosa.config.configuration_manager import ConfigurationManager`; patch must target the source module path | Tests use `@patch( "cosa.config.configuration_manager.ConfigurationManager" )` |

Risk #1 in the Phase 1 design doc explicitly anticipated finding #1 ("ConfigurationManager API differs from assumption (e.g., no `default=` kwarg)") — the audit-at-execute-time mandate caught the divergence before any code was written. Risk #3 (circular import) was also anticipated and mitigated as designed (deferred-import inside the function body).

---

## 4. Pre-existing bug surfaced and fixed inline

The full-unit regression run surfaced 3 failures in `src/tests/unit/commons/test_commons_mcp_*_subprocess.py`:

```
FAILED src/tests/unit/commons/test_commons_mcp_config_toggle_subprocess.py::test_ac12_commons_disabled_omits_tools_and_skips_daemon
FAILED src/tests/unit/commons/test_commons_mcp_config_toggle_subprocess.py::test_ac12_commons_enabled_registers_tools_and_starts_daemon
FAILED src/tests/unit/commons/test_commons_mcp_subprocess.py::test_ac14_commons_tools_registered_in_subprocess
```

All three failed with:
```
ModuleNotFoundError: No module named 'lupin_mcp'
```

**Root cause**: both files compute `_SRC = Path( __file__ ).resolve().parents[ 2 ]`, but the test files live at `src/tests/unit/commons/test_*.py`, so `parents[2]` = `src/tests` (not `src/` as the comment claims). The spawned MCP subprocess gets `PYTHONPATH=src/tests`, so it can't find `lupin_mcp` (which lives at `src/lupin_mcp/`).

**Verification of pre-existence**: failures reproduce with `env -u PYTHONPATH pytest ...`; tests pass when invoked with `PYTHONPATH=src` set externally (the team's verification commands in `TODO.md:89-92` explicitly set `PYTHONPATH=src`, masking the bug).

**Fix**: `parents[2]` → `parents[3]` in both files, plus inline comment clarifying which level resolves to `src/`. Aligns with the existing comment on line 27 of `test_commons_mcp_subprocess.py` ("Add `src/` to sys.path so the helper module is importable as `tests.helpers...`").

**Why fixed inline**: per `feedback_fix_all_failing_tests`, never classify failures as "pre-existing" or "out of scope." 2-character change in 2 files, verifiable in seconds.

---

## 5. Verification matrix

| Layer | Check | Venue | Result |
|---|---|---|---|
| `py_compile` | `src/cosa/utils/util.py` | local | ✅ OK |
| Import chain | `from cosa.utils import util as cu; cu.get_tts_interaction_mode()` | :7999 (process-local, no server) | ✅ Returns `'chorus'` |
| Live INI smoke | Helper against actual INI with `LUPIN_CONFIG_MGR_CLI_ARGS` set | local | ✅ Returns `'chorus'` (matches the new INI value) |
| Unit (Phase 1) | 9 tests in `test_tts_interaction_mode_helper.py` | :7999 | ✅ 9/9 passed in 0.05s |
| Unit (commons fix) | 3 previously-failing tests after `parents` count fix | :7999 | ✅ 3/3 passed without external PYTHONPATH |
| Unit regression | Full `pytest src/tests/unit/` (env -u PYTHONPATH) | :7999 | ✅ 4210 passed / 0 failed / 1 xfailed / 69 warnings — see §6 |

**No `:8000` testing needed** for Phase 1 (no behavior change, no monopoly resource contention).

---

## 6. Unit regression summary

| Metric | First Phase-1 run (with PYTHONPATH bug) | Final (post-commons-fix) | Delta |
|---|---|---|---|
| Passed | 4207 (includes the 9 new helper tests) | 4210 | +3 (commons tests pass after parents-count fix) |
| Failed | 3 (pre-existing PYTHONPATH bug in commons subprocess tests) | 0 | -3 ✅ |
| xfailed | 1 | 1 | 0 |
| Warnings | 69 | 69 | 0 (none introduced by Phase 1) |
| Wall time | 137s | 144s | within run-to-run noise |

**Both runs invoked with `env -u PYTHONPATH ./src/cosa/.venv/bin/python -m pytest src/tests/unit/`** — i.e., neither relied on a PYTHONPATH set externally; the fix made the commons subprocess tests self-sufficient. The +9 new helper tests were already included in the 4207 baseline (the helper test file was created before the first regression run).

---

## 7. Memory-feedback compliance check

| Memory | Compliance |
|---|---|
| `feedback_no_defensive_programming` | ✅ Helper uses explicit value checks + explicit exception handling at the boundary; no `getattr` chains |
| `feedback_audit_plans_at_execute_time` | ✅ 4 execution-time divergences surfaced and folded into both implementation and updated design doc |
| `feedback_skip_rnd_doc_for_trivial_fixes` | ✅ Phase 1 is non-trivial enough to warrant the doc (multi-phase plan); the inline test fix is sub-trivial and stays under the same execution log entry |
| `feedback_no_migration_code` | ✅ No migration code; new key has a default; old configs simply pick up `chorus` from the default |
| `feedback_lupin_only_never_cosa` | ✅ Edited `src/cosa/utils/util.py` for code; no CoSA git ops |
| `feedback_cosa_edit_vs_manage_git` | ✅ Same — editing CoSA code is fine; only git ops are forbidden |
| `feedback_fix_all_failing_tests` | ✅ Pre-existing commons subprocess bug fixed in-session rather than deferred |
| `feedback_sweep_for_pattern_offenders` | ✅ Swept `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/` for all `default.*solo` mentions; 4 docs updated (00-index, 10-phase1, 2026.05.12, 90-decisions-log) — phase-2-spec doc per-session-state-defaults (mode-dependent, not the global default) intentionally untouched |
| `feedback_never_auto_commit_push` | ✅ No commit performed; awaiting Rick's explicit authorization |
| `feedback_acknowledge_receipt_before_tool_work` | n/a (conversation mode is OFF this session) |

---

## 8. Hand-off to Phase 2

Phase 2 (`11-phase2-bridge-rename-design.md`) is now unblocked. It will:

- Import `cu.get_tts_interaction_mode` for the per-session `speakerphone_on` default
- Read the mode flag once per session-start to compute the new-bridge default (solo: `false`, chorus: `true`)
- Rename `conversation_mode_active` bridge field → `speakerphone_on` across all surfaces
- Bump bridge file format version; old bridges discarded on read (no migration code)

Phase 1 only added the helper. Phase 2 owns the consumer logic.

---

## 9. Open items for Rick's review before Phase 2 kickoff

| # | Item | Recommendation |
|---|---|---|
| 1 | Default flipped `solo → chorus` per Phase 1 kickoff override — recorded in 90-decisions-log | Already confirmed by Rick; no further gate needed |
| 2 | Helper uses `.get()` not `.get_config_value()` — design doc updated | No further gate needed (Risk #1 mitigation as designed) |
| 3 | Commons subprocess PYTHONPATH bug fixed in-session (2 files, 2 lines + comments) | Acknowledge or revert — fix is independent of Phase 1 work but bundled in the same change set |
| 4 | No commit performed; all work uncommitted on disk | Awaiting Rick's explicit authorization per `feedback_never_auto_commit_push` |
| 5 | Authorization to proceed to Phase 2 | Awaiting explicit go-ahead — `feedback_approved_sequences_execute_end_to_end` does NOT apply here because the Phase 1 → 2 hop was not pre-declared as a single approved sequence |

---

## 10. Timing

| Phase | Time |
|---|---|
| Audit-at-execute-time (read design doc, config files, util.py, ConfigurationManager) | ~4 min |
| Design doc sweep + 3-doc-surface updates (90-log append, 00-index, 10-phase1, canonical plan) | ~6 min |
| INI key + splainer entry | ~2 min |
| Helper function implementation in util.py | ~2 min |
| py_compile + import-chain + live smoke | ~1 min |
| Unit test file (9 tests + helper) | ~5 min |
| Full unit regression + pre-existing bug diagnosis + fix + re-verify | ~6 min |
| This execution log | ~5 min |
| **Total active work** | **~31 min** |

Design doc estimated 30-45 min including tests. Actual: ~31 min. Within range.

---

## 11. Status

✅ **Phase 1 complete.** All verification layers green. Ready for Phase 2 on Rick's explicit go-ahead.

No commit performed. All changes uncommitted on disk.
