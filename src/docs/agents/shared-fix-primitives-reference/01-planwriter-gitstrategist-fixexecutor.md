> Part 1 of 2 of the [Shared Fix Primitives Reference](../shared-fix-primitives-reference.md): sections 1 to 5, from the package layout to `FixExecutor`.

# Shared Fix Primitives Reference

**Audience**: Developers adding a new expediter agent or debugging behavior shared between BFE and TFE.

**Scope**: `src/cosa/agents/shared/` — `PlanWriter`, `GitStrategist`, `FixExecutor`, `FIX_PROMPT_BUILDERS` registry.

**Last Updated**: 2026-04-10.

**See Also**:

- [Bug Fix Expediter Guide](../bug-fix-expediter-guide.md)
- [Test Fix Expediter Guide](../test-fix-expediter-guide.md)
- R&D: [`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/02-fix-executor-extraction-plan.md`](../../../rnd/v0.1.6/2026.04.10-test-fix-expediter/02-fix-executor-extraction-plan.md)

---

## Table of Contents

1. [Why the Shared Package Exists](#1-why-the-shared-package-exists)
2. [Package Layout](#2-package-layout)
3. [`PlanWriter` — Markdown Plan Docs](#3-planwriter--markdown-plan-docs)
4. [`GitStrategist` — Trust-Aware Git Operations](#4-gitstrategist--trust-aware-git-operations)
5. [`FixExecutor` — Polymorphic Coder+Tester Loop](#5-fixexecutor--polymorphic-codertester-loop)
6. [`FIX_PROMPT_BUILDERS` Registry](02-prompt-registry-new-agent-and-tests.md#6-fix_prompt_builders-registry)
7. [How to Add a New Expediter Agent](02-prompt-registry-new-agent-and-tests.md#7-how-to-add-a-new-expediter-agent)
8. [Test Coverage](02-prompt-registry-new-agent-and-tests.md#8-test-coverage)

---

## 1. Why the Shared Package Exists

The Bug Fix Expediter (BFE) and Test Fix Expediter (TFE) both apply code changes.
They do it through a **Coder → Tester → Retry** loop using the Claude Agent SDK. Both write
structured Markdown plan documents. Both commit changes via a trust-level-aware
git strategy. These concerns are **agent-agnostic** — the only parts that differ
between BFE and TFE are:

- **Input shape**: BFE consumes a `DeadJobContext` (one crashed job → one root cause),
  TFE consumes a `TestRemediationContext` (N failures → K root causes).
- **Prompts**: BFE's prompts reason about stack traces, TFE's reason about pytest
  `classname::name[param]` semantics.
- **Output**: BFE retries the original dead job, TFE reruns the affected test suites.

During the session of 2026-04-10 the reusable pieces were extracted into
`src/cosa/agents/shared/` as a peer of the agent packages — **not** a subordinate
of either. Agent packages import from `shared/`; `shared/` does not import from any
specific agent package. This keeps BFE's proven dead-job code path untouched while
giving TFE a fully-tested foundation.

**Key invariant**: adding a third expediter agent (e.g., a future `IntegrationFixExpediter`)
should require zero changes to `shared/`. It needs only new prompt modules that self-register
into the `FIX_PROMPT_BUILDERS` registry.

---

## 2. Package Layout

```
src/cosa/agents/shared/
├── __init__.py               # Re-exports the public API
├── plan_writer.py            # PlanWriter class (moved from BFE)
├── git_strategist.py         # GitStrategist class (new, extracted from BFE orchestrator)
├── fix_executor.py           # FixExecutor + FIX_PROMPT_BUILDERS registry (new)
└── resume_guard.py           # resume_covers(): has a resumed run's checkpoint reached a phase (BFE and TFE)
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

Phase numbers are those of the BFE and TFE pipelines:

- Phase 2: Propose
- Phase 3: Fix
- Phase 4: collapsed into Phase 3.
- Phase 5: Git
- Phase 6: Resubmit (BFE) or Rerun (TFE)

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

`GitStrategist` encapsulates the trust-level → git-strategy mapping. It executes the
actual commit / branch / push / PR operations via an injected `GitOps` instance
(from `src/cosa/agents/bug_fix_expediter/git_ops.py`). It has **two entry points**:

- `commit_and_pr_single()` — BFE path (one fix → one commit or one branch+PR)
- `commit_and_pr_multi()` — TFE path (K cluster fixes → one branch, N commits, one PR)

**Source**: `src/cosa/agents/shared/git_strategist.py`

### Trust-to-git mapping

Same table for both entry points:

| Trust Level | Mode | Git Strategy | Notes |
|-------------|------|--------------|-------|
| **Level 1 Shadow** | passive | `commit_only` on current branch | Baseline, no auto-branching |
| **Level 2 Suggest** | passive | `commit_only` on current branch | Reviewing mode |
| **Level 3+ Active** | active | `branch_and_pr` via `gh` CLI | Full auto: branch, push, PR |
| `gh` missing | — | Degrade level 3+ → `branch_only` | Branch + push succeed; PR step skipped |
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

Used when one fix produces one commit. If trust is level 1 or 2, it commits on the current
branch. At level 3 or above, it creates a new `fix/...` branch, pushes, and opens a PR via `gh`.

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

**Partial-progress semantics**: If the second cluster's commit fails mid-batch, the first and third still
commit successfully. `commit_hashes` comes back with fewer entries than clusters, and
`error` is set to the first failure message. Callers decide whether to proceed.

**Trust 3 and above pushes only when the caller's flag is on.**

`commit_and_pr_multi` takes `push_enabled`, `False`
by default, and TFE passes `test fix expediter push fix branch enabled`. After the N commits the strategist pushes once,
through `git_ops.push_branch( slug )`, and only then says "Pushed N commit(s)" and calls `create_pr`.
`GitOps.push_branch` pushes the branch `fix/<name>` with one explicit refspec, never forced, and refuses any other name.
With the flag off, `git_strategy` is `commit_only` and `pr_url` is `None`. The `error` reads "push disabled
(test fix expediter push fix branch enabled is false): nothing was pushed and no pull request was opened".
With no `push_branch`, or when it fails, nothing is pushed either and `error` names the cause. In every case the commits stay on the
new local branch, `create_pr` is not called, and the original branch is checked out again.

`commit_and_pr_single` follows the same rule for BFE. It takes `push_enabled`, `False` by default, and BFE passes
`bug fix expediter push fix branch enabled`. Off, it commits on the fix branch, skips `commit_and_push` and `create_pr`,
and restores the original branch. Trust levels 1 and 2 never push.

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

