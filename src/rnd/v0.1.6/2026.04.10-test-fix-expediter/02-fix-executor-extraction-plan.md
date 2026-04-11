# 02 — FixExecutor / GitStrategist / PlanWriter Extraction Plan

## Goal

Extract the reusable fix-application + git-strategy + plan-writer primitives out of BFE into `src/cosa/agents/shared/` so TFE can reuse them without contaminating BFE's dead-job-specific code. Each extraction commit must be **behaviorally identical** to the BFE status quo — regression gate is the full BFE test suite.

## Ordering (by risk, ascending)

| Step | Extract | Risk | Tests that must stay green |
|------|---------|------|-----------------------------|
| 1 | `PlanWriter` | Low (pure text writer, no LLM wiring) | `test_bfe_plan_writer.py` + any BFE orchestrator tests that construct a PlanWriter |
| 2 | `GitStrategist` | Medium (trust proxy wiring, async subprocess, gh CLI degradation) | `test_bfe_phase5.py`, `test_bfe_git_ops.py` |
| 3 | `FixExecutor` | High (coder+tester SDK clients, redelegation loop, cancellation plumbing) | `test_bfe_fix.py`, `test_bfe_orchestrator.py`, full BFE suite |

Each step is a separate commit with a pytest regression gate. Do NOT batch them. If step 3 hits trouble (expected), keep steps 1 and 2 landed and iterate on step 3 in isolation.

---

## Step 1 — PlanWriter extraction

### Current state

`src/cosa/agents/bug_fix_expediter/plan_writer.py` defines `PlanWriter` class with:
- `write_initial_plan(dead_job_context, diagnosis, proposed_fixes) → str` (path)
- `update_after_fix(plan_path, fix_result, files_changed)`
- `update_git_references(plan_path, fix_result)` (added in Phase 5)
- `_render_header`, `_render_body`, `_render_footer` helpers

It's already generic enough — only takes a `user_email` at construction and a `plan_path` at write time. No dead-job-specific logic in the writer itself.

### Refactor

1. Move the file verbatim to `src/cosa/agents/shared/plan_writer.py`.
2. Update imports in BFE:
   - `bug_fix_expediter/orchestrator.py` — `from cosa.agents.shared.plan_writer import PlanWriter`
   - `bug_fix_expediter/job.py` — same
3. **Backwards compatibility stub** at the old path only if any code outside BFE imports it. Grep first:
   ```bash
   grep -rn "bug_fix_expediter.plan_writer\|bug_fix_expediter import plan_writer" src/
   ```
   If zero hits outside BFE, delete the old file. If any hit, leave a re-export stub: `from cosa.agents.shared.plan_writer import *`.
4. Update `test_bfe_plan_writer.py` (if it exists) import path.

### Regression gate

```bash
pytest src/tests/unit/ -v --tb=no -q | tail -5
```
Totals must not regress. Targeted run:
```bash
pytest src/tests/unit/test_bfe_plan_writer.py -v
pytest src/tests/unit/test_bfe_orchestrator.py -v
```

---

## Step 2 — GitStrategist extraction

### Current state

BFE's `orchestrator.py` contains `run_git_strategy()` (~line 1138), `_resolve_trust_level()`, `_finalize_git_strategy()`, `_generate_slug()` — the trust-level → git action mapping and the actual `git_ops.GitOps` invocation. BFE's `git_ops.py` is a standalone async wrapper around `git` and `gh` CLI calls and stays where it is (it's already reusable — TFE imports it).

### Refactor

Create `src/cosa/agents/shared/git_strategist.py`:

```python
from cosa.agents.bug_fix_expediter.git_ops import GitOps
from cosa.agents.swe_team.proxy.engineering_strategy import EngineeringStrategy

class GitStrategist:
    def __init__(self, config, session_id, job_id, voice_io_module,
                 debug=False, verbose=False): ...

    def _resolve_trust_level(self) -> int: ...
    def _generate_slug(self, context_tag: str) -> str: ...

    async def commit_and_pr_single(
        self,
        files_changed: list[str],
        fix: ProposedFix,
        plan_path: str,
        trust_level: int,
    ) -> dict:
        """BFE path. One fix → one commit or one branch+PR."""

    async def commit_and_pr_multi(
        self,
        clusters: list[tuple[str, list[str], ProposedFix]],
        # (cluster_title, files_for_this_cluster, fix_for_this_cluster)
        plan_path: str,
        trust_level: int,
    ) -> dict:
        """TFE path. K clusters → one branch, N commits, one PR."""
```

### Trust-to-git mapping (reused as-is)

| Trust Level | Mode | Git Strategy |
|---|---|---|
| L1 (shadow) | passive | `commit_only` on current branch |
| L2 (suggest) | passive | `commit_only` on current branch |
| L3+ (active) | active | `branch_and_pr` via `gh` |
| Proxy unavailable | — | `commit_only` |
| `gh` CLI missing | — | Degrade L3+ → `branch_only` |

### BFE shim

```python
# bug_fix_expediter/orchestrator.py
from cosa.agents.shared.git_strategist import GitStrategist

class BFEOrchestrator:
    def __init__(self, ...):
        self._git_strategist = GitStrategist(
            config=self.config, session_id=self.session_id,
            job_id=self.job_id, voice_io_module=voice_io,
            debug=self.debug, verbose=self.verbose
        )

    async def run_git_strategy(self, fix_result, files_changed, plan_path):
        """Shim: delegates to shared GitStrategist."""
        trust_level = self._git_strategist._resolve_trust_level()
        return await self._git_strategist.commit_and_pr_single(
            files_changed=files_changed,
            fix=self.last_selected_fix,
            plan_path=plan_path,
            trust_level=trust_level,
        )
```

### Regression gate

```bash
pytest src/tests/unit/test_bfe_phase5.py -v
pytest src/tests/unit/test_bfe_git_ops.py -v
pytest src/tests/unit/ -v --tb=no -q | tail -5
```

---

## Step 3 — FixExecutor extraction (riskiest)

### Current state

BFE `run_fix()` (orchestrator.py:960 and following) contains:
- SafetyGuard construction
- Coder agent delegation via Claude Agent SDK (`_delegate_to_coder`, `_build_coder_options`)
- Tester agent delegation (`_verify_fix`, `_build_tester_options`)
- Redelegation loop (up to `max_fix_attempts`, default 2)
- Plan log update on exit

These ~200 lines are tightly coupled to `self.dead_job_context` for prompt building and to `self.proxy` for trust gating. Extraction must decouple both.

### New module: `shared/fix_executor.py`

```python
# --- FixContext — polymorphic input shape ---

class FixContext(BaseModel):
    user_email          : str
    root_cause          : str
    error_category      : str
    affected_components : list[str]
    origin_label        : str   # "dead_job: dr-abc" or "test_cluster: C2"
    origin_details      : dict  # dead-job error/trace OR cluster failure metadata
    prompt_builder_key  : str   # "bfe" | "tfe"

    @classmethod
    def from_dead_job(cls, ctx, diagnosis) -> "FixContext":
        return cls(
            user_email=ctx.user_email,
            root_cause=diagnosis.root_cause,
            error_category=diagnosis.error_category,
            affected_components=diagnosis.affected_components,
            origin_label=f"dead_job:{ctx.id_hash}",
            origin_details={"error": ctx.error, "stack_trace": ctx.stack_trace,
                            "question_text": ctx.question_text,
                            "metadata_json": ctx.metadata_json},
            prompt_builder_key="bfe",
        )

    @classmethod
    def from_test_cluster(cls, cluster, diagnosis, user_email) -> "FixContext":
        return cls(
            user_email=user_email,
            root_cause=diagnosis.root_cause,
            error_category=diagnosis.error_category,
            affected_components=diagnosis.affected_components,
            origin_label=f"test_cluster:{cluster.cluster_id}",
            origin_details={"failure_indices": cluster.failure_indices,
                            "shared_error_signature": cluster.shared_error_signature,
                            "hypothesis": cluster.hypothesis,
                            "test_symptoms": diagnosis.test_symptoms},
            prompt_builder_key="tfe",
        )

# --- Polymorphic prompt registry ---

# Each prompts/fix.py module registers itself at import time:
#   from cosa.agents.shared.fix_executor import register_fix_prompts
#   register_fix_prompts("bfe", build_fix_prompt=..., build_verify_prompt=...,
#                        build_redelegate_prompt=...)

FIX_PROMPT_BUILDERS: dict[str, tuple[Callable, Callable, Callable]] = {}

def register_fix_prompts(key, *, build_fix_prompt, build_verify_prompt,
                         build_redelegate_prompt):
    FIX_PROMPT_BUILDERS[key] = (build_fix_prompt, build_verify_prompt,
                                build_redelegate_prompt)

# --- FixExecutor — the extracted engine ---

class FixExecutor:
    def __init__(self, config, session_id, job_id, voice_io_module,
                 cosa_interface_module, cancel_check, on_notify,
                 debug=False, verbose=False):
        self.config               = config
        self.session_id           = session_id
        self.job_id               = job_id
        self._voice_io            = voice_io_module
        self._cosa                = cosa_interface_module
        self._cancel_check        = cancel_check
        self._on_notify           = on_notify
        self.debug                = debug
        self.verbose              = verbose

    async def execute_fix(
        self,
        proposed_fix : ProposedFix,
        fix_context  : FixContext,
        plan_path    : str,
    ) -> tuple[FixResult, list[str]]:
        """
        Requires:
            - fix_context.prompt_builder_key is registered in FIX_PROMPT_BUILDERS
        Ensures:
            - returns (result, files_changed)
            - never raises; errors surfaced via FixResult.success=False and details
        """
        builders = FIX_PROMPT_BUILDERS[fix_context.prompt_builder_key]
        build_fix, build_verify, build_redelegate = builders
        # ... coder delegation loop, tester verification, redelegation ...
        return fix_result, files_changed
```

### BFE `prompts/fix.py` registration

At the bottom of `bug_fix_expediter/prompts/fix.py`:
```python
from cosa.agents.shared.fix_executor import register_fix_prompts

register_fix_prompts(
    "bfe",
    build_fix_prompt=build_fix_prompt,
    build_verify_prompt=build_verification_prompt,
    build_redelegate_prompt=build_redelegation_prompt,
)
```

### BFE shim

```python
# bug_fix_expediter/orchestrator.py
from cosa.agents.shared.fix_executor import FixExecutor, FixContext

class BFEOrchestrator:
    def __init__(self, ...):
        # ... existing init ...
        self._fix_executor = FixExecutor(
            config=self.config, session_id=self.session_id,
            job_id=self.job_id, voice_io_module=voice_io,
            cosa_interface_module=cosa_interface,
            cancel_check=self._cancel_check,
            on_notify=self._on_notify,
            debug=self.debug, verbose=self.verbose,
        )

    async def run_fix(self, diagnosis, selected_fix, plan_path):
        """Shim: delegates to shared FixExecutor."""
        fix_context = FixContext.from_dead_job(self.dead_job_context, diagnosis)
        fix_result, files_changed = await self._fix_executor.execute_fix(
            proposed_fix=selected_fix,
            fix_context=fix_context,
            plan_path=plan_path,
        )
        self.last_files_changed = files_changed
        return fix_result
```

Net BFE orchestrator change: ~200 lines → ~20 lines (shim). The ~180 lines move to `shared/fix_executor.py`.

### Tests touched

- `test_bfe_fix.py` — update imports, adapt test inputs to construct `FixContext.from_dead_job()` where they previously built raw dead-job fixtures.
- `test_bfe_orchestrator.py` — shim delegation assertions. Verify `run_fix()` calls `_fix_executor.execute_fix()` with a correctly-built `FixContext`.
- **New**: `src/tests/unit/test_fix_executor_shared.py` — exercises the polymorphic registry with both a `"bfe"` mock and a `"tfe"` mock, verifies each branch independently.

### Regression gate

```bash
pytest src/tests/unit/test_bfe_fix.py -v
pytest src/tests/unit/test_bfe_orchestrator.py -v
pytest src/tests/unit/test_fix_executor_shared.py -v
pytest src/tests/unit/ -v --tb=no -q | tail -10
```

All BFE tests from the 58-test Phase 6 suite must stay green. Expect 2-3 iterations — SafetyGuard wiring and cancellation plumbing are fragile.

---

## Rollback protocol

If any extraction step breaks BFE tests that I can't resolve within 30 minutes of iterating:

1. Revert the step's commit.
2. Notify the user via cosa-voice urgent.
3. Stop — do not proceed to the next extraction step.
4. File an investigation note under `90-extraction-execution-log.md` with the observed failure mode and current hypothesis.

The extraction is a prerequisite for TFE but cannot come at the cost of BFE regressions. If rollback is needed, we re-plan: either a smaller extraction surface or a delayed extraction after BFE Phase 6 live E2E fully baselines.
