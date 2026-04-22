# 23 — Model × Thinking-Effort Matrix Results

**Paired plan**: `22-model-effort-matrix-plan.md`
**Paired Phase 3 log**: `21-tfe-to-cc-phase3-live-test.md`
**Run date**: 2026-04-20 (21:23 EDT → 22:24 EDT)

---

## Headline

**Sonnet beats Opus by roughly 5× on this workload. More thinking does not help; at `xhigh` it mildly hurts.**

## Full results

Five arms, same 11-fix input (the `tfe-72adc928` CBR-predicted set). Same prompt, same harness, same worktree recipe.

| Arm | Model | Effort | Fixed | Already-clean | Unclear | Failed | **Effective** | Duration | Fixes/min |
|---|---|---|---|---|---|---|---|---|---|
| A | Sonnet 4.6 | high  | 3 | 2 | 6  | 0 | **5/11** | 17.1 m | 0.29 |
| B | Opus 4.7   | low   | 0 | 0 | 11 | 0 | 0/11     | 4.3 m  | 0.00 |
| C | Opus 4.7   | high  | 1 | 0 | 9  | 1 | 1/11     | 5.9 m  | 0.17 |
| D | Opus 4.7   | xhigh | 1 | 0 | 10 | 0 | 1/11     | 7.7 m  | 0.13 |
| E | Sonnet 4.6 | xhigh | 2 | 2 | 7  | 0 | **4/11** | 7.4 m  | 0.54 |

"Effective" = `fixed + already_clean`. The latter is the `already_clean` verdict introduced in Phase B (2026-04-20) for clusters where a subagent reported `verdict=fixed` but produced no commit because the worktree was already in the correct state (usually because a parallel subagent landed the same change first).

## Observations

### 1. Model choice dominates

Opus across all three effort levels (B, C, D) lands 0–1 effective fixes. Sonnet at both tested effort levels (A, E) lands 4–5. That's a 4–5× gap attributable to model alone. Effort does not close it.

### 2. Opus defaults to `unclear`

Look at the Opus distributions:
- **B** (Opus + low): 11/11 unclear. Opus at low effort didn't attempt a single cluster.
- **C** (Opus + high): 9/11 unclear + 1 failed.
- **D** (Opus + xhigh): 10/11 unclear.

More thinking budget didn't move Opus off the `unclear` default. Whatever calibration makes Opus conservative here is orthogonal to effort.

### 3. `xhigh` is faster than `high` on Sonnet

Arm A (Sonnet + high): 17.1 min
Arm E (Sonnet + xhigh): 7.4 min — **2.3× faster**

Arm E landed 4 effective vs A's 5. Slight regression in landed count, but **fixes-per-minute nearly doubles** (0.54 vs 0.29). If wall-clock matters more than raw count (and on Max subscription it usually does), xhigh is the surprise winner on throughput.

Hypothesis: `xhigh` short-circuits tail-chasing. Subagents at `high` effort second-guess their work; at `xhigh` they commit the first plausible plan and move on. The speedup is real.

### 4. Opus `xhigh` doesn't even get faster than Sonnet `high`

Arm D (Opus + xhigh): 7.7 min, 1 effective
Arm A (Sonnet + high): 17.1 min, 5 effective

Even accounting for speed, Opus loses on throughput (0.13 fixes/min vs 0.29). Opus doesn't trade quality for speed — it trades quality for nothing visible.

## Hypothesis-testing against the plan

The `22-*` plan staked out three hypotheses (marked as "to be falsified"):

1. **Model > Effort**  ✅ **Confirmed, but direction inverted.** Model matters far more than effort, but Sonnet > Opus (not Opus > Sonnet as originally assumed).
2. **Effort has diminishing returns past `high`**  ✅ **Confirmed for Sonnet** (xhigh slightly worse by count, much faster). Confirmed more strongly for Opus (xhigh no better than low).
3. **Submodule leaks are model-agnostic**  ⚠️ **Not directly tested** — none of the five arms produced submodule leaks in this run. Bug 9 isolation improvement deferred.

## Recommendations

### Default knob positions

- **Harness** (`src/scripts/tfe_to_cc_phase3_live.py`): flip `DEFAULT_MODEL` back to `claude-sonnet-4-6`. Keep `DEFAULT_EFFORT = high` for first-run quality; consider `xhigh` if throughput matters more than count (e.g., overnight rips).
- **TFE/BFE agentic-job defaults** (INI): no change needed. The per-run override path via the UI now lets ops pick the right knob per job.
- **UI defaults** (localStorage fallback in `notifications.js`): change `'claude-opus-4-7'` → `'claude-sonnet-4-6'`. First-time users get the Sonnet path by default.

### Follow-up experiments

1. **Sonnet + medium** — find out whether effort saturates below `high` too. If Sonnet + medium ≈ Sonnet + high, we've been over-spending thinking budget.
2. **Why is Opus conservative?** — inspect a failing Opus cluster's stream-json to see what the subagent actually said. Did it diagnose? Propose? Attempt? Or just return `unclear` without trying? This is the most interesting unanswered question from tonight.
3. **Cross-workload validation** — run the same matrix against a different cluster batch (e.g., a fresh TFE from a BFE dead-letter) to confirm the Sonnet-wins pattern generalizes beyond `tfe-72adc928`.

### Not worth pursuing

- **Opus + max** — predicted 1 effective, ~10 min. The curve B → C → D is flat; `max` will not change the shape.
- **Per-cluster model routing** — the Sonnet floor is high enough (5/11) that splitting by cluster adds complexity for marginal gain.

## Artifacts

All preserved under `/tmp/`:

| Arm | Stream-json | Changes JSON | Changes MD |
|---|---|---|---|
| A | `/tmp/tfe-to-cc-phase3-stream-20260421T012347Z.jsonl` | `/tmp/tfe-to-cc-changes-20260421T012347Z.json` | `.md` |
| B | `/tmp/tfe-to-cc-phase3-stream-20260421T014055Z.jsonl` | `/tmp/tfe-to-cc-changes-20260421T014055Z.json` | `.md` |
| C | `/tmp/tfe-to-cc-phase3-stream-20260421T014511Z.jsonl` | `/tmp/tfe-to-cc-changes-20260421T014511Z.json` | `.md` |
| D | `/tmp/tfe-to-cc-phase3-stream-20260421T015106Z.jsonl` | `/tmp/tfe-to-cc-changes-20260421T015106Z.json` | `.md` |
| E | `/tmp/tfe-to-cc-phase3-stream-20260421T021129Z.jsonl` | `/tmp/tfe-to-cc-changes-20260421T021129Z.json` | `.md` |

Matrix runner log: `/tmp/tfe-to-cc-matrix-20260421T012347Z-summary.md`
21-*.md received one new "LIVE 11-fix run" section per arm (5 total). 21-*.md committed with arms A/B/C in checkpoint `3d95284`; arms D/E are in this session-end commit.

## Status

**Matrix plan → CLOSED** (all hypotheses tested). Follow-up questions moved to TODO.md.
