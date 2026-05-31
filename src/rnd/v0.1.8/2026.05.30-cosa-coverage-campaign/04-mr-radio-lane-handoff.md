# 04 — Mr. Radio 🦉 Lane Handoff (expediter/team family)

**Author**: Mr. Radio 🦉 (session 37e9d20e) · **Date**: 2026-05-31
**Manager**: Tiberius 👑 · **Reviewer**: Krishna 🦚
**Lane**: `cosa/agents/{bug_fix_expediter, test_fix_expediter, swe_team}`

Seeds the fresh author on TFE (Clayton) + whoever takes swe_team. Concise on purpose — read the BFE test files for the canonical patterns.

---

## TL;DR — lane status

| Package | LOC | Status |
|---|---|---|
| `bug_fix_expediter` | ~4023 | ✅ **COMPLETE — 14/14 modules @ 100%** (1335/0/382/0, 243 tests). Committed `51cf0c9`, Krishna-approved, 3 pragmas ratified, 0 prod bugs. |
| `test_fix_expediter` | ~5296 | 🟡 **Sub-batch 1a done by me** (voice_io, cosa_interface, config, __init__ → 100%, 15 tests, ON DISK at `src/cosa/tests/unit/agents/test_fix_expediter/test_facades_and_config.py`). Remainder open. |
| `swe_team` | ~5891 | ⬜ Not started. Scout when reached. |

**Clayton: start at the TFE prompts (sub-batch 1b), NOT the facades — 1a is already green on disk.** Verify with the runner one-liner below before building on it.

---

## 1. BFE patterns that worked (reuse verbatim)

1. **Boundary-mock everything; zero real anything.** No real LLM/SDK/network/subprocess/git/fs writes (zero spend — firewalled keys never touched). Mock at the seam:
   - SDK: patch `orchestrator.sdk_query` with an async-generator helper; build **real** `TextBlock(text=)` / `ToolUseBlock(id=,name=,input=)` / `AssistantMessage(content=,model=)`; use `MagicMock(spec=ResultMessage)` / `MagicMock(spec=RateLimitEvent)` for the heavy-ctor ones (the code only `getattr`s them, so spec-default is fine).
   - voice: `patch.object(bfe_voice_io, "notify", AsyncMock())` etc. (the modules import `from ...bug_fix_expediter import voice_io, cosa_interface` inside methods → patch the module attr).
   - persistence/factory/queue: inject fakes into `sys.modules` (e.g. `cosa.rest.job_persistence`, `fastapi_app.main`) to dodge heavy imports.
   - collaborators (`FixExecutor`, `GitStrategist`, `PlanWriter`, `WorktreeContext`, `EngineeringStrategy`): patch the orchestrator-module symbol; configure async methods as `AsyncMock`.
2. **Capture+assert printer output** (`contextlib.redirect_stdout` → assert substrings), don't assert "no exception". Test BOTH `debug=True` and `debug=False` arcs.
3. **Discriminating asserts** — assert WHICH branch produced WHICH substring / which return_type the config dispatch computed / identity of re-exports. No coloring.
4. **Big orchestrator → split the test file** into `test_orchestrator_helpers.py` (init/checkpoint/parsing/static/options/notify-state-cancel/worktree) + `test_orchestrator_phases.py` (the async SDK-delegation + voice-gate + fix/git phases). Kept each reviewable. Run them together for the final measure.
5. **Sub-batch reporting** (>3k-LOC package → 2–3 sub-batches): support → mid → job → orchestrator. DM Tiberius the **verbatim same-turn coverage table** per sub-batch (re-measure from disk; trust no remembered number).
6. **`Test*`-prefixed prod classes** (e.g. `TestFixExpediterConfig`) trip pytest test-class collection. Import via the **module** (`import ...config as cfg; _Config = cfg.TestFixExpediterConfig`) under a non-`Test` alias — do NOT `from ... import TestFixExpediterConfig` into the test namespace.

---

## 2. Tooling — `run-sdk-cov.sh` (MANDATORY for this lane)

These packages transitively import `claude_agent_sdk → mcp.types`, whose pydantic `RootModel[Union[...]]` creation hits **`KeyError: 'pydantic.root_model'` under the coverage tracer**. `unset COVERAGE_CORE` does NOT fix it (both ctrace + pytrace fail). Fix: pre-import `claude_agent_sdk` in the **parent process before `pytest.main()`** so pydantic's `_GENERIC_TYPES_CACHE` is warm before the tracer engages. Committed runner: `src/cosa/tests/run-sdk-cov.sh` (Tiberius `5178520`).

**Usage one-liner:**
```bash
src/cosa/tests/run-sdk-cov.sh <test-path> --cov=<dotted.module> --cov-report=term-missing -q
```
Always scope `--cov` to the module(s) under test; never full-suite (destabilizes :7999). Always `-p no:cacheprovider`. The lone residual `anyio` PytestAssertRewriteWarning is an expected SDK-preimport side effect, not a defect.

---

## 3. Pragma classes encountered (all confirmed-unreachable, same-line reason; Krishna ratifies)

- **async-with trailing-`if` false-arc** (`job.py:316` `# pragma: no branch`): an `if` that is the last statement inside `async with ...:`. When false, control exits via the CM cleanup (attributed to the `async with` line), so coverage's modeled `316->327` direct arc is unrepresentable. Confirmed with a 10-line minimal repro (`async with` + trailing `if` → identical `8->10` BrPart at 94% even with both outcomes exercised). Test BOTH outcomes; pragma the arc.
- **optional-dep import guard** (`orchestrator.py:66` `# pragma: no cover`): `except ImportError: SDK_AVAILABLE = False` — SDK is installed, never executes. (Tiberius pre-blessed import guards.)
- **dead defensive branch** (`orchestrator.py:755` `# pragma: no cover`): `if not isinstance(data, list)` after `_extract_last_json_array` which always yields a `[...]` string → `json.loads` → list. Unreachable.

Expect the SAME three classes in TFE/swe_team (they share the SDK import + the JSON-extract helpers + async-with phase blocks).

---

## 4. TFE scout map + recommended order

```
voice_io 59      __init__ 70      cosa_interface 89    config 247     ← 1a DONE (mine, 100%)
prompts/cluster 21   prompts/diagnosis 296   prompts/fix 352   prompts/proposal 249   ← 1b NEXT
snapshot_loader 349  state 377   cluster 562   resume_resolver 566    ← sub-batch 2 (mid)
job 648                                                                 ← sub-batch 3a
orchestrator 2329                                                       ← sub-batch 3b (split helpers+phases)
```

Notes for Clayton:
- **prompts** are pure string-builders depending on `state.TestRemediationContext` / `FailureCluster` / `TestDiagnosisResult` / `TFEProposedFix` (construct them as the modules' `quick_smoke_test()` blocks show). `prompts/fix.py` self-registers into `shared.fix_executor.FIX_PROMPT_BUILDERS` under key `"tfe"` at import (assert the registration like BFE's `"bfe"`). `prompts/cluster.py` is a stub (2 trivial symbols). Branch hotspots: `diagnosis.build_diagnosis_prompt` (hypothesis present/absent, affected_files, `_truncate_traceback` empty/≤30/>30, iteration>1 + previous_attempts, evidence present, pytest_args present); `proposal.build_proposal_prompt` (evidence/affected_components/test_symptoms/pytest_args present-absent) + `build_proposal_system_prompt(max_proposals)`.
- **state.py** has a `__getattr__`-free set of Pydantic models + `create_initial_state` + `BFE`-shared exception types (`VoiceGateTimeoutError`, `StalledException(checkpoint, phase, message="")`, `CheckpointData`) — BFE's `state.__getattr__` lazily re-imports these from here, so they're well-exercised already.
- **orchestrator (2329)** — Tiberius flagged: scout HARD. Fertile ground = the **voice-gate ratification** paths (`voice_gate_timeout_policy` ∈ {stall, top_1, top_n, none}) and **TFE→CC orchestration**. Tripwire any real bug (don't fix): arm `@unittest.expectedFailure` / xfail-strict asserting the CORRECT contract + a pin test for current behavior, DM `dm-tiberius` with `file:line` + evidence. Tiberius owns ALL prod fixes.

---

## 5. swe_team note (~5891 LOC, when reached)

Scout it fresh. It's the deepest SDK/subprocess surface (test_runner, hooks, safety_limits, proxy/engineering_strategy, agent_definitions, orchestrator). Same runner, same boundary-mock discipline. The `mcp-adjacent` caveat in the original assignment was a red herring — the real fix is the parent-pre-import runner (§2), not `unset COVERAGE_CORE`.

---

## 6. Hard rules (don't drift)

cosa venv ONLY (`src/cosa/.venv/bin/python`, py3.11/pytest9 — the lupin .venv py3.13/pytest8 SILENTLY MASKS failures). Test-only — NEVER edit prod logic (pragmas are annotations, not logic, and need Krishna ratify). NO git add/commit/push (held per Rick; Tiberius commits each Krishna-approved module). Style: spaces inside `( )` and `[ ]`, double quotes, vertical alignment. Honest stop > phantom data — checkpoint at a clean green line if degrading.

🦉 Standing down at a clean line. — Mr. Radio
