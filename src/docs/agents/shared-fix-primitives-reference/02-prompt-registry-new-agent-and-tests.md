> Part 2 of 2 of the [Shared Fix Primitives Reference](../shared-fix-primitives-reference.md): sections 6 to 8, the prompt registry, new agents and tests.

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

**Import order matters**: the registration must run before any code attempts to
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
   following the [agentic-voice-workflow skill](../../../workflow/agentic-voice-workflow.md).

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
   These are the SDK wiring. They construct `ClaudeAgentOptions` with the right
   `system_prompt` (pulled from `FIX_PROMPT_BUILDERS["ife"]["coder_system_prompt"]`).
   They call `sdk_query()` and iterate the message stream collecting text + tool uses.
   Copy the pattern from `src/cosa/agents/test_fix_expediter/orchestrator.py`.

7. **Use `GitStrategist.commit_and_pr_single()` or `commit_and_pr_multi()`** in your
   Phase 5 depending on whether you produce one fix or N clustered fixes.

8. **Write unit tests** covering the prompt registration, the executor callback wiring
   via mocks, and the git strategy. See `src/tests/unit/test_tfe_phase3_fix.py` as a
   reference — specifically the `TestTFEPromptRegistration` and `TestFixContextConstruction`
   test classes.

**What you do not need**: your own retry loop, your own escalation gate, your own
git-strategy mapping, your own plan-writer. All of that is reused from `shared/`.

---

## 8. Test Coverage

### Shared module tests

| Test file | What it covers |
|-----------|----------------|
| `src/tests/unit/test_tfe_phase3_fix.py::TestTFEPromptRegistration` | TFE prompts land in `FIX_PROMPT_BUILDERS["tfe"]` on import |
| `src/tests/unit/test_tfe_phase3_fix.py::TestFixContextConstruction` | `FixExecutor` constructor receives the right context + callbacks |
| `src/tests/unit/test_tfe_phase5_git.py::TestCommitAndPrMultiL1` | `commit_and_pr_multi()` level 1 path (commit_only N sequential commits) |
| `src/tests/unit/test_tfe_phase5_git.py::TestCommitAndPrMultiL3` | `commit_and_pr_multi()` level 3+ path (branch + N commits + push + PR) |
| `src/tests/unit/test_tfe_phase5_git.py::TestPhase5GitHelpers` | `resolve_trust_level`, `generate_slug`, static helpers |
| `src/tests/unit/test_bfe_phase5.py` | BFE's `commit_and_pr_single()` path (inherited via the extraction shim) |
| `src/tests/unit/test_bfe_fix.py` | BFE's `FixExecutor` callbacks still exercised through the post-extraction shim |
| `src/tests/unit/test_bfe_git_ops.py` | `GitOps` async subprocess wrapper (unchanged since extraction) |

**BFE regression through extraction**: all 58 BFE Phase 6 tests continued to pass
byte-for-byte through the three extraction commits (PlanWriter, GitStrategist,
FixExecutor). See the extraction execution log at
[`src/rnd/v0.1.6/2026.04.10-test-fix-expediter/90-extraction-execution-log.md`](../../../rnd/v0.1.6/2026.04.10-test-fix-expediter/90-extraction-execution-log.md).

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

All green at the last recorded run: **3119 passed, 1 xfailed**.

---

## Related Documentation

- **[Bug Fix Expediter Guide](../bug-fix-expediter-guide.md)** — BFE architecture, phases, INI keys, operator playbook
- **[Test Fix Expediter Guide](../test-fix-expediter-guide.md)** — TFE architecture, phases, watchdog, operator playbook
- **[Test-Suite Scheduling Guide](../test-suite-scheduling-guide.md)** — TestSuiteJob + `/schedule-tests` skill workflow
- **[Agentic Voice Workflow Skill](../../../workflow/agentic-voice-workflow.md)** — canonical reference for building any new agentic job (not just expediters)
- **R&D planning docs** (historical): [TFE plan index](../../../rnd/v0.1.6/2026.04.10-test-fix-expediter/00-index.md), [BFE plan index](../../../rnd/v0.1.6/2026.03.27-bug-fix-expediter/00-index.md)
