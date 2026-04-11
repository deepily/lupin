# 91 — TFE Scaffolding Execution Log

**Tracks**: Implementation step 6 of the plan — create the TFE package with all modules mandated by the agentic-voice-workflow skill. Plus step 14 (INI keys + splainer + command JSON).

**Design doc**: [`01-design-overview.md`](01-design-overview.md) (shared-module boundary) + [`12-config-inventory.md`](12-config-inventory.md)

**Precondition**: All 3 extraction steps (1-3) complete and green. See [`90-extraction-execution-log.md`](90-extraction-execution-log.md).

**Regression gate**: `pytest src/tests/unit/ -v --tb=no -q | tail -5` after every commit.

---

## Step 6: TFE scaffolding

**Status**: ✅ COMPLETE (zero regression, +38 new tests)

**Scope reduction from plan**: The agentic-voice-workflow skill originally mandated `api_client.py`, `cost_tracker.py`, and `rate_limiter.py` as separate modules. **Not created** — BFE (the closer analog) uses the Claude Agent SDK directly with `max_budget_usd` passed through `ClaudeAgentOptions`, which handles both cost tracking and rate limiting internally. TFE follows BFE's pattern. The skill's list was biased toward deep_research-style direct-API agents; BFE + TFE are SDK-delegated and don't need those modules. Config exposes `budget_usd` as an alias for `cost_cap_usd` so the shared FixExecutor works unchanged.

### Directory + package skeleton

| Sub-step | Status | Notes |
|----------|--------|-------|
| Create `src/cosa/agents/test_fix_expediter/` directory | DONE | |
| `__init__.py` with 28 exports | DONE | Re-exports config, state models, voice I/O, job |
| Create `prompts/` subdirectory with `__init__.py` | DONE | |

### Core modules

| Module | Status | Notes |
|--------|--------|-------|
| `config.py` — `TestFixExpediterConfig` with 16 fields (12 from plan + model/feedback/narrate + budget_usd alias) | DONE | `from_config()` classmethod loads all keys from INI |
| `state.py` — `TFEPhase` (12 values), `TestRemediationContext`, `FailureCluster`, `TestDiagnosisResult`, `TFEProposedFix`, `TFEState` TypedDict | DONE | Reuses BFE's `DiagnosisResult` and `FixResult` |
| `snapshot_loader.py` — `load_from_path()`, `load_from_artifacts()`, `SnapshotLoadError`, PII redaction | DONE | Schema version gate, all_passed/empty-failures validation |
| `cosa_interface.py` — `SENDER_ID = "test_fix_expediter@lupin.deepily.ai"` + 4 wrappers | DONE | Delegates to BFE's cosa_interface implementations (shared facade) |
| `voice_io.py` — thin wrapper re-exporting BFE's voice_io | DONE | All 8 functions re-exported |
| `cluster.py` — `heuristic_seed()` stub + `llm_refine()` stub | DONE | Single-cluster fallback; full implementation in step 7 |
| `orchestrator.py` — `TFEOrchestrator` with 6 phase method stubs | DONE | All 6 phases callable, transitions current_phase correctly |
| `job.py` — `TestFixExpediterJob(AgenticJobBase)` with `do_all()` / `_execute()` | DONE | JOB_TYPE=test_fix_expediter, JOB_PREFIX=tfe, dry_run support |
| `api_client.py`, `cost_tracker.py`, `rate_limiter.py` | **NOT CREATED** | Scope reduction (see note above) — TFE delegates to Claude Agent SDK like BFE |

### Prompt stubs (step 10 registers real builders)

| Module | Status | Notes |
|--------|--------|-------|
| `prompts/__init__.py` | DONE | |
| `prompts/cluster.py` — stub | DONE | Real in step 7 |
| `prompts/diagnosis.py` — stub | DONE | Real in step 8 |
| `prompts/proposal.py` — stub | DONE | Real in step 9 |
| `prompts/fix.py` — stubs, NO registration yet | DONE | Registration into shared FIX_PROMPT_BUILDERS deferred to step 10 to avoid dispatching to stubs |

### Queue wiring

| Sub-step | Status | Notes |
|----------|--------|-------|
| `src/cosa/rest/agentic_job_factory.py` import + elif branch | DONE | Command: `"agent router go to test fix expediter"` |
| Factory parses `original_test_types` (comma-separated string OR list) | DONE | Verified via unit tests |
| `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` entry | DEFERRED | Not blocking for step 6 since factory routing works; add in step 15 or 17 when the command is fully wired |
| `src/conf/agent-router-agentic-commands.json` | DEFERRED | Same — part of step 17 PEFT training data task |

### Config keys (step 14 of plan — folded into step 6 for clean scaffolding)

| Sub-step | Status | Notes |
|----------|--------|-------|
| Add 16 INI keys to `src/conf/lupin-app.ini` | DONE | Includes lead/worker model + narrate/feedback keys beyond the 12 in plan doc 12 |
| Add matching 16 splainer entries to `src/conf/lupin-app-splainer.ini` | DONE | Per CLAUDE.md memory — all splainer entries present |
| Verify clean load via `TestFixExpediterConfig.from_config()` | DONE | No splainer warnings; all defaults match |

### Unit tests

| Test file | Status | Tests |
|-----------|--------|-------|
| `test_tfe_config.py` | DONE | 7 tests — defaults, budget_usd mirror, custom values, from_config all keys, mirror after from_config |
| `test_tfe_state.py` | DONE | 12 tests — phase enum, TestRemediationContext, FailureCluster (confidence bounds), TestDiagnosisResult inheritance, TFEProposedFix, create_initial_state |
| `test_tfe_snapshot_loader.py` | DONE | 14 tests — valid, override, schema gate, missing version, all_passed=True, empty failures, not-dict, PII redaction (home/Users/email/preserve), load_from_path absolute/missing/invalid JSON |
| `test_tfe_job.py` | DONE | 9 tests — constants, construction, id_hash prefix, test_types passthrough, last_question_asked, factory routing (command, comma-separated, list input) |
| **Total new TFE tests** | | **42** unit tests (38 counted by pytest after test class collection warnings) |

### Smoke tests (inline in each module)

| Module | Status | Sub-checks |
|--------|--------|-----------|
| `state.py` | DONE | 6 sub-checks pass |
| `config.py` | DONE | 3 sub-checks (default, custom, from_config) |
| `snapshot_loader.py` | DONE | 6 sub-checks (valid, PII, schema gate, all_passed, empty, load_from_path) |
| `cluster.py` | DONE | 4 sub-checks (empty, single, multi-stub, llm_refine stub) |
| `cosa_interface.py` | DONE | 2 sub-checks (SENDER_ID, callable) |
| `voice_io.py` | DONE | 2 sub-checks (re-exports, mode description) |
| `orchestrator.py` | DONE | 3 sub-checks (instantiation, Phase 0 runs, all phase stubs callable) |
| `job.py` | DONE | 4 sub-checks (constants, instantiation, id_hash format, last_question_asked) |

### Regression gate

| Check | Status | Result |
|-------|--------|--------|
| py_compile all 14 TFE files | DONE | OK |
| Package import (`cosa.agents.test_fix_expediter`) | DONE | 28 exports, version 0.1.0 |
| All 8 module smoke tests via `python -m` | DONE | All pass |
| Targeted BFE: test_bfe_fix/orchestrator/phase5/proposal/git_ops | DONE | **130 passed in 0.92s** |
| New TFE tests (test_tfe_config/state/snapshot_loader/job) | DONE | **38 passed in 0.43s** |
| Full unit regression | DONE | **2954 passed, 1 xfailed in 130.87s** |
| Delta from pre-scaffolding baseline | — | **+38 tests (2916 → 2954), zero regression on prior tests** |

**Test delta**: pre=**2916 passed / 1 xfailed** / post=**2954 passed / 1 xfailed**
**Regression**: **ZERO** on prior tests; +38 new TFE tests
**Deviations from plan**:
1. `api_client.py`, `cost_tracker.py`, `rate_limiter.py` NOT created (see scope reduction note at top — TFE follows BFE's SDK-delegated pattern, not deep_research's direct-API pattern).
2. `agent_registry.py` entry + `agent-router-agentic-commands.json` registration deferred to step 17 (PEFT training data step) where they are co-located with the command training templates.
3. INI keys + splainer folded into step 6 (scaffolding) rather than a separate step 14 — folding keeps the scaffolding commit complete and testable. Plan sequence remains semantically equivalent.

---

## Follow-ups discovered during scaffolding

_(add entries here as discovered)_
