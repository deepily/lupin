# 90 — Extraction Execution Log

**Tracks**: Implementation steps 1-3 of the approved plan — extraction of PlanWriter, GitStrategist, and FixExecutor from BFE into `src/cosa/agents/shared/`.

**Design doc**: [`02-fix-executor-extraction-plan.md`](02-fix-executor-extraction-plan.md)

**Regression gate**: `pytest src/tests/unit/ -v --tb=no -q | tail -5` after every commit. Totals must not regress.

**Baseline unit test count** (pre-extraction): **2916 passed, 1 xfailed** (131 seconds). Session 1cfcdf73 2026-04-10T16:32.

---

## Step 1: Extract `PlanWriter`

**Status**: ✅ COMPLETE (zero regression)

| Sub-step | Status | Notes |
|----------|--------|-------|
| Capture pre-extraction unit test baseline | DONE | 2916 passed, 1 xfailed |
| Grep for external imports | DONE | 3 test files import (test_bfe_phase5/fix/proposal); 2 internal (orchestrator, __init__) |
| Create `src/cosa/agents/shared/` directory + `__init__.py` | DONE | PlanWriter re-exported; __version__ = 0.1.0 |
| Write `src/cosa/agents/shared/plan_writer.py` | DONE | Verbatim copy + standalone smoke test using SimpleNamespace mocks (no BFE back-dep) |
| Replace `src/cosa/agents/bug_fix_expediter/plan_writer.py` with re-export shim | DONE | 20-line shim, preserves import identity + smoke test |
| Compile verification (py_compile on all 3 files) | DONE | OK |
| Import identity check (all 3 paths → same class) | DONE | `P1 is P2 is P3` holds |
| `test_bfe_phase5.py`, `test_bfe_fix.py`, `test_bfe_proposal.py` | DONE | 77 passed in 1.02s |
| `python -m cosa.agents.shared.plan_writer` smoke test | DONE | All 4 sub-checks pass (slug, write_plan, update_implementation_log, update_git_references) |
| `python -m cosa.agents.bug_fix_expediter.plan_writer` smoke test via shim | DONE | All 4 sub-checks pass |
| Run full unit regression | DONE | 2916 passed, 1 xfailed in 132.70s |
| Verify no regression | DONE | Delta = 0 (identical to baseline) |

**Test delta**: pre=**2916 passed / 1 xfailed** (131.33s) / post=**2916 passed / 1 xfailed** (132.70s)
**Regression**: **ZERO** — byte-for-byte identical counts
**Deviations from plan**: Rewrote smoke test to use `types.SimpleNamespace` mocks instead of BFE-specific `DeadJobContext`/`DiagnosisResult`/`ProposedFix` types — avoids a back-dependency from `shared/` to `bug_fix_expediter/` which would have been a layering violation. BFE-specific test coverage remains in `test_bfe_phase5/fix/proposal.py` which still exercise PlanWriter with real BFE types via the import shim.

---

## Step 2: Extract `GitStrategist`

**Status**: ✅ COMPLETE (zero regression)

| Sub-step | Status | Notes |
|----------|--------|-------|
| Capture pre-step test baseline | DONE | 2916 passed, 1 xfailed (inherited from step 1 post-state) |
| Create `src/cosa/agents/shared/git_strategist.py` | DONE | GitStrategist class with resolve_trust_level (static), generate_slug (static), commit_and_pr_single (async), commit_and_pr_multi (stub) |
| Extract commit_and_pr_single body from BFE `run_git_strategy` | DONE | ~80 lines of commit/branch/PR logic moved; caller provides GitOps + notify_fn |
| Leave `commit_and_pr_multi` as stub (NotImplementedError) | DONE | Implemented in TFE step 11 |
| Update `shared/__init__.py` to export GitStrategist | DONE | |
| BFE `orchestrator.run_git_strategy()` → shim calling `commit_and_pr_single()` | DONE | ~50-line shim that builds commit_message/pr_title/pr_body and delegates |
| Keep `BFEOrchestrator._resolve_trust_level()` as instance shim (test compat) | DONE | delegates to `GitStrategist.resolve_trust_level(self.proxy)` |
| Keep `BFEOrchestrator._generate_slug()` as static shim (test compat) | DONE | delegates to `GitStrategist.generate_slug(text)` |
| Keep `_finalize_git_strategy` unchanged (BFE-specific, uses dead_job_context.user_email) | DONE | |
| Compile verification (py_compile) | DONE | shared/__init__.py, shared/git_strategist.py, bug_fix_expediter/orchestrator.py all OK |
| Import identity + class hook check | DONE | BFEOrchestrator still has `_resolve_trust_level` + `_generate_slug` attrs |
| Run targeted: `test_bfe_phase5.py`, `test_bfe_git_ops.py`, `test_bfe_fix.py`, `test_bfe_proposal.py` | DONE | 93 passed in 0.90s |
| `python -m cosa.agents.shared.git_strategist` smoke test | DONE | All 4 sub-checks pass (trust resolution, slug gen, constructor, stub raises) |
| Run full unit regression | DONE | 2916 passed, 1 xfailed in 131.47s |
| Verify no regression | DONE | Delta = 0 |

**Test delta**: pre=**2916 passed / 1 xfailed** / post=**2916 passed / 1 xfailed**
**Regression**: **ZERO**
**Deviations from plan**: None. Plan doc 02 suggested moving `_finalize_git_strategy` to shared; left it in BFE because it references `self.dead_job_context.user_email` (BFE-specific). TFE will have its own equivalent that reads user_email from `TestRemediationContext`. This is a minor scope reduction — cleaner than contorting shared/ to carry both contexts.

---

## Step 3: Extract `FixExecutor` (RISKIEST)

**Status**: ✅ COMPLETE (zero regression, 1 iteration)

| Sub-step | Status | Notes |
|----------|--------|-------|
| Create `src/cosa/agents/shared/fix_executor.py` | DONE | ~400 lines including smoke test |
| Define `FIX_PROMPT_BUILDERS` registry dict + `register_fix_prompts()` helper | DONE | Registry keyed by agent string ("bfe", "tfe") |
| Extract main Coder+Tester retry loop into `FixExecutor.execute_fix()` | DONE | ~200 lines of retry/redelegate/escalate logic moved |
| Register BFE prompt bundle in `prompts/fix.py` at import time | DONE | Self-registers under key `"bfe"` when module imports |
| Update `shared/__init__.py` exports | DONE | FixExecutor, FIX_PROMPT_BUILDERS, register_fix_prompts |
| BFE `orchestrator.run_fix()` → shim | DONE | ~30-line shim: SDK_AVAILABLE check → state transition → notify → construct FixExecutor → delegate → plan doc update → completion notify |
| Keep BFE `_delegate_to_coder`, `_verify_fix`, `_build_coder_options`, `_build_tester_options` UNCHANGED | DONE | Required for unit-test patch compatibility |
| Iteration 1 failure: `test_sdk_unavailable` + `test_run_fix_sdk_unavailable_graceful` | FAILED | My initial shim removed the `if not SDK_AVAILABLE: return` early check — tests that `patch("orchestrator.SDK_AVAILABLE", False)` saw no effect |
| Iteration 1 fix: Restored SDK_AVAILABLE check at top of shim | DONE | 1-line addition; both tests green on retry |
| Compile verification | DONE | All 4 touched files OK |
| Import-time registration check | DONE | `FIX_PROMPT_BUILDERS` has `'bfe'` key after BFE prompts import |
| BFE instance methods still present (`_delegate_to_coder`, `_verify_fix`, `_build_coder_options`, `_build_tester_options`) | DONE | hasattr check passes |
| Targeted: test_bfe_fix, test_bfe_orchestrator, test_bfe_phase5, test_bfe_proposal, test_bfe_git_ops | DONE | **130 passed in 0.93s** |
| `python -m cosa.agents.shared.fix_executor` smoke test | DONE | 4 sub-checks pass (registry, registration, unknown-key KeyError, valid construction) |
| Run full unit regression | DONE | 2916 passed, 1 xfailed in 131.30s |
| Verify no regression | DONE | Delta = 0 |

**Test delta**: pre=**2916 passed / 1 xfailed** / post=**2916 passed / 1 xfailed**
**Regression**: **ZERO**

**Deviations from plan**:
1. **FixContext model deferred to TFE**. Plan doc 02 specified building `FixContext` Pydantic model with `from_dead_job()` / `from_test_cluster()` classmethods. Because BFE unit tests extensively patch `orchestrator._delegate_to_coder` and `orchestrator._verify_fix` and require those to be called by `run_fix`, the cleanest extraction kept those methods on BFE orchestrator and made FixExecutor accept them as callbacks. `fix_context` in `FixExecutor.__init__` is now a duck-typed pass-through — BFE passes `self.dead_job_context`, TFE will pass a `FailureCluster`-derived context. Adding `FixContext` Pydantic model and `from_test_cluster()` is deferred to TFE step 10 where it's actually needed. **This is a scope reduction, not a feature loss** — same end behavior, less upfront abstraction.
2. **`_delegate_to_coder`, `_verify_fix`, `_build_coder_options`, `_build_tester_options` stay in BFE orchestrator**. Plan 02 called for extracting these to the shared FixExecutor. Test patch surface made that impossible without rewriting ~15 tests. The callback pattern (BFE passes its own methods in) preserves all tests and still delivers the main reusable piece (the retry/redelegate/escalate main loop). TFE will provide equivalent methods on its own orchestrator when implemented in step 10.
3. **1 iteration instead of expected 2-3**. Plan predicted 2-3 iterations due to SafetyGuard/cancellation fragility. Actual: 1 failed iteration (SDK_AVAILABLE early-exit) + 1 green iteration. Faster than expected because the callback pattern avoided the hardest rewriting.

---

## Extraction phase summary

All three extraction steps complete with **zero regression** across 2916 unit tests. The shared package is:

```
src/cosa/agents/shared/
├── __init__.py           (re-exports PlanWriter, GitStrategist, FixExecutor, FIX_PROMPT_BUILDERS, register_fix_prompts)
├── plan_writer.py        (moved verbatim; standalone smoke test with SimpleNamespace mocks)
├── git_strategist.py     (new; resolve_trust_level, generate_slug, commit_and_pr_single, commit_and_pr_multi stub)
└── fix_executor.py       (new; FIX_PROMPT_BUILDERS registry + FixExecutor retry loop, accepts delegate/verify callbacks)
```

BFE reductions:
- `bug_fix_expediter/plan_writer.py` — 410 lines → 20-line re-export shim
- `bug_fix_expediter/orchestrator.run_git_strategy` — 100 lines → 50-line shim
- `bug_fix_expediter/orchestrator.run_fix` — 180 lines → 30-line shim

BFE preservation (unchanged — tests depend on these):
- `bug_fix_expediter/orchestrator._delegate_to_coder`
- `bug_fix_expediter/orchestrator._verify_fix`
- `bug_fix_expediter/orchestrator._build_coder_options`
- `bug_fix_expediter/orchestrator._build_tester_options`
- `bug_fix_expediter/orchestrator._resolve_trust_level` (now delegates to GitStrategist)
- `bug_fix_expediter/orchestrator._generate_slug` (now delegates to GitStrategist)
- `bug_fix_expediter/orchestrator._finalize_git_strategy` (BFE-specific, uses dead_job_context)

Next: TFE scaffolding (task #9 — step 6 in the approved plan).

---

## Extraction rollback protocol

If any step breaks BFE tests that cannot be resolved within 30 minutes:

1. `git revert` the step's commit
2. Notify user via cosa-voice urgent
3. Stop — do NOT proceed to the next extraction step
4. File investigation note below under "Deviations"
5. Re-plan with user before retrying

---

## Deviations from plan

_(add entries here as they occur)_

---

## Open follow-ups

_(add entries here as discovered)_
