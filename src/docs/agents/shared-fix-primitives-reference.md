# Shared Fix Primitives Reference

> **Audience**: Developers adding a new expediter agent OR debugging behavior shared between BFE and TFE
>
> **Scope**: `src/cosa/agents/shared/` — `PlanWriter`, `GitStrategist`, `FixExecutor`, `FIX_PROMPT_BUILDERS` registry
>
> **Last Updated**: 2026-04-10
>
> **See Also**:
> - [Bug Fix Expediter Guide](bug-fix-expediter-guide.md)
> - [Test Fix Expediter Guide](test-fix-expediter-guide.md)
> - R&D: [`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/02-fix-executor-extraction-plan.md`](../../rnd/v0.1.6/2026.04.10-test-fix-expediter/02-fix-executor-extraction-plan.md)

---

## Table of Contents

1. [Why the Shared Package Exists](#1-why-the-shared-package-exists)
2. [Package Layout](#2-package-layout)
3. [`PlanWriter` — Markdown Plan Docs](#3-planwriter--markdown-plan-docs)
4. [`GitStrategist` — Trust-Aware Git Operations](#4-gitstrategist--trust-aware-git-operations)
5. [`FixExecutor` — Polymorphic Coder+Tester Loop](#5-fixexecutor--polymorphic-codertester-loop)
6. [`FIX_PROMPT_BUILDERS` Registry](#6-fix_prompt_builders-registry)
7. [How to Add a New Expediter Agent](#7-how-to-add-a-new-expediter-agent)
8. [Test Coverage](#8-test-coverage)

---

## 1. Why the Shared Package Exists

The Bug Fix Expediter (BFE) and Test Fix Expediter (TFE) both apply code changes
through a **Coder → Tester → Retry** loop using the Claude Agent SDK. Both write
structured Markdown plan documents. Both commit changes via a trust-level-aware
git strategy. These concerns are **agent-agnostic** — the only parts that differ
between BFE and TFE are:

- **Input shape**: BFE consumes a `DeadJobContext` (one crashed job → one root cause),
  TFE consumes a `TestRemediationContext` (N failures → K root causes).
- **Prompts**: BFE's prompts reason about stack traces, TFE's reason about pytest
  `classname::name[param]` semantics.
- **Output**: BFE retries the original dead job, TFE reruns the affected test suites.

During Session 1cfcdf73 (2026-04-10) the reusable pieces were extracted into
`src/cosa/agents/shared/` as a PEER of the agent packages — **not** a subordinate
of either. Agent packages import from `shared/`; `shared/` does not import from any
specific agent package. This keeps BFE's proven dead-job code path untouched while
giving TFE a fully-tested foundation.

**Key invariant**: adding a third expediter agent (e.g., a future `IntegrationFixExpediter`)
should require zero changes to `shared/` — only new prompt modules that self-register
into the `FIX_PROMPT_BUILDERS` registry.

---

## 2. Package Layout

```
src/cosa/agents/shared/
├── __init__.py               # Re-exports the public API
├── plan_writer.py            # PlanWriter class (moved from BFE)
├── git_strategist.py         # GitStrategist class (new, extracted from BFE orchestrator)
└── fix_executor.py           # FixExecutor + FIX_PROMPT_BUILDERS registry (new)
```

**Public exports** (from `cosa.agents.shared`):

| Symbol | Type | Purpose |
|--------|------|---------|
| `PlanWriter` | class | Markdown plan doc writer |
| `GitStrategist` | class | Trust-level → git strategy dispatcher |
| `FixExecutor` | class | Coder+Tester retry loop engine |
| `FIX_PROMPT_BUILDERS` | dict | Polymorphic prompt registry keyed by agent string |
| `register_fix_prompts()` | function | Helper for agent packages to self-register |

---

## 3. `PlanWriter` — Markdown Plan Docs

`PlanWriter` writes structured Markdown plan documents that capture a diagnosis,
proposed fixes, implementation log, and git references. One plan doc per fix attempt.
Documents land under `io/swe-team/plans/{user_email}/YYYY.MM.DD-{slug}-plan.md`.

**Source**: `src/cosa/agents/shared/plan_writer.py`

### Constructor

```python
writer = PlanWriter( user_email="alice@example.com", debug=False )
```

- `user_email`: partitions plan docs by user. Required for multi-tenant deployments.
- `debug`: enables `[PlanWriter]` diagnostic prints.

### Methods

| Method | Purpose | When called |
|--------|---------|-------------|
| `write_plan(dead_job_context, diagnosis, proposed_fixes, selected_fix=None)` | Write initial plan doc with diagnosis + proposal sections. Returns absolute path. | After Phase 2 (Propose) completes |
| `update_implementation_log(plan_path, fix_result, files_changed, coder_output)` | Replace the `(Phase 4 — populated after fix is applied)` placeholder with real results | After Phase 3 (Fix) completes |
| `update_git_references(plan_path, fix_result)` | Replace the `(Phase 5 — populated after git operations)` placeholder with branch/commit/PR metadata | After Phase 5 (Git) completes |

### Plan doc structure

```markdown
# Bug Fix Plan: {slug}

**Dead Job**: {id_hash} ({job_type})
**Diagnosed**: {timestamp}
**Root Cause**: {root_cause}
**Category**: {error_category}
**Confidence**: {confidence:.0%}

---

## Diagnosis
**Error**: ...
**Stack Trace**: ...
**Evidence**: ...
**Affected Components**: ...

## Proposed Fixes
### Fix 1: {title} [SELECTED]
- **Type**: {fix_type}
- **Confidence**: ...
- **Risk**: ...
- **Effort**: ...
{description}

**Changes**:
| File | Action | Description |

## Implementation Log
(Phase 4 — populated after fix is applied)

## Git References
(Phase 5 — populated after git operations)
```

### Duck typing

`PlanWriter` is duck-typed on its inputs: it reads `.id_hash`, `.job_type`, `.error`,
`.stack_trace` from `dead_job_context`, and `.root_cause`, `.error_category`,
`.confidence`, `.evidence`, `.affected_components` from `diagnosis`. Any object with
those attributes works — BFE passes a `DeadJobContext`, TFE passes a synthesized
`SimpleNamespace` built from the aggregated `TestRemediationContext`.

---

## 4. `GitStrategist` — Trust-Aware Git Operations

`GitStrategist` encapsulates the trust-level → git-strategy mapping and executes the
actual commit / branch / push / PR operations via an injected `GitOps` instance
(from `src/cosa/agents/bug_fix_expediter/git_ops.py`). It has **two entry points**:

- `commit_and_pr_single()` — BFE path (one fix → one commit OR one branch+PR)
- `commit_and_pr_multi()` — TFE path (K cluster fixes → one branch, N commits, one PR)

**Source**: `src/cosa/agents/shared/git_strategist.py`

### Trust-to-git mapping

Same table for both entry points:

| Trust Level | Mode | Git Strategy | Notes |
|-------------|------|--------------|-------|
| **L1 Shadow** | passive | `commit_only` on current branch | Baseline, no auto-branching |
| **L2 Suggest** | passive | `commit_only` on current branch | Reviewing mode |
| **L3+ Active** | active | `branch_and_pr` via `gh` CLI | Full auto: branch, push, PR |
| `gh` missing | — | Degrade L3+ → `branch_only` | Branch + push succeed; PR step skipped |
| Proxy unavailable | — | `commit_only` | Conservative fallback |

### Static helpers

```python
# Both are callable without constructing a GitStrategist instance.

trust_level = GitStrategist.resolve_trust_level( proxy )   # Returns int 1-5
#  - None proxy → L1
#  - proxy.trust_tracker.get_level("engineering") → int
#  - Any exception → L1

slug = GitStrategist.generate_slug( "Fix null pointer in auth module" )
# Returns "fix/2026-04-10-fix-null-pointer"
#  - Strips non-alphanumeric, joins first 3 words, prefixes with fix/YYYY-MM-DD-
```

### `commit_and_pr_single()` (BFE path)

Used when one fix produces one commit. If trust is L1-L2, commits on the current
branch; if L3+, creates a new `fix/...` branch, pushes, and opens a PR via `gh`.

```python
strategist = GitStrategist( debug=False, verbose=False )
trust_level = GitStrategist.resolve_trust_level( bfe.proxy )

result = await strategist.commit_and_pr_single(
    git_ops        = git_ops_instance,
    files_changed  = [ "src/cosa/auth/tokens.py" ],
    commit_message = "[BFE] Fix: return new token instead of None",
    pr_title       = "[BFE] Fix null token refresh",
    pr_body        = "Automated fix from Bug Fix Expediter...",
    trust_level    = trust_level,
    notify_fn      = async_notify_fn,
)
# result = {
#     "git_strategy": "commit_only" | "branch_and_pr" | "branch_only" | None,
#     "commit_hash": "abc12345" | None,
#     "branch_name": "fix/2026-04-10-..." | None,
#     "pr_url": "https://github.com/..." | None,
#     "error": None | "error message",
# }
```

### `commit_and_pr_multi()` (TFE path)

Used when K cluster fixes produce N commits on a single branch, followed by one PR
covering all of them. Each cluster becomes one commit with its own message; the
branch and PR represent the batch.

```python
result = await strategist.commit_and_pr_multi(
    git_ops          = git_ops_instance,
    clusters         = [
        ( "C1", "Fix visual regression",    [ "io/baselines/login.png" ],     "fix(tfe): C1 ..." ),
        ( "C2", "Fix auth token race",      [ "src/cosa/auth/tokens.py" ],    "fix(tfe): C2 ..." ),
        ( "C3", "Fix queue counter",        [ "src/cosa/rest/queue.py" ],     "fix(tfe): C3 ..." ),
    ],
    trust_level      = 1,
    notify_fn        = async_notify_fn,
    pr_title         = "TFE fix: 3 clusters from unit test run",
    pr_body          = "## Summary...",
    branch_slug_hint = "tfe-unit-3-clusters",
)
# result = {
#     "git_strategy": "commit_only" | "branch_and_pr" | "branch_only" | None,
#     "branch_name": "fix/2026-04-10-tfe-unit-3-clusters" | None,
#     "commit_hashes": [ "aaa11111", "bbb22222", "ccc33333" ],  # one per cluster
#     "pr_url": "https://github.com/..." | None,
#     "error": None | "error message",
# }
```

**Partial-progress semantics**: If cluster C2's commit fails mid-batch, C1 and C3 still
commit successfully. `commit_hashes` comes back with fewer entries than clusters, and
`error` is set to the first failure message. Callers decide whether to proceed.

### Never raises

Both entry points wrap all `GitOps` calls in try/except. Failures surface via the
`error` field in the returned dict. This is critical for the async phase pipeline —
git errors never propagate up to crash the orchestrator.

---

## 5. `FixExecutor` — Polymorphic Coder+Tester Loop

`FixExecutor.execute_fix()` implements the retry loop: initial Coder delegation, Tester
verification, redelegation on failure, escalation on max iterations. It is the shared
engine that both BFE and TFE delegate to for the actual code-change work.

**Source**: `src/cosa/agents/shared/fix_executor.py`

### Construction

```python
executor = FixExecutor(
    config                 = agent_config,      # duck-typed, must have max_fix_attempts, wall_clock_timeout_secs, feedback_timeout_seconds
    fix_context            = agent_fix_context, # duck-typed pass-through — the agent's own context object
    job_id                 = "bfe-abc12345",
    prompt_builder_key     = "bfe",             # "bfe" or "tfe" — looked up in FIX_PROMPT_BUILDERS
    voice_io_module        = bfe.voice_io,      # agent's voice_io module
    cosa_interface_module  = bfe.cosa_interface,# agent's cosa_interface module
    notify_fn              = orchestrator._notify,    # async(voice_io, msg, priority, abstract=None)
    is_cancelled_fn        = orchestrator._is_cancelled,   # sync() → bool
    delegate_to_coder_fn   = orchestrator._delegate_to_coder,  # async(voice_io, prompt, guard, cosa) → (output, files)
    verify_fix_fn          = orchestrator._verify_fix,         # async(voice_io, fix, output, files, guard, cosa) → (passed, output)
    debug                  = False,
    verbose                = False,
)
```

**Why callbacks, not methods?** Agent orchestrators (BFE / TFE) retain ownership of
their Coder/Tester SDK delegation because:

1. **Test compatibility**: BFE's 58 unit tests patch `orchestrator._delegate_to_coder`
   and `orchestrator._verify_fix` directly via `patch.object()`. Moving those methods
   into `FixExecutor` would have broken every test.
2. **Agent-specific options**: the Claude Agent SDK `ClaudeAgentOptions` need the
   right `system_prompt`, `cwd`, and `can_use_tool` callback — each comes from the
   agent's own package. The callback pattern lets each agent build its own options
   while sharing the retry loop.

**What stays in the executor**: the `for iteration in range(max_fix_attempts)` loop,
SafetyGuard construction, prompt building via the registered builders, escalation via
`cosa_interface.present_choices()` on max-iteration failure.

### The retry loop

```
Iteration 1:
    build_fix_prompt(selected_fix, diagnosis, fix_context)
    → delegate_to_coder_fn → (coder_output, files_changed)
    → verify_fix_fn → (passed, tester_output)
    if passed → SUCCESS, return
    if iteration >= max_fix_attempts → escalation via present_choices()
    else:
        build_redelegate_prompt(selected_fix, coder_output, tester_output, iteration+1)
        → delegate_to_coder_fn → (new_coder_output, new_files)
Iteration 2:
    verify_fix_fn again
    ...
```

**Escalation**: When the Tester rejects the fix on the last iteration, the executor
presents the user a multiple-choice gate via `cosa_interface.present_choices()`:

- **Accept without tests** → `FixResult(applied=True, success=False, retry_eligible=True)`
- **Reject fix** → `FixResult(applied=False, success=False)`

On timeout or proxy unavailable, the gate treats the absence of a response as "reject."

### Return value

```python
fix_result, files_changed = await executor.execute_fix(
    diagnosis    = diagnosis,
    selected_fix = selected_fix,
)

# fix_result is a FixResult pydantic model (from cosa.agents.bug_fix_expediter.state):
#   applied: bool            # Did any code change land on disk?
#   success: bool            # Did the fix pass verification?
#   details: str             # Human-readable summary
#   retry_eligible: bool     # Can this be retried?
#   git_strategy: str | None # Populated in Phase 5
#   commit_hash: str | None
#   branch_name: str | None
#   pr_url: str | None
```

**Shared `FixResult` type**: Both BFE and TFE reuse the same Pydantic model defined
in `src/cosa/agents/bug_fix_expediter/state.py` (lines 102-120). This is a deliberate
upward dependency — `shared/fix_executor.py` imports `FixResult` from BFE's state
module. TFE also imports the same type.

---

## 6. `FIX_PROMPT_BUILDERS` Registry

The polymorphic prompt registry maps agent strings (`"bfe"`, `"tfe"`) to bundles of
prompt builders plus system prompts. Each agent registers its bundle at **import
time** from its `prompts/fix.py` module.

### Registry contract

```python
FIX_PROMPT_BUILDERS: dict[ str, dict ] = {
    "bfe": {
        "build_fix_prompt"         : callable,   # (selected_fix, diagnosis, fix_context) → str
        "build_verify_prompt"      : callable,   # (selected_fix, coder_output, files_changed) → str
        "build_redelegate_prompt"  : callable,   # (selected_fix, coder_output, tester_output, iteration) → str
        "coder_system_prompt"      : str,        # ClaudeAgentOptions.system_prompt for the Coder agent
        "tester_system_prompt"     : str,        # ClaudeAgentOptions.system_prompt for the Tester agent
    },
    "tfe": { ... same shape ... },
}
```

### How registration happens

Each agent's `prompts/fix.py` runs `register_fix_prompts()` at import time:

```python
# src/cosa/agents/test_fix_expediter/prompts/fix.py (bottom of file)

from cosa.agents.shared.fix_executor import register_fix_prompts

register_fix_prompts(
    "tfe",
    build_fix_prompt        = build_fix_prompt,
    build_verify_prompt     = build_verification_prompt,
    build_redelegate_prompt = build_redelegation_prompt,
    coder_system_prompt     = CODER_SYSTEM_PROMPT,
    tester_system_prompt    = TESTER_SYSTEM_PROMPT,
)
```

**Import order matters**: the registration must run BEFORE any code attempts to
construct a `FixExecutor` with `prompt_builder_key="tfe"`. In practice, both BFE and
TFE orchestrators import `prompts.fix` at the top of the orchestrator module, so the
registration happens on first import.

Unit test: `src/tests/unit/test_tfe_phase3_fix.py::TestTFEPromptRegistration` asserts
`"tfe"` is present in the registry after import.

### Why system prompts live in the registry

The per-agent system prompts (`coder_system_prompt`, `tester_system_prompt`) are stored
alongside the builder functions even though `FixExecutor` doesn't read them directly.
Each agent's **own** `_build_coder_options()` method reads them from the registry when
constructing `ClaudeAgentOptions`. Storing them together makes auditing easy — you can
see at a glance which prompts an agent will send by inspecting `FIX_PROMPT_BUILDERS[agent_key]`.

---

## 7. How to Add a New Expediter Agent

Suppose you're adding a hypothetical `IntegrationFixExpediter` that auto-fixes
integration test failures. Here's the checklist:

1. **Create the agent package** under `src/cosa/agents/integration_fix_expediter/`
   following the [agentic-voice-workflow skill](../../workflow/agentic-voice-workflow.md).

2. **Define your input context** (`state.py`) — pydantic model with whatever fields
   your prompts need to reason about. No need to match BFE or TFE shape.

3. **Write your prompts** in `prompts/fix.py`:
   - `CODER_SYSTEM_PROMPT` — string
   - `TESTER_SYSTEM_PROMPT` — string
   - `build_fix_prompt(selected_fix, diagnosis, fix_context) → str`
   - `build_verification_prompt(selected_fix, coder_output, files_changed) → str`
   - `build_redelegation_prompt(selected_fix, coder_output, tester_output, iteration) → str`

4. **Register at import time** at the bottom of `prompts/fix.py`:

   ```python
   from cosa.agents.shared.fix_executor import register_fix_prompts

   register_fix_prompts(
       "ife",  # pick a short agent key
       build_fix_prompt        = build_fix_prompt,
       build_verify_prompt     = build_verification_prompt,
       build_redelegate_prompt = build_redelegation_prompt,
       coder_system_prompt     = CODER_SYSTEM_PROMPT,
       tester_system_prompt    = TESTER_SYSTEM_PROMPT,
   )
   ```

5. **In your orchestrator's Phase 3** (fix delegation), construct a `FixExecutor`:

   ```python
   from cosa.agents.shared.fix_executor import FixExecutor
   from cosa.agents.integration_fix_expediter import voice_io, cosa_interface

   executor = FixExecutor(
       config                 = self.config,
       fix_context            = your_context_object,
       job_id                 = self.id_hash,
       prompt_builder_key     = "ife",
       voice_io_module        = voice_io,
       cosa_interface_module  = cosa_interface,
       notify_fn              = self._notify,
       is_cancelled_fn        = self._is_cancelled,
       delegate_to_coder_fn   = self._delegate_to_coder,   # your own method
       verify_fix_fn          = self._verify_fix,           # your own method
       debug                  = self.debug,
       verbose                = self.verbose,
   )
   fix_result, files_changed = await executor.execute_fix(
       diagnosis=diagnosis, selected_fix=selected_fix,
   )
   ```

6. **Implement `_delegate_to_coder()` and `_verify_fix()` on your orchestrator**.
   These are the SDK wiring: they construct `ClaudeAgentOptions` with the right
   `system_prompt` (pulled from `FIX_PROMPT_BUILDERS["ife"]["coder_system_prompt"]`),
   call `sdk_query()`, and iterate the message stream collecting text + tool uses.
   Copy the pattern from `src/cosa/agents/test_fix_expediter/orchestrator.py`.

7. **Use `GitStrategist.commit_and_pr_single()` or `commit_and_pr_multi()`** in your
   Phase 5 depending on whether you produce one fix or N clustered fixes.

8. **Write unit tests** covering the prompt registration, the executor callback wiring
   via mocks, and the git strategy. See `src/tests/unit/test_tfe_phase3_fix.py` as a
   reference — specifically the `TestTFEPromptRegistration` and `TestFixContextConstruction`
   test classes.

**What you do NOT need**: your own retry loop, your own escalation gate, your own
git-strategy mapping, your own plan-writer. All of that is reused from `shared/`.

---

## 8. Test Coverage

### Shared module tests

| Test file | What it covers |
|-----------|----------------|
| `src/tests/unit/test_tfe_phase3_fix.py::TestTFEPromptRegistration` | TFE prompts land in `FIX_PROMPT_BUILDERS["tfe"]` on import |
| `src/tests/unit/test_tfe_phase3_fix.py::TestFixContextConstruction` | `FixExecutor` constructor receives the right context + callbacks |
| `src/tests/unit/test_tfe_phase5_git.py::TestCommitAndPrMultiL1` | `commit_and_pr_multi()` L1 path (commit_only N sequential commits) |
| `src/tests/unit/test_tfe_phase5_git.py::TestCommitAndPrMultiL3` | `commit_and_pr_multi()` L3+ path (branch + N commits + push + PR) |
| `src/tests/unit/test_tfe_phase5_git.py::TestPhase5GitHelpers` | `resolve_trust_level`, `generate_slug`, static helpers |
| `src/tests/unit/test_bfe_phase5.py` | BFE's `commit_and_pr_single()` path (inherited via the extraction shim) |
| `src/tests/unit/test_bfe_fix.py` | BFE's `FixExecutor` callbacks still exercised through the post-extraction shim |
| `src/tests/unit/test_bfe_git_ops.py` | `GitOps` async subprocess wrapper (unchanged since extraction) |

**BFE regression through extraction**: all 58 BFE Phase 6 tests continued to pass
byte-for-byte through the three extraction commits (PlanWriter, GitStrategist,
FixExecutor). See the extraction execution log at
[`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/90-extraction-execution-log.md`](../../rnd/v0.1.6/2026.04.10-test-fix-expediter/90-extraction-execution-log.md).

### Regression gate

Any change to `src/cosa/agents/shared/` must pass both test suites:

```bash
# BFE side (existing 58 tests + BFE-specific extraction shim tests)
pytest src/tests/unit/test_bfe_*.py -v

# TFE side (197 tests including shared-module exercises)
pytest src/tests/unit/test_tfe_*.py -v

# Full unit regression
pytest src/tests/unit/ --tb=no -q
```

All green as of 2026-04-10: **3119 passed, 1 xfailed**.

---

## Related Documentation

- **[Bug Fix Expediter Guide](bug-fix-expediter-guide.md)** — BFE architecture, phases, INI keys, operator playbook
- **[Test Fix Expediter Guide](test-fix-expediter-guide.md)** — TFE architecture, phases, watchdog, operator playbook
- **[Test-Suite Scheduling Guide](test-suite-scheduling-guide.md)** — TestSuiteJob + `/schedule-tests` skill workflow
- **[Agentic Voice Workflow Skill](../../workflow/agentic-voice-workflow.md)** — canonical reference for building any new agentic job (not just expediters)
- **R&D planning docs** (historical): [TFE plan index](../../rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md), [BFE plan index](../../rnd/v0.1.6/2026.03.27-bug-fix-expediter/00-index.md)
