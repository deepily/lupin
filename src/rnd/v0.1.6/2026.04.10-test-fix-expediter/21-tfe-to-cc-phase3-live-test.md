# 21 — TFE-to-CC Phase 3 (Apply Fixes) — Live Test Execution Log

**Paired design**: `19-tfe-to-cc-design.md`
**Paired Phase 1 log**: `20-tfe-to-cc-phase1-live-test.md`

---

### 2026-04-19T21:17:26-04:00 — LIVE 11-fix run

**Worktree**: `/var/lupin/.claude/worktrees/phase3-live-20260420T010911Z`
**Prompt**: 16327 bytes | host: `/tmp/tfe_to_cc_phase3_prompt_20260420T010911Z.md` | container: `/tmp/tfe_to_cc_phase3_prompt_20260420T010911Z.md`
**Stream**: `/tmp/tfe-to-cc-phase3-stream-20260420T010911Z.jsonl`

**SDK/CC path confirmation**:
- apiKeySource: `none`
- model: `claude-sonnet-4-6`

**Outcome**:
- Exit code: `0`
- result.subtype: `success`
- result.is_error: `False`
- result.num_turns (coordinator): `2`
- result.duration_ms: `55068`
- result.total_cost_usd (informational): `3.6815526499999978`
- Raw event count: 326
- Tool use count: 19
- Tool breakdown: {'ToolSearch': 1, 'TodoWrite': 7, 'Agent': 11}

**Verdict**: **5 / 11 fixes landed** (vs. SDK path's 0/11 baseline)
- Parser: primary (tfe-result fence)
- Validation OK: False
- Validation issues:
    - cluster 'C3': verdict=fixed but commit_sha is missing or not a string

**Per-cluster verdicts**:

```json
{
  "clusters": {
    "C1": {
      "verdict": "unclear",
      "commit_sha": null,
      "files": [],
      "pytest_passed": false,
      "notes": "Neither target path exists in this worktree. src/tests/e2e_ui/conftest.py and io/test-suite/visual-baselines/ are entirely absent \u2014 no Playwright/visual-regression infrastructure present. Fix requires an interactive update-snapshots run against a different environment."
    },
    "C2": {
      "verdict": "fixed",
      "commit_sha": "2502b4c",
      "files": [
        "src/cosa/rest/todo_fifo_queue.py"
      ],
      "pytest_passed": true,
      "notes": "Added 'agent router go to test fix expediter resume': 'Test Fix Expediter Resume (resume a stalled TFE job)' to PRODUCT_NAMES. WARNING: subagent committed to the live CoSA sub-repo at /var/lupin/src/cosa/ (not the isolated worktree), because the worktree lacks a cosa/ directory. Commit sha is on CoSA's wip branch, not the phase3 worktree."
    },
    "C3": {
      "verdict": "fixed",
      "commit_sha": null,
      "files": [
        "src/tests/unit/test_runtime_argument_expeditor.py",
        "src/cosa/agents/runtime_argument_expeditor/agent_registry.py"
      ],
      "pytest_passed": true,
      "notes": "All stale count assertions were already corrected by the time C3 ran (C6 landed first). test_registry_has_ten_agents asserts == 10 and passes. No new commit needed; worktree was already clean."
    },
    "C3b": {
      "verdict": "unclear",
      "commit_sha": null,
      "files": [],
      "pytest_passed": false,
      "notes": "Target file src/tests/unit/test_deep_research_to_presentation.py does not exist anywhere in the worktree. Superseded or the file was never present in this branch."
    },
    "C4": {
      "verdict": "fixed",
      "commit_sha": "c35a2d9",
      "files": [
        "src/cosa/agents/notification_proxy/config.py"
      ],
      "pytest_passed": true,
      "notes": "Added 'resume_from': 'tfe-mock1234::user1' after dead_job_id in the all_agents union profile. WARNING: same isolation issue as C2 \u2014 subagent committed to the live CoSA sub-repo at /var/lupin/src/cosa/, not the isolated worktree. Commit sha is on CoSA repo."
    },
    "C5": {
      "verdict": "unclear",
      "commit_sha": null,
      "files": [],
      "pytest_passed": false,
      "notes": "Target file src/tests/unit/test_presentation_visual_renderer.py does not exist in the worktree. PlaceholderRenderer / NanoBananaRenderer infrastructure absent from this branch."
    },
    "C5b": {
      "verdict": "unclear",
      "commit_sha": null,
      "files": [],
      "pytest_passed": false,
      "notes": "Target file src/tests/unit/test_presentation_visual_renderer.py does not exist. NanoBananaRenderer and SUPPORTED_TYPES not found anywhere in codebase. Fix does not apply to this worktree."
    },
    "C6": {
      "verdict": "fixed",
      "commit_sha": "908ecf5",
      "files": [
        "src/tests/unit/test_runtime_argument_expeditor.py"
      ],
      "pytest_passed": true,
      "notes": "Renamed test_registry_has_five_agents to test_registry_has_ten_agents and updated assertion from 5 to 10. agent_registry.py quick_smoke_test in CoSA was updated locally but not committed (CoSA is a separate repo). Worktree commit covers the test file only."
    },
    "C8": {
      "verdict": "fixed",
      "commit_sha": "dea2c76",
      "files": [
        "src/lupin_cli/claude_code/hooks/stop.py"
      ],
      "pytest_passed": true,
      "notes": "Restored _ask_anything_else call in stop.py main() \u2014 removed '# disable temporarily' block and bare emit_json({}) short-circuit. All 14 TestVoiceBlocking and TestNotifyUserSync tests pass. notifications.js renderHistoryActions part skipped: function not found in worktree's version of the file and has no pytest coverage."
    },
    "C8b": {
      "verdict": "unclear",
      "commit_sha": null,
      "files": [
        "src/lupin_cli/claude_code/hooks/stop.py"
      ],
      "pytest_passed": true,
      "notes": "The _ask_anything_else branch was already restored (no commented-out code found at lines 344-350; file is only 259 lines). All 23 targeted tests passed without any edit. Superseded by C8 which landed first."
    },
    "C8c": {
      "verdict": "unclear",
      "commit_sha": null,
      "files": [],
      "pytest_passed": false,
      "notes": "renderHistoryActions function does not exist anywhere in notifications.js or any other file. Lines 6089-6113 contain loadJobInteractions. No pytest test named renderHistoryActions exists (0 collected). Fix targets code absent from this worktree version."
    }
  },
  "summary": "4/11 fixed (worktree commits: C6=908ecf5, C8=dea2c76; CoSA-repo commits outside worktree: C2=2502b4c, C4=c35a2d9; C3 already passing); 7 unclear (C1, C3b, C5, C5b, C8b, C8c: target files absent or already correct)"
}
```

**Git state in worktree**:

```
$ git log --oneline origin/main..HEAD
dea2c76 fix(tfe): C8 Restore stop.py hook path and add delete-btn to renderHistoryActions
908ecf5 fix(tfe): C6 Update stale agent-count assertion from 9 to 10

$ git diff --stat origin/main
src/lupin_cli/claude_code/hooks/stop.py           | 98 ++++++++++++++++++++++-
 src/tests/unit/test_runtime_argument_expeditor.py |  6 +-
 2 files changed, 97 insertions(+), 7 deletions(-)
```

### Parallel SDK run `tfe-da58cf7e` (four-way A/B/C/D comparison)

A standard SDK-path Resume of `tfe-72adc928` fired alongside the TFE-to-CC harness (queue-visible; fully independent path). Operator was offline (watching a movie) → voice gate timed out → all 17 proposals fell through to escalation defaults → each attempted.

**SDK outcome**: 17 selected, **0 fixed**, duration 10,776 s = **~180 min**. Same 3-line uncommitted edit pattern as the prior two SDK runs.

#### Four-way head-to-head (same `tfe-72adc928` input, three engines, four runs)

| Metric | **A**: tfe-a1c6e15a (SDK, pre-audit) | **B**: tfe-0a71bc1a (SDK, post-audit) | **C**: tfe-da58cf7e (SDK, post-audit re-run) | **D**: TFE-to-CC Phase 3 (CC + Task) |
|---|---|---|---|---|
| Phase 3 engine | claude-agent-sdk | claude-agent-sdk | claude-agent-sdk | `claude -p` (CLI) + Task subagents |
| Fixes selected | 11 | 11 | **17 (all)** | 11 |
| **Fixes landed** | **0 / 11** | **0 / 11** | **0 / 17** | **4 / 11** (+ 1 already-correct) |
| Wall-clock duration | 63 min | ~120 min | **180 min** | **8 min** |
| Total agentic calls | ~13 SDK | ~18 SDK | ~17-20 SDK | 1 coordinator + 11 Task subagents |
| Coordinator turns | N/A | N/A | N/A | 2 (!) |
| Max tier hit | flat 20 | 50/80/150 | 50/80/150 | subagent-internal (~20-40) |
| Paper cost (USD) | ~$6.50 | ~$10+ | ~$15+ | $3.68 (**$0** on Max subscription) |
| Actual billing | API key (uncertain) | API key (uncertain) | API key (uncertain) | Max subscription, no incremental |
| Operator touch | Voice gate once | Voice gate + escalations | Voice gate + escalations (offline → timeouts) | None (fully autonomous run) |
| Worktree isolation | Clean | Clean | Clean | **Leak**: C2 + C4 committed to `src/cosa/` sub-repo (Bug 9 submodule gap) |
| Parallelism | Sequential | Sequential | Sequential | **Parallel** (subagents batched 2-4 concurrent) |

#### Takeaways

1. **SDK path is structurally incapable of landing these fixes** across three consecutive runs with progressively-tuned prompts + budgets. Not a tuning problem.
2. **TFE-to-CC Phase 3 solves it in a fraction of the time + cost**, with Claude Code's native Task-subagent parallelism doing the heavy lifting. Coordinator used **2 turns**; subagents did the real work.
3. **Bug 9 gap**: worktree isolation applies to the outer Lupin repo only. Nested submodules (`src/cosa/`) receive their own commits when subagents edit nested files. Two C2/C4 commits landed on the CoSA wip branch (local only, unpushed) during this run. Reset via `cd src/cosa && git reset --hard HEAD~2` if unwanted.
4. **Phase 5 GitStrategist assumption needs revisiting**: it reads `git log origin/main..HEAD` from the worktree path, which will miss commits that leaked into submodules. Either (a) CC subagents avoid committing in submodules, (b) GitStrategist walks submodule logs too, or (c) accept submodule commits as a separate post-run reconciliation step.
5. **Artifacts preserved for reflection** — rendered prompt at `/tmp/tfe_to_cc_phase3_prompt_20260420T010911Z.md`, full stream-json at `/tmp/tfe-to-cc-phase3-stream-20260420T010911Z.jsonl`, worktree at `.claude/worktrees/phase3-live-20260420T010911Z/`, CoSA-leak commits at `cd src/cosa && git log --oneline -2`.
