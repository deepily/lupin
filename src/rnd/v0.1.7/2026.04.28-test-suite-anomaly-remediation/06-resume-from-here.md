# 06 — Resume From Here (Context-Clear Recovery)

**Status**: Active session bookmark
**Last update**: 2026-04-28 19:35 EDT (post ts-976bdc44 verification + OOS-4 hotfix + CalculatorAgent codeless replay fix)
**Read this first** if you've cleared context and want to pick up where Session ba7138c4 left off.

---

## TL;DR — what state are we in?

The 2026-04-27 22:35 EDT incident's root causes are largely addressed. **Wins**: WG-1 docker fonts (image rebuilt + retagged), WG-2 skip discipline, WG-3 GPU-test deletion, WG-4 peft guard, WG-5 lxml dep, WG-7 websocket parser, WG-8b heartbeat, WG-9 TFE policy, OOS-4 hotfix Parts A+B (mis-attribution + empty-error), and the **CalculatorAgent codeless-replay fix** (user's intuition: "the agent isn't broken; the playback is" — confirmed correct).

**Two verification re-runs on `:8000` performed today**:
- `ts-1c41e064` (18:05 EDT) — died at 7 min from the OOS-4 mis-attribution bug (now fixed).
- `ts-976bdc44` (post-fix, 18:05 EDT) — completed cleanly in 75 min: **4524 P / 15 F / 12 E / 54 S**. test_suite_job survived 5 calc dead-letters with proper error fields.

**What still needs work** (priority order):
1. 12 e2e visual ERRORs persist (container chromium ≠ host chromium even with same fonts → need container-side baseline regen)
2. 13 smoke FAILs that are real agent failures (need OOS-3 trigger + per-test triage; calc smoke specifically should now PASS with the codeless-replay fix in place — needs re-run to confirm)
3. CoSA submodule commit (this session's CoSA edits + prior c4e5d4f's 6 CoSA edits)
4. Push parent commits (`bb9298c` + this checkpoint)

---

## Key references

| Doc | Purpose |
|-----|---------|
| `01-design.md` | Original consolidated remediation plan (9 working groups + 4 OOS proposals) |
| `02-wg-{1..9}-*.md` | Per-WG design docs (status: all WGs landed in some form) |
| `03-oos-{1..4}-*.md` | OOS proposals with prewarm findings folded in |
| `04-execution-orchestration.md` | The 4-phase A→B→C→D plan with role assignments |
| `05-voice-gate-policy-evolution.md` | WG-9 forward-compat design (UPE delegate ~2 dev branches out) |
| `06-resume-from-here.md` | THIS file — context-clear recovery |
| `90-execution-log.md` | Per-WG execution log (timestamped) |

---

## What's committed vs. uncommitted

### Parent Lupin repo

- **Committed** (`bb9298c` from earlier today): WG-1 Dockerfile fonts, WG-5 pyproject.toml lxml, WG-7 splainer notes, WG-8b INI keys, WG-9 INI keys + splainer, R&D doc skeletons, deletion of 2 GPU-touching smoke tests, 3 new unit tests (TFE voice gate, websocket parser, consumer heartbeat), tracking docs.
- **Pending** (this checkpoint): updated R&D docs with prewarm findings (`03-oos-{1,2,4}-*.md`), new R&D docs (`04-execution-orchestration.md`, `05-voice-gate-policy-evolution.md`, this file), `pyproject.toml` (pydantic-ai `[slim]` removed), `uv.lock` (regenerated), `docker-compose.yml` (test container parity bind mounts), `src/conf/lupin-app-splainer.ini` (delegate-mode reservation note), `src/scripts/seed_test_companions.py` (CC_LISTENER_LUPIN added), new unit test `test_solution_snapshot_codeless_replay.py`, history.md + TODO.md + .claude-session.md updates.

### CoSA submodule (separate cosa-context commit needed; `feedback_lupin_only_never_cosa`)

This session's CoSA edits:
- `src/cosa/rest/running_fifo_queue.py` (OOS-4 hotfix Parts A + B at line 276, 294)
- `src/cosa/memory/solution_snapshot.py` (CalculatorAgent codeless replay fix in run_code())
- `src/cosa/agents/test_fix_expediter/orchestrator.py` (`_delegate_to_predictor()` stub for future UPE)

Prior session (c4e5d4f) CoSA edits (still uncommitted in submodule):
- `src/cosa/training/peft_trainer.py` (peft import guard)
- `src/cosa/agents/test_fix_expediter/config.py` (WG-9 fields + key map)
- `src/cosa/agents/test_fix_expediter/orchestrator.py` (WG-9 timeout-policy branch)
- `src/cosa/agents/test_suite/job.py` (WG-7 `_parse_non_pytest_stdout`)
- `src/cosa/rest/queue_consumer.py` (WG-8b heartbeat write)
- (Plus today's running_fifo_queue.py + solution_snapshot.py edits)

**Total CoSA pending**: 7 files. Separate cosa-context session needed.

---

## Test-suite verification matrix (ts-976bdc44, post-fixes)

| Suite | 22:35 baseline | 19:19 result | Δ | Status |
|-------|---------------|--------------|---|--------|
| unit | 3672 P / 0 F / 0 E / 1 S | 3726 P / 0 F / 0 E / 1 S | +54 tests | ✅ |
| smoke | 131 P / 23 F / 7 E / 1 S | 129 P / 15 F / 0 E / 8 S | -8F -7E +7S | ⚠️ improved but 13 real fails remain |
| websocket | 0/0/0/0 (false-FAIL) | 50 P / 0 F / 0 E / 0 S | ✅ WG-7 nailed it | ✅ |
| integration | 251 P / 0 F / 0 E / 45 S | 251 P / 0 F / 0 E / 45 S | unchanged | ✅ |
| e2e | 368 P / 0 F / 12 E / 0 S | 368 P / 0 F / 12 E / 0 S | unchanged | ❌ visual ERRORs persist |

### The 12 persisting e2e ERRORs

All 12 are `test_visual_page[chromium-{login,register,change-password,profile,notifications,landing,admin-{dashboard,snapshots,users,ratify,trust},dev-tools}]` — every visual page diffs.

**Why they persist after fonts**: my host-side check (`./src/scripts/run-e2e-ui-tests.sh -v -k visual` against `:8000` from host) returned 13/13 PASS. That used HOST chromium. The `:8000` test_suite_job runs CONTAINER chromium. Same fonts in both, but the rendering output is subtly different (font hinting? GPU vs CPU rasterization? subpixel positioning?). Diff exceeds the 0.1 threshold.

**Fix path**: schedule a baseline regen run via `POST /api/test-suite/submit` with `pytest_args="--update-snapshots -k visual"` so baselines are generated INSIDE the test container. Then they'll match future container runs.

### The 13 surviving smoke FAILs

Real agent failures (not infra). Triage candidates:

| Test | Hypothesis | Confidence |
|------|-----------|------------|
| `test_calculator_live_pipeline` | Was failing due to codeless-replay bug; should now PASS post-fix | HIGH (re-run to confirm) |
| `test_lora_env_update_smoke × 3` | WG-4 fixed collection-time error; tests now run and fail at runtime for different reason | NEED INVESTIGATION |
| `test_bfe_phase6_repair_loop_smoke` | Real BFE pipeline issue | LOW (need stack) |
| `test_deep_research_dry_run_smoke`, `test_deep_research_submit_smoke` | Real DR pipeline issues | LOW (need stack) |
| `test_podcast_generator_dry_run_smoke` | Real podcast issue | LOW (need stack) |
| `test_presentation_live_smoke`, `test_presentation_render_only_smoke`, `test_research_to_presentation_live_smoke` | Real presentation issues (3 related) | LOW (need stack) |
| `test_swe_team_proxy` | Real SWE team test | LOW (need stack) |
| `test_test_suite_live_pipeline` | Real test_suite live test | LOW (need stack) |
| `test_notification_proxy_script_matching` (WG-6 survivor) | Likely script-content drift | OOS-3 |
| `test_tfe_error_capture_smoke` (WG-6 survivor) | Likely persistence/store issue | OOS-3 |

---

## Outstanding fixes that didn't ratify yet

### OOS-1 Finding A (one-line typo, ratification-ready)

**File**: `src/cosa/agents/test_fix_expediter/job.py:549`

```python
# CURRENT — broken:
count = getattr( c, "failure_count", len( getattr( c, "failures", [] ) or [] ) )

# FIX:
count = len( getattr( c, "failure_indices", [] ) or [] )
```

`FailureCluster` has `failure_indices`, not `failures`. The 22:35 TFE clustered correctly — the report just lied about cluster sizes. Trivial. Standalone hotfix candidate.

### OOS-1 Finding B (proposal-cap INI key)

`prompts/proposal.py:20` asks LLM for "1 to 3 alternative fixes" per cluster. 8 clusters × 3 ≈ 23-24 proposals (the bloat we saw). Recommendation: add INI key `test fix expediter max proposals per cluster = 1` and template-substitute it into the prompt.

### OOS-4 Findings C+D (architectural + integration-e2e regression)

Findings A+B already landed under hotfix authorization. Remaining:
- **Finding C**: 4 non-canonical dead-queue write paths (lines 314, 378, 1202, 1263) bypass `_transition_to_dead`. Refactor to canonical. M effort.
- **Finding D**: `integration-e2e-remediation.json` systematically writes empty `failures[]` since 2026-04-24. Container-side `docker exec lupin-rest-test ls /tmp/integration-junit-*.xml` to localize.

---

## Memory update needed (one rule expansion)

`feedback_never_grab_gpu.md` already has the "tests must be DELETED, not guarded" corollary from earlier today. Should additionally note:

> **`SolutionSnapshot.__init__()` loads ~1 GB of embedding models onto cuda:0** (nomic-embed-text-v1.5 + CodeRankEmbed). Tests of SolutionSnapshot methods MUST use `SolutionSnapshot.__new__(SolutionSnapshot)` + direct attribute set, NOT the constructor. The first draft of `test_solution_snapshot_codeless_replay.py` triggered GPU load; caught and rewrote.

---

## Next-session entry plan

If you `/clear` and come back:

1. **Read this file first** (`06-resume-from-here.md`).
2. Skim `01-design.md` for the original WG/OOS structure.
3. Check `git log` for the most recent parent commit + `git status` for any uncommitted state.
4. Confirm `:8000` queue is empty before any test scheduling.
5. **If you want to schedule the next verification re-run** (e.g., to confirm the calc codeless-replay fix worked end-to-end + visual-baseline regen):
   ```python
   # First: regen visual baselines container-side
   POST /api/test-suite/submit {
       "test_types": "e2e",
       "pytest_args": "--update-snapshots -k visual",
       "scheduled_at": <slot>
   }
   # Then: full all-suite verification
   POST /api/test-suite/submit {
       "test_types": "all",
       "auto_fix_on_failure": false,
       "scheduled_at": <slot>
   }
   ```
6. **If ratifying OOS plans**: read `03-oos-{1,2,3,4}-*.md`. OOS-1 Finding A is the cheapest hotfix; OOS-3 is gated on B-phase results (now confirmed needed).
7. **For any CoSA work**: cd into `src/cosa/` and use a separate session per `feedback_lupin_only_never_cosa`.

---

## Critical context (don't lose)

- **`:7999` is dev** (auto-reload), **`:8000` is test** (no reload, restart needed for code changes).
- **`:8000` is monopolize-mode**: never side-door inject; use `/api/test-suite/submit` with `scheduled_at`. Per `feedback_test_server_monopolize_mode`.
- **CoSA is a submodule**: edit freely, never `git` from parent context. Per `feedback_cosa_edit_vs_manage_git` + `feedback_lupin_only_never_cosa`.
- **No GPU touching in tests**: per `feedback_never_grab_gpu`. SolutionSnapshot constructor is a known offender; bypass with `__new__()`.
- **No auto-commit/push**: per `feedback_never_auto_commit_push`. Always wait for explicit per-action authorization.
- **No auto-promotion of build tags**: per `feedback_no_auto_promote_tags`. Park rebuilds at candidate tags; user retags.
- **Phase 0 doc serialization is mandatory**: per `feedback_phase0_serialization_prominence`. Every non-trivial plan creates R&D doc stubs FIRST.

---

## Where to find more

- The full session narrative: `history.md` Session ba7138c4 entry (2 checkpoint sub-sections).
- The pending-action TODO: `TODO.md` "Session ba7138c4 follow-on" block.
- The session manifest: `.claude-session.md` Session: ba7138c4 section.
- The plan-file artifact (Claude planning system): `~/.claude/plans/floating-greeting-bentley.md`.

If something seems out of date, trust `git log` over any of these docs — they reflect intent at write time.
