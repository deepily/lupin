# 19 — TFE-to-CC: Parallel Claude Code Engine for Phases 1 + 3

**Filed**: 2026-04-19, Session be57a252
**Status**: Design (Phase 1 per the approved plan — no orchestrator code yet; Max-subscription smoke test is the gating artifact)
**Plan source**: `~/.claude/plans/let-s-start-a-new-structured-moonbeam.md`
**Direction**: Option 3 of 3 compared (Phase 0 stays deterministic, Phase 2 voice gate + CBR stay SDK-Opus, Phase 5/6 unchanged; Phases 1 and 3 gain a CC-engine option behind INI flags).

---

## Precipitating problem

`tfe-a1c6e15a` (2026-04-19 resumed from `tfe-72adc928`) produced **0/11 fixed** over 63 minutes. Total API-metered cost across 13 SDK calls: ~$6.50. Phase 3 alone accounted for ~$6.50; the Coder exhausted its turn budget on most fixes. Today's prompt audit (doc-paired session) identified inefficient exploration in the Coder's behavior. The more fundamental reality: **we're paying per-token for an orchestration that a polished off-the-shelf agent (Claude Code) already does better** — and the user is on a Claude Max 200 subscription whose flat rate makes the per-token cost effectively zero for the right invocation path.

## The core insight

The container already has everything:
- `/home/rruiz/.local/bin/claude` — Claude Code CLI 2.1.114 (installed via Dockerfile line ~238)
- `~/.claude/.credentials.json` — OAuth session credentials, bind-mounted read-only
- No `ANTHROPIC_API_KEY` env var in `docker-compose.yml`
- `ClaudeCodeJob` BOUNDED mode (`src/cosa/agents/claude_code/job.py` + dispatcher at `src/cosa/orchestration/claude_code/dispatcher.py`) which spawns `claude -p` as a subprocess with `--output-format stream-json --allowedTools --max-turns`
- REST endpoint `POST /api/claude-code/queue/submit` (`src/cosa/rest/routers/claude_code_queue.py`) that queues bounded CC jobs as `cc-<hash>`
- `TaskResult.cost_usd` reporting — **$0.00 confirms Max subscription; >$0 means API-key fallback**

Bridging TFE phases to this existing infrastructure gives us subscription-backed execution with zero new auth plumbing.

## The interactivity unlock (what tipped the scale to Option 3)

User observation: *"does the bounded Claude code job get access to a local MCP server since it runs in process? If that's the case, then Claude code can maintain interactivity/contact with me the operator while it's in flight, correct?"*

**Confirmed yes.** The dispatcher's hardcoded `--allowedTools` already includes `mcp__cosa-voice__{converse, notify, ask_yes_no}` — the same cosa-voice MCP server that TFE's Phase 2 voice gate uses today. Mechanism:

1. `claude -p` inside the container loads `~/.claude/.mcp.json` (copied in via Dockerfile), which registers `cosa-voice`
2. When Claude Code wants operator input, it calls `mcp__cosa-voice__ask_yes_no` (or similar)
3. The cosa-voice MCP server posts to Lupin's `/api/notify` with `response_requested=true`
4. Lupin broadcasts over WebSocket to the browser → notification card fires
5. Operator answers → Lupin returns → MCP tool returns → Claude Code resumes
6. Wall-clock timeout (default 3600s) caps the wait

**BOUNDED ≠ fire-and-forget**. CC can call the operator mid-diagnosis or mid-fix whenever it hits ambiguity. This renders yesterday's filed "Option B mid-flight check-in" follow-up obsolete — the capability is native to Claude Code + MCP.

## Option landscape (all three compared; Option 3 chosen)

| Option | Pivot | Cost reduction | Voice gate | CBR | Complexity |
|---|---|---|---|---|---|
| 1 — Phase 3 only | Fix application → CC | ~70-80% | ✅ preserved | ✅ preserved | Low |
| 2 — Whole pipeline via CC | 0–3 all to CC | 100% | ❌ lost | ❌ lost | Low structurally, high trust cost |
| **3 — Phases 1+3** ★ | Diagnose + Fix → CC | ~95% | ✅ preserved | ✅ preserved | Medium |

**Option 3 chosen** for two reasons: (a) Phase 1 diagnosis benefits from Claude Code's strong Grep/Read codebase exploration just as much as Phase 3 does, (b) the MCP interactivity unlock means CC can ask the operator clarifying questions during diagnosis too, which is qualitatively new capability not available in the SDK path today.

## Architecture — runtime fork, both paths permanent

```
  Phase 0: cluster              ← Python, deterministic (unchanged)

  Phase 1: diagnose
    if ini.phase_1_engine == "sdk":
      ← SDK-Opus path (existing; fully maintained)
    elif ini.phase_1_engine == "claude_code":
      ← TFE-to-CC diagnosis: one bounded CC job, MCP-interactive
        emits structured diagnosis JSON → Phase 2 reads it

  Phase 2: propose + voice gate ← SDK-Opus (unchanged — builds TFEProposedFix + CBR predicts)

  Phase 3: fix + verify
    if ini.phase_3_engine == "sdk":
      ← SDK-Sonnet Coder+Tester path (existing; fully maintained)
    elif ini.phase_3_engine == "claude_code":
      ← TFE-to-CC fix: one bounded CC job inside worktree, MCP-interactive
        CC commits per-fix; emits structured verdict JSON

  Phase 5: GitStrategist        ← Unchanged — reads worktree commits, opens PR
  Phase 6: TestSuiteJob         ← Unchanged — re-queue validation
```

### Critical principle: permanent fork, not a migration

Per user direction: *"If we're going to be using a runtime configuration value to fork and either pass the job off to a bounded claude code Instance or to the SDK, Then I do not want to delete any of the SDK code & functionality already implemented. That seems wasteful to jump to that as we may want to return to that capacity in the future."*

Both paths stay first-class. No "cleanup" phase. No "retire the loser." Operator selects engine per-run or per-deployment via INI. Unit tests cover both branches. The feature flag IS the steady-state architecture.

## Feature-flag surface

Two independent INI keys, one per TFE phase:
```ini
test fix expediter phase 1 engine = sdk        # default; alt: claude_code
test fix expediter phase 3 engine = sdk        # default; alt: claude_code
```

Independent flags let the operator flip Phase 3 on while Phase 1 still uses the SDK path (or vice versa). Each phase gets its own engine-selection logic at the top of the corresponding `run_phase{1,3}_*` method on `TFEOrchestrator`.

## Interactivity model (both CC-engine phases)

```
Phase 1 (engine=claude_code):
  CC reads failure bundle + codebase
  CC diagnoses each cluster
  IF ambiguous: CC invokes ask_yes_no / ask_multiple_choice / converse
    → Browser card fires, operator answers, CC resumes
  CC emits structured diagnoses JSON
  → flows into Phase 2 (SDK Opus, preserved)

Phase 2 (SDK Opus, unchanged):
  Builds TFEProposedFix objects from diagnoses (whether they came from SDK or CC path)
  Voice gate fires (ask_multiple_choice with N proposals + CBR prediction)
  Operator picks proposals

Phase 3 (engine=claude_code):
  CC reads selected proposals + diagnoses
  CC applies fixes inside worktree (cwd = /var/lupin/.claude/worktrees/<tfe-id>/)
  IF a fix is unclear: CC asks operator mid-flight
  CC commits per-fix in worktree
  CC emits structured verdict JSON → Phase 5 GitStrategist PRs
```

## Pre-req: dispatcher allowlist extension

Current dispatcher hardcodes:
```
Read, Write, Bash,
mcp__cosa-voice__converse,
mcp__cosa-voice__notify,
mcp__cosa-voice__ask_yes_no
```

TFE-to-CC needs the richer set (per user approval of full MCP tool exposure):
```
Read, Edit, Write, Bash, Grep, Glob,
mcp__cosa-voice__converse,
mcp__cosa-voice__notify,
mcp__cosa-voice__ask_yes_no,
mcp__cosa-voice__ask_multiple_choice,
mcp__cosa-voice__ask_open_ended_batch
```

Surgical change to `src/cosa/orchestration/claude_code/dispatcher.py`: add keyword-only `allowed_tools_override: Optional[list[str]] = None` to `dispatch()`. When set, replaces the hardcoded default. Default `None` preserves existing behavior for every other ClaudeCodeJob caller — zero regression risk.

## Critical files

### New (all created in future sessions — this session produces design doc only)

```
src/cosa/agents/tfe_to_cc/
  __init__.py
  orchestrator.py            — TFE_to_CC_Orchestrator
                                 run_phase1_diagnose_via_cc(clusters, failure_context) → dict
                                 run_phase3_fix_via_cc(selected_fixes, diagnoses, worktree) → dict
  prompts/
    __init__.py
    bundle_phase1.py         — build_diagnosis_bundle_prompt(clusters, failure_context) → str
    bundle_phase3.py         — build_fix_bundle_prompt(selected_fixes, diagnoses, worktree_path) → str
    output_contract.py       — fenced-JSON constants + parsers (with fallbacks)
  job.py                     — TFE_to_CC_Job (thin wrapper over ClaudeCodeJob BOUNDED)
```

### Modified (surgical, SDK path preserved in every case)

```
src/cosa/orchestration/claude_code/dispatcher.py
  + keyword-only `allowed_tools_override: Optional[list[str]] = None` on dispatch()
  + when set, replaces the hardcoded default tool list
  Default None → zero behavior change for existing callers.

src/cosa/agents/test_fix_expediter/orchestrator.py
  + at top of run_phase1_diagnose(): if self.config.phase_1_engine == "claude_code":
        return await TFE_to_CC_Orchestrator(self).run_phase1_diagnose_via_cc(...)
  + at top of run_phase3_fix(): if self.config.phase_3_engine == "claude_code":
        return await TFE_to_CC_Orchestrator(self).run_phase3_fix_via_cc(...)
  Else branch = existing SDK implementation, fully preserved.

src/cosa/agents/test_fix_expediter/config.py
  + phase_1_engine: str = "sdk"
  + phase_3_engine: str = "sdk"
  + key_map entries for both new INI keys

src/conf/lupin-app.ini + lupin-app-splainer.ini
  + test fix expediter phase 1 engine = sdk
  + test fix expediter phase 3 engine = sdk
  + splainer entries explaining the fork + cost/capability tradeoff
```

### What does NOT change — fully preserved

- `src/cosa/agents/test_fix_expediter/prompts/fix.py` — Coder/Tester system prompts + all `build_*_prompt` functions
- `_delegate_to_coder`, `_verify_fix`, `_build_tfe_coder_options`, `_build_tfe_tester_options`, `_summarize_tool_use`, `_derive_budget_tier`, tier-budget INI keys, today's Coder-prompt-audit changes
- FixExecutor + TFE's registration in FIX_PROMPT_BUILDERS
- All existing TFE unit tests, smoke tests, E2E tests — expected to pass unchanged in the SDK-engine path

## Structured output contracts

### Phase 1 diagnosis (CC → orchestrator)

CC emits a single fenced block at end of its run:

````
```tfe-diagnosis
{
  "clusters": {
    "C1": {
      "root_cause": "...",
      "error_category": "code_bug|test_bug|fixture_bug|environment_bug",
      "confidence": 0.85,
      "affected_components": ["src/..."],
      "notes": "..."
    },
    "C2": {...}
  }
}
```
````

**Parser fallback**: if the block is missing/malformed, parse the conversation markdown via regex to recover at least root_cause + category. Degraded fields get safe defaults (`confidence=0.5`, `error_category="unknown"`). Phase 2's `_build_proposal_prompt` tolerates degraded inputs.

### Phase 3 verdict (CC → orchestrator)

````
```tfe-result
{
  "clusters": {
    "C1": {"verdict": "fixed|failed|unclear", "commit_sha": "...", "files": [...], "notes": "..."},
    "C2": {...}
  },
  "summary": "K/N fixed"
}
```
````

**Parser fallback**: `git log --oneline origin/main..HEAD` inside the worktree. Every successful fix has a commit; commits are ground truth. JSON is nice-to-have enrichment.

## Rollout steps (all but Step 0 are future sessions)

### Step 0 — Max-subscription smoke test (THIS SESSION)

`src/tests/smoke/test_claude_code_max_subscription.py` submits a trivial BOUNDED CC job and asserts `TaskResult.cost_usd == 0.0`. This is the blocking gate — if `cost_usd > 0`, the Max subscription path isn't active and the whole cost-reduction thesis is wrong; investigation pivots before any TFE-to-CC code.

### Step 1 — Dispatcher allowlist extension

`allowed_tools_override` keyword arg on `dispatch()`. Unit tests cover the old default path + the override path. Zero behavior change for existing callers.

### Step 2 — Phase 3 CC path

Implement `TFE_to_CC_Orchestrator.run_phase3_fix_via_cc()` + `bundle_phase3.py` + verdict parser. Wire the `phase 3 engine` INI fork into `TFEOrchestrator.run_phase3_fix()`. Default stays `sdk`.

### Step 3 — First A/B run (with user approval)

Against the same `tfe-72adc928`-derived 11-proposal set:
- **A**: `tfe-a1c6e15a` (historical, pre-audit, flat 20 turns)
- **B**: current post-prompt-audit run (50/80/150 tiers, new prompt) — landing soon
- **C**: `phase_3_engine=claude_code` run

Compare: fix-landing rate (X/11), wall-clock duration, total cost, operator-touch points.

### Step 4 — Phase 1 CC path (after Step 3 signals work)

`run_phase1_diagnose_via_cc()` + `bundle_phase1.py` + diagnosis parser. Wire `phase 1 engine` fork. Diagnosis-only A/B.

### Step 5 — Operational choice (permanent)

Operator sets engine per run via INI or per-job override. Both paths remain tested and maintained. No retirement.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| OAuth credential expires mid-run | Extend `preflight-test-container.sh` with probe: `docker exec lupin-rest-test claude api user --jq .login`. Warns before TFE dispatches. |
| Max 200 cap (200 msgs / 3h) exhausted by concurrent TFE-CC + interactive Claude Code use | 2 msgs per TFE run. Telemetry warning at >50 TFE-CC runs per 3h. Low risk today. |
| Dispatcher allowlist extension regresses other callers | `allowed_tools_override` is keyword-only + default=None. Existing tests stay green. |
| Structured JSON output from CC is unreliable | Fallback parsers for both Phase 1 (markdown regex recovery) and Phase 3 (git log). Degraded confidence, not a crashed run. |
| CC model mismatch (operator's CC configured for Opus, TFE was Sonnet) | Explicit `--model sonnet` flag on the CC invocation. Prevents surprise Opus billing. |
| TFE-CC Max share interferes with user's interactive Claude Code | 2 msgs per TFE run × infrequent runs = negligible. Add TODO to measure sustained usage. |
| CC CLI version drift breaks subprocess contract | Pin Claude CLI install version in Dockerfile. Preflight smoke test catches drift. |
| Partial-success handling (some CC fixes succeed, some fail) | CC commits per-fix in worktree. Phase 5 reads `git log` — ground truth. Matches today's design. |
| No per-turn cost telemetry on CC path | Expected. Track wall-clock + turns as proxy. `cost_usd=0` is the success signal. |
| User wants to switch back to SDK mid-session | Flip INI key, restart container. Both paths stay tested and supported. Zero migration cost. |
| Phase 1 CC diagnoses don't map to TestDiagnosisResult expected by Phase 2 | Adapter in `TFE_to_CC_Orchestrator` converts CC JSON → TestDiagnosisResult. Single translation layer. |

## Verification

### Smoke test (blocking gate for everything else)

`src/tests/smoke/test_claude_code_max_subscription.py`:
1. Authenticates via the existing LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* path
2. `POST /api/claude-code/queue/submit` with a trivial prompt (`write "hello from TFE-to-CC smoke test" to /tmp/cc-smoke-<pid>.txt`)
3. Polls job terminal state
4. Asserts: exit code 0, `TaskResult.cost_usd == 0.0`, file exists with expected contents
5. Cleans up the temp file

### Unit tests (future sessions)

- `test_tfe_to_cc_bundle_phase1_prompt.py` — clusters in, well-formed markdown prompt out
- `test_tfe_to_cc_bundle_phase3_prompt.py` — proposals in, well-formed markdown prompt out
- `test_tfe_to_cc_diagnosis_parser.py` — structured JSON parse + markdown fallback
- `test_tfe_to_cc_verdict_parser.py` — structured JSON parse + git log fallback
- `test_tfe_to_cc_engine_fork_wiring.py` — orchestrator forks to right engine based on INI

### Integration A/B (future, with user approval)

Four data points on the same `tfe-72adc928`-derived 11-proposal baseline:
- **A**: `tfe-a1c6e15a` (historical, SDK engine)
- **B**: current run (SDK engine, post-audit prompts, 50/80/150 tiers)
- **C**: Phase 3 engine = claude_code
- **D**: Phase 1 + Phase 3 both = claude_code

Metrics: fix-landing rate, wall-clock duration, total cost, operator-touch points.

## Non-goals for v1

- Not migrating Phases 0, 2, 5, 6 to CC — they work; moving costs more than the benefit.
- Not INTERACTIVE mode for TFE-to-CC — BOUNDED + MCP interactivity covers both phases. INTERACTIVE uses the SDK, which defeats the Max-subscription win.
- Not auto-flipping the INI default to `claude_code` — operator makes that call.
- Not replacing `cosa_interface` guardrails — `allowed_tools_override` is the surgical extension point.
- Not adding cost telemetry UI — Max subscription makes per-run cost uninformative for CC.
- **Not deleting any SDK code** — explicit user direction. SDK engine is a peer, not a legacy.

## Related

- `~/.claude/plans/let-s-start-a-new-structured-moonbeam.md` — plan file (source of this doc)
- `18-post-tfe-validation-cleanup.md` — prior TFE planning doc in this series
- `~/.claude/projects/.../memory/feedback_feature_flag_preserves_old_path.md` — captured principle driving the "no deletion" stance
- `~/.claude/projects/.../memory/feedback_naming_underscore_not_abbreviations.md` — `TFE_to_CC_*` naming convention
- `src/cosa/agents/claude_code/job.py` + `src/cosa/orchestration/claude_code/dispatcher.py` — existing ClaudeCodeJob infrastructure we're reusing

## Execution log (will grow as future sessions land work)

### 2026-04-19 — Session be57a252 — Design doc filed (this session)
- Plan serialized to `~/.claude/plans/let-s-start-a-new-structured-moonbeam.md`
- Design doc filed here (`19-tfe-to-cc-design.md`)
- Max-subscription smoke test at `src/tests/smoke/test_claude_code_max_subscription.py` (Step 0) — pairs with this doc
- Two memories captured: naming-underscore-not-abbreviations, feature-flag-preserves-old-path
- Zero CoSA code changes this session
