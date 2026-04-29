# 07 — Final Execution Plan (Findings A → 14 Smokes → Finding B)

**Status**: Phases 1 + 2 complete (Lupin + CoSA edits, no commits). Phase 3 not yet started.
**Author session**: ba7138c4 (continuation), execution session d34f2f74
**Last update**: 2026-04-29
**Read-on-resume**: Yes — this is the canonical "what to do next" doc post-RUN 2. Pair with `90-execution-log.md` for per-cluster findings + diffs.

## Phase status

| Phase | Status | Detail |
|---|---|---|
| 0 | ✅ Done (this doc itself) | — |
| 1 | ✅ Edits landed | OOS-1A typo fix in TFE `job.py` + adjacent defensive-programming cleanup. Awaiting CoSA-context commit. |
| 2 | ✅ All 14 smoke FAILs resolved | See `90-execution-log.md` Phase 2 section. Mix of CoSA + Lupin edits. Awaiting commits in both contexts. |
| 3 | ⏸️ Not started | OOS-1B INI proposal-cap. Pending user buy-in. |

---

## Context — where we are after RUN 2 (ts-9f9ffed0)

RUN 2 landed clean at 2026-04-28 22:39 EDT (70 min). Per-suite:

| Suite | Result | P | F | E | S |
|---|---|---|---|---|---|
| unit | ✅ | 3748 | 0 | 0 | 1 |
| smoke | ❌ | 130 | **14** | 0 | 8 |
| websocket | ✅ | 50 | 0 | 0 | 0 |
| integration | ✅ | 252 | 0 | 0 | 44 |
| e2e | ✅ | 368 | 0 | **0** | 0 |

**Resolved**:
- ✅ All 12 e2e visual ERRORs cleared (RUN 1's `--update-snapshots -k visual` worked)
- ✅ CalculatorAgent codeless-replay fix verified (calc smoke flipped FAIL→PASS — the lone disappeared FAIL between baseline and RUN 2)
- ✅ Bucket 3 (CoSA submodule + parent commits) committed overnight by user

**Remaining**:
- 14 surviving smoke FAILs (real agent failures — see Phase 2)
- OOS-1 Finding A typo (1-line, ratification-ready)
- OOS-1 Finding B proposal-cap INI key

---

## Plan structure

| Phase | Title | Effort | Gates |
|---|---|---|---|
| 0 | Doc serialization | This doc itself | — |
| 1 | OOS-1 Finding A typo fix | XS (1 line) | Per-action commit auth |
| 2 | 14 surviving smoke FAIL triage + fixes | M-L (per-fix) | Per-fix triage gate; per-commit auth |
| 3 | OOS-1 Finding B proposal-cap INI key | S | Per-action commit auth |

---

## Phase 0 — Doc serialization (THIS doc)

This document is the plan artifact. Per `feedback_skip_rnd_doc_for_trivial_fixes`, Phase 1 (1-line typo) does not require its own R&D doc. Phase 2 sub-investigations may produce inline diagnostic notes here or in `90-execution-log.md`. Phase 3 (Finding B) is a small config + prompt template change documented inline below.

---

## Phase 1 — OOS-1 Finding A (one-line typo)

**File**: `src/cosa/agents/test_fix_expediter/job.py:549`
**Repo**: CoSA submodule (edits OK, git ops in separate cosa-context per `feedback_lupin_only_never_cosa`)

### Current

```python
count = getattr( c, "failure_count", len( getattr( c, "failures", [] ) or [] ) )
```

### Target

```python
count = len( getattr( c, "failure_indices", [] ) or [] )
```

### Rationale

`FailureCluster` exposes `failure_indices`, not `failures`. The existing line falls back to a non-existent attribute and reports cluster size 0 in the TFE final report. The 22:35 TFE clustered correctly — the report just lied.

### Steps

1. Edit `job.py:549` (CoSA edit OK from parent context).
2. `python -c "import py_compile; py_compile.compile( 'src/cosa/agents/test_fix_expediter/job.py', doraise=True )"`.
3. Run a relevant unit test if one exists (search: `pytest src/tests/unit/ -v -k tfe -k cluster_count` or similar).
4. **Pause for user commit authorization** (do NOT auto-commit per `feedback_never_auto_commit_push`).

### Acceptance

- `py_compile` clean.
- Any unit test that touches `_build_final_report` or cluster-size rendering passes.
- User authorizes commit; commit message: `Bug Fix: TFE cluster count uses failure_indices, not failures (OOS-1A)`.

---

## Phase 2 — 14 surviving smoke FAIL triage + fixes

The 14 fails group into **9 distinct issue clusters**:

| # | Cluster | Tests | Initial hypothesis | Confidence | Likely venue |
|---|---|---|---|---|---|
| 2.1 | LoRA env update × 3 | `test_prefers_8bit_over_4bit`, `test_update_lora_env_writes_file`, `test_update_preserves_other_models` | WG-4 fixed collection-time peft import error; tests now run and fail at runtime for a separate reason (file write path? env-var precedence? assertion drift?) | M | :7999 (no state mutation, fast) |
| 2.2 | Deep Research × 2 | `test_dry_run_smoke`, `test_deep_research_submit` | DR pipeline failing — could be API rate-limit, prompt drift, schema mismatch | L | :7999 (dry_run); :8000 (submit if hits real LLM) |
| 2.3 | BFE Phase 6 repair loop | `test_bfe_phase6_repair_loop_smoke` | Real BFE pipeline issue | L | :7999 if dry; else :8000 |
| 2.4 | Notification proxy script matching | `test_notification_proxy_script_matching` | OOS-3 Survivor 1: deep-research.json schema drift OR matcher confidence threshold | M | :7999 |
| 2.5 | Podcast generator dry run | `test_podcast_generator_dry_run_smoke` | Dry-run pipeline issue | L | :7999 |
| 2.6 | Presentation × 3 | `test_presentation_live_endpoint`, `test_presentation_render_only`, `test_research_to_presentation_live` | Likely shared root cause across 3 presentation tests | L | mix — render-only :7999, live ones :8000 |
| 2.7 | SWE team proxy | `test_swe_team_proxy` | Bare assert F, no detail | L | :7999 |
| 2.8 | Test suite live pipeline | `test_test_suite_live_pipeline` | Real test_suite live pipeline issue | L | :8000 (mutates queue) |
| 2.9 | TFE error capture | `test_tfe_error_capture_smoke` | OOS-3 Survivor 2: persistence allowlist drift OR DB migration gap | M | :7999 |

### Phase 2 protocol (per cluster)

For each of 2.1-2.9, repeat the loop:

1. **Capture evidence**: pull the full traceback for that test from `/var/lupin/io/test-suite/2026.04.28-at-22:39-EDT-all-results.md` (in container).
2. **Triage**: read the test source, the implicated production code, and the test's `quick_smoke_test()` if applicable. Decide one of:
   - **FIX**: clear root cause + small fix → make the edit, verify locally.
   - **DEFER**: structural issue beyond the scope of this session → document in `90-execution-log.md` and create a follow-up ticket entry in `TODO.md`.
3. **Verify**:
   - :7999-eligible (no state mutation, ≤2 min): `pytest src/tests/smoke/<test_file>.py::<test_name> -v` against :7999.
   - :8000-required (state mutation OR >2 min): defer to Phase 4 batch verification (below).
4. **Commit gate**: pause for user commit authorization per cluster (or batched across clusters at user discretion).

### Phase 2 batch verification (Phase 2 final step)

After all FIX clusters land:

- Schedule a smoke-only re-run on :8000: `POST /api/test-suite/submit { "test_types": "smoke", "auto_fix_on_failure": false, "scheduled_at": <user-confirmed slot> }`.
- Compare delta against RUN 2 baseline (130 P / 14 F / 0 E / 8 S).
- Acceptance: each FIX cluster's tests flip from FAIL to PASS; no new regressions.

### Acceptance for Phase 2

- Every FIX cluster's tests pass on :8000 verification.
- Every DEFER cluster has a documented follow-up entry in `TODO.md` and `90-execution-log.md`.
- No regressions in unit/websocket/integration/e2e suites (verified by smoke-only re-run not regressing those tiers — but a full-suite re-run is **not required** unless DEFER count is high).

---

## Phase 3 — OOS-1 Finding B (proposal-cap INI key)

**Files**:
- `src/conf/lupin-app.ini` — add new key
- `src/conf/lupin-app-splainer.ini` — add matching explanation
- `src/cosa/agents/test_fix_expediter/prompts/proposal.py:20` — template-substitute the cap

### Steps

1. **Add INI key** to `[Lupin: Baseline]` (or appropriate section):
   ```ini
   test fix expediter max proposals per cluster = 1
   ```
2. **Add splainer entry** in `lupin-app-splainer.ini`:
   ```ini
   test fix expediter max proposals per cluster = "Maximum number of fix proposals an LLM may generate per failure cluster. Lower values reduce proposal bloat (8 clusters × 3 proposals ≈ 24 proposals). Default 1 favours convergence."
   ```
3. **Update prompt template** in `prompts/proposal.py:20` — replace the hard-coded "1 to 3 alternative fixes" string with a template-substituted value pulled from config.
4. **Read config in TFE proposal-generation path** — use `cu.get_project_root()` + ConfigurationManager pattern.
5. `py_compile` on `proposal.py` and any TFE caller files touched.
6. Unit test: search for `test_tfe_proposal*` or write a smoke that verifies the cap.
7. **Pause for user commit authorization**.

### Acceptance

- INI + splainer entries present and aligned.
- Prompt template no longer hard-codes "1 to 3" — pulls from config.
- A unit or smoke test exercises the cap (mock orchestrator, assert proposals_per_cluster ≤ N).
- User authorizes commit; message: `Feature: TFE max proposals per cluster INI cap (OOS-1B)`.

---

## Outstanding work NOT in this plan

These are flagged as "you didn't ask but you should know":

1. **OOS-4 Finding C**: 4 non-canonical dead-queue write paths (`running_fifo_queue.py:314,378,1202,1263`) bypass `_transition_to_dead`. Refactor to canonical. **M effort**. Doc: `03-oos-4-test-suite-in-dead-anomaly.md`.
2. **OOS-4 Finding D**: `integration-e2e-remediation.json` systematically writes empty `failures[]` since 2026-04-24. Container-side localization needed. **S investigation, M-L fix**. Doc: `03-oos-4-...`.
3. **Consumer-stalls-after-test-suite-job pattern** (newly observed this session): `RunningFifoQueue` consumer thread heartbeat goes stale after every test-suite job completes. Both RUN 1 (60s job) and RUN 2 (70 min job) left consumer stalled. Workaround: bounce :8000. Real fix unknown — likely a heartbeat-write path issue specific to the test_suite agent's completion flow. **S investigation, S-M fix**. Recommend filing a fresh OOS doc once Phases 1-3 land.
4. **`feedback_never_grab_gpu` memory addendum** flagged in `06-resume-from-here.md` is OBSOLETE — session c7333045 added the EmbeddingProvider routing invariant which makes `SolutionSnapshot.__init__()` GPU-safe outside FastAPI. No memory edit needed.

---

## Cross-cutting rules in force

- **Git ops gating** per `feedback_never_auto_commit_push`: every commit needs explicit per-action user yes; one yes does NOT cover the next change.
- **CoSA scope** per `feedback_cosa_edit_vs_manage_git` + `feedback_lupin_only_never_cosa`: edit CoSA files freely from parent context; never run git in `src/cosa/`. CoSA commits happen in a separate cosa-context session.
- **Testing venues** per CLAUDE.md §TESTING VENUES: :7999 for non-mutating ≤2 min; :8000 for everything else, scheduled via `/api/test-suite/submit` with user-confirmed slot.
- **Memory check before recommendation** per CLAUDE.md memory protocol: verify any file/symbol referenced from memory still exists before acting on it.

---

## Resume protocol (post-`/clear`)

If you've cleared context and come back:

1. **Read this file first** (`07-final-execution-plan.md`) — it supersedes `06-resume-from-here.md` for what to do next.
2. Run `git log -5 --oneline` on parent + `cd src/cosa && git log -5 --oneline` to confirm where Bucket 3 landed.
3. Check `TaskList` to see current phase progress.
4. If mid-phase, `git diff --stat` to see what's already in flight.
5. Check `:8000` health and `consumer_stalled` before any test scheduling — bounce if stalled.

---

## Related docs

| Doc | Role |
|---|---|
| `01-design.md` | Original 9-WG remediation plan |
| `03-oos-1-tfe-bfe-pattern-matcher.md` | Findings A + B context |
| `03-oos-3-survivor-deep-dive.md` | Phase 2 Survivors 1+2 hypotheses |
| `03-oos-4-test-suite-in-dead-anomaly.md` | OOS-4 Findings C+D |
| `06-resume-from-here.md` | Snapshot post-RUN 2 (now superseded by this doc for forward work) |
| `90-execution-log.md` | Per-WG execution log |
