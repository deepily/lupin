> Part 3 of 3 of the [Bug Fix Expediter (BFE) Guide](../bug-fix-expediter-guide.md): sections 8 and 9, troubleshooting, the code map and related documents.

## 8. Troubleshooting

### BFE never fires on my failed jobs

**Check 1**: Is `bug fix expediter enabled = true` in `lupin-app.ini`? Restart the
server after editing.

**Check 2**: Is the failed job an agentic job (subclass of `AgenticJobBase`)? BFE
only processes agentic jobs — regular code-runner jobs and notifications are
skipped by the dead-queue watchdog.

**Check 3**: Was the error classified as transient/infra (timeout, OOM, rate limit)?
The `DeadQueueWatchdog` skips these on purpose — they're usually not code bugs. Check
the FastAPI log for `[DeadQueueWatchdog]` lines explaining why a job was skipped.

**Check 4**: Has the `RepairAttemptTracker` already exhausted its budget for this
`(job_id, routing_command)` key? BFE won't retry forever. Reset via restart or by
clearing the in-memory tracker state.

### Claude Agent SDK not installed

BFE's Phase 3 (Fix) requires `claude-agent-sdk`. If you see
`Claude Agent SDK not available` in the logs, install it:

```bash
pip install claude-agent-sdk
```

The `SDK_AVAILABLE` flag at the top of `orchestrator.py` gates all SDK-dependent
code. Without it, Phase 3 gracefully returns `FixResult(applied=False, success=False)`
and the job completes without crashing.

### Diagnosis confidence is always low

Possible causes:

1. **Insufficient stack trace**: the dead job didn't capture a full traceback, so
   the Lead agent has nothing to reason about. Check `metadata_json.stack_trace`
   on the dead job in `job_history`.
2. **Model rate limited**: the Lead agent hit rate limits during iteration. Check
   for `RateLimitEvent` warnings in the log.
3. **Budget exhausted**: `bug fix expediter budget usd` was hit mid-run. Check the
   cost tracker summary in the plan doc footer.
4. **Root cause genuinely obscure**: some bugs need human investigation.
   Lowering `bug fix expediter min diagnosis confidence` (e.g., 0.5) lets BFE
   proceed with lower-confidence diagnoses, but the fix success rate drops.

### Fix phase keeps failing verification

The Coder keeps producing changes but the Tester rejects them. This often indicates:

1. **Tests exist and are running correctly** — good, the Coder just hasn't found
   the right fix yet. Let the retry loop continue up to `max_fix_attempts`.
2. **Tests don't exist** — the Coder has nothing to verify against. The Tester will
   try to write targeted tests first; if it can't, verification is weak.
3. **The diagnosis was wrong** — Phase 1 misidentified the root cause. The Coder is
   applying a well-formed but ineffective fix. Re-run with a higher
   `min_diagnosis_confidence` threshold, or cancel and fix manually.

### Git branch conflicts

Level 3+ mode creates branches named `fix/YYYY-MM-DD-{slug}`. If a branch with the same
name already exists from a prior BFE run, `create_fix_branch()` fails and the
strategy degrades. Options:

- Manually delete the stale branch: `git branch -D fix/2026-04-10-foo`
- Tune `GitStrategist._generate_slug()` to add a uniqueness suffix (not currently
  implemented — filed as a follow-up in the R&D dir)

### PR creation fails (`gh not found`)

The strategist degrades to `branch_only` mode automatically and emits a
high-priority notification. The fix branch still exists.
With `bug fix expediter push fix branch enabled = true`, it has also been pushed.
You can manually create the PR via `gh pr create` or the GitHub web UI. To prevent this,
install `gh` CLI on the host:

```bash
# Ubuntu
sudo apt install gh

# macOS
brew install gh

# Authenticate
gh auth login
```

### Voice gates never come back

If you approved a diagnosis but the fix phase never advances, check cosa-voice MCP
connectivity:

```bash
cd /tmp && claude mcp get cosa-voice
```

Should show `Scope: User config (available in all your projects)`. If missing, run
`bash $LUPIN_ROOT/src/scripts/install-cosa-voice.sh` and restart Claude Code.

Voice gate timeout is controlled by `bug fix expediter feedback timeout seconds`
(default 300s / 5 minutes). After timeout, the gate treats the absence of a response
as rejection.

---

## 9. Code Map

Use this table to find the implementation of any concept mentioned above:

| Concept | Source file | Key symbols |
|---------|-------------|-------------|
| Job class | `src/cosa/agents/bug_fix_expediter/job.py` | `BugFixExpediterJob`, `_resubmit_original_job` |
| Orchestrator | `src/cosa/agents/bug_fix_expediter/orchestrator.py` | `BFEOrchestrator`, `run_diagnosis`, `run_proposal`, `run_fix` (shim), `run_git_strategy` (shim), `_voice_gate_diagnosis`, `_voice_gate_proposal`, `_delegate_to_coder`, `_verify_fix` |
| Config | `src/cosa/agents/bug_fix_expediter/config.py` | `BugFixExpediterConfig` dataclass, `from_config()` |
| State | `src/cosa/agents/bug_fix_expediter/state.py` | `BFEPhase` enum, `DeadJobContext`, `DiagnosisResult`, `ProposedFix`, `FixResult`, `BFEState` |
| Dead-job packaging | `src/cosa/agents/bug_fix_expediter/dead_job_packager.py` | `package_dead_job(dead_job_id)` |
| Diagnosis prompts | `src/cosa/agents/bug_fix_expediter/prompts/diagnosis.py` | `DIAGNOSIS_SYSTEM_PROMPT`, `build_diagnosis_prompt` |
| Proposal prompts | `src/cosa/agents/bug_fix_expediter/prompts/proposal.py` | `PROPOSAL_SYSTEM_PROMPT`, `build_proposal_prompt` |
| Fix prompts | `src/cosa/agents/bug_fix_expediter/prompts/fix.py` | `CODER_SYSTEM_PROMPT`, `TESTER_SYSTEM_PROMPT`, prompt builders, `register_fix_prompts("bfe", ...)` |
| Git operations | `src/cosa/agents/bug_fix_expediter/git_ops.py` | `GitOps` async wrapper around git + gh CLI |
| Dead-queue watchdog | `src/cosa/rest/dead_queue_watchdog.py` | `DeadQueueWatchdog`, `init_watchdog`, `RepairAttemptTracker` |
| Unified watchdog facade | `src/cosa/rest/watchdogs.py` | `init_watchdogs(config_mgr, todo_queue, debug, verbose)` — single entry point for both BFE and TFE watchdog singletons; called from `src/lupin_app/main.py` at startup |
| Shared primitives | `src/cosa/agents/shared/` | `PlanWriter`, `GitStrategist`, `FixExecutor`, `FIX_PROMPT_BUILDERS` |

### R&D archive

Historical planning documents live under
[`src/rnd/v0.1.6/2026.03.27-bug-fix-expediter/`](../../../rnd/v0.1.6/2026.03.27-bug-fix-expediter/00-index.md):

- `00-index.md` — navigation
- `01-implementation-plan.md` — original end-to-end plan
- `02-agentic-job-consistency-audit.md` — phase-zero prerequisite audit
- `03-phase2-diagnose-orchestrator-plan.md` through `08-phase6-automated-repair-loop-plan.md` — per-phase detailed plans
- `07-phase5-execution-log.md` — Phase 5 implementation log (actual work done)

These are frozen planning artifacts — they explain why BFE is designed the way it
is. The guide you're reading now explains how to use and maintain it.

---

## Related Documentation

- **[Shared Fix Primitives Reference](../shared-fix-primitives-reference.md)** — `PlanWriter`, `GitStrategist`, `FixExecutor` details
- **[Test Fix Expediter Guide](../test-fix-expediter-guide.md)** — sister agent for test-failure recovery, shares the same Phase 3 and Phase 5 engines
- **[Decision Proxy Admin Guide](../../proxy-admin-guide.md)** — trust levels and ratification workflow
- **[REST API Reference](../../rest-api-reference.md)** — `/api/bug-fix-expediter/submit` endpoint schema
- **[Agentic Voice Workflow Skill](../../../workflow/agentic-voice-workflow.md)** — conventions for building any new agentic job
