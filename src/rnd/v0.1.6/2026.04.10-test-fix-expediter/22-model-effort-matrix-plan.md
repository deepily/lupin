# 22 — Model × Thinking-Effort Matrix Plan

**Paired design**: `19-tfe-to-cc-design.md`
**Paired Phase 3 log**: `21-tfe-to-cc-phase3-live-test.md`
**Harness entry**: `src/scripts/tfe_to_cc_phase3_live.py`

---

## Context

Phase 3 Run D (2026-04-20) demonstrated TFE-to-CC's ability to land real fixes (4/11 in 8 min) against the same cluster batch where three SDK-path runs all scored 0. Open question: how much of that win was the engine (CC + Task subagents), and how much is left on the table by choosing **Sonnet** as the harness model? This plan defines a clean A/B/C/D matrix to answer that.

**Motivating questions**:
1. Does Opus 4.7 land more fixes than Sonnet 4.6 on the same batch?
2. Does raising `--effort` (low → high → xhigh → max) pay off, or does tail-chasing risk dominate?
3. Where's the fixes-landed-per-minute sweet spot for "operator is offline, wake me if you need me"?

## Prerequisites (shipped in Session d8831785)

- [x] Harness accepts `--model` + `--effort` + `--max-budget-usd` (Phase A)
- [x] Each run emits a machine-parseable `tfe-to-cc-changes-{timestamp}.{json,md}` artifact (Phase B)
- [x] `TestFixExpediterJob` + `BugFixExpediterJob` accept `thinking_effort` param (Phase C)
- [x] Resume-from-checkpoint endpoint accepts overrides in request body (Phase D)
- [x] Done-queue UI surfaces Model + Effort dropdowns for TFE/BFE cards (Phase E)
- [x] Unit tests cover all of the above (Phase F)

## Design

### Arms

Hold everything else constant (prompt, cluster set, worktree recipe). Vary model + effort only.

| Arm | Harness invocation | Model | Effort | Purpose |
|---|---|---|---|---|
| **A** (baseline) | `python3 src/scripts/tfe_to_cc_phase3_live.py --model claude-sonnet-4-6 --effort high` | Sonnet 4.6 | high | Reproduces Run D as closely as possible (Run D was Sonnet, no explicit `--effort`). Anchor. |
| **B** | `--model claude-opus-4-7 --effort low` | Opus 4.7 | low | Cheapest Opus arm; tests whether model alone carries the win. |
| **C** | `--model claude-opus-4-7 --effort high` | Opus 4.7 | high | Balanced; expected sweet spot. |
| **D** | `--model claude-opus-4-7 --effort xhigh` | Opus 4.7 | xhigh | Aggressive thinking; checks for tail-chasing plateau. |

**Deferred** (only if B–D produce a clear monotonic curve and we want to see the ceiling):
| Arm | Invocation | Notes |
|---|---|---|
| E | `--model claude-opus-4-7 --effort max` | Maximum effort. Expected ≥90% of D's performance at higher cost. Skip if D already saturates. |

### Inputs

Same `SELECTED_FIXES` list the harness ships with today — the 11-fix CBR-predicted set from `tfe-72adc928`'s Phase 2 voice gate. Do not touch `src/scripts/tfe_to_cc_phase3_live.py` between runs.

### Measurement

For each arm, the harness emits `/tmp/tfe-to-cc-changes-{ts}.json`. Key fields to compare:

| Metric | Where in artifact | Direction |
|---|---|---|
| `overall.fixed` | top-level | ↑ better |
| `overall.already_clean` | top-level | ↑ neutral (no-op clusters) |
| `overall.unclear` + `.failed` | top-level | ↓ better |
| `duration_s` | top-level | ↓ better |
| `clusters[*].pytest_passed` | per-cluster | ↑ better |
| `possibly_leaked_to_submodules` | top-level | ↓ better (isolation signal) |

**Derived composite**: **fixes-landed-per-minute** = `overall.fixed / (duration_s / 60)` is the single headline metric. Secondary: **fixes-per-dollar** (once paper cost is meaningful — on Max subscription this is $0 for all arms).

### Tail-chasing proxy

From the stream-json: count of tool-use events where the coordinator or a subagent reads the same file it just edited within 3 turns (back-and-forth), or TodoWrite entries that transition `in_progress → pending` (backtracking). Higher at `max` effort → evidence of second-guessing.

Post-run, eyeball the full `.md` artifact for each arm side-by-side in `/tmp/`. Tables line up for quick visual diff.

## Execution

### Option 1 — CLI (recommended for the matrix experiment itself)

Sequential runs to keep container + MCP state clean. Estimated ~10 min per run on Max subscription + Docker test container.

```bash
# Prereq: lupin-rest-test container running; worktrees dir writable.

python3 src/scripts/tfe_to_cc_phase3_live.py --model claude-sonnet-4-6 --effort high    # Arm A
python3 src/scripts/tfe_to_cc_phase3_live.py --model claude-opus-4-7   --effort low     # Arm B
python3 src/scripts/tfe_to_cc_phase3_live.py --model claude-opus-4-7   --effort high    # Arm C
python3 src/scripts/tfe_to_cc_phase3_live.py --model claude-opus-4-7   --effort xhigh   # Arm D
```

Each run preserves its worktree + stream-json + changes artifacts in `/tmp/`. Do not clean between runs; the comparison needs all four artifact sets alongside each other.

### Option 2 — UI (for future one-off resumes of specific TFE/BFE jobs)

Go to Done queue → locate the stalled TFE/BFE job → select Model + Effort from the inline dropdowns next to Resume → click Resume. Overrides travel via the extended `/api/jobs/{id_hash}/resume-from-checkpoint` body (`lead_model_override`, `worker_model_override`, `thinking_effort`). localStorage remembers last choice.

This path isn't for the matrix (it resumes a single job, not the canned 11-fix batch) but ensures the same knobs are available in day-to-day ops.

## Expected read-out

Hypothesis ordering (no priors for this workload, so this is speculation to be falsified):

1. **Model > effort** — moving from Sonnet to Opus (A → C) delivers more than raising effort at fixed model (B → C → D).
2. **Effort has diminishing returns past `high`** — C ≈ D, with D maybe slightly better at the cost of ~2× wall-clock. `max` (arm E) probably isn't worth running.
3. **Submodule leaks are model-agnostic** — Bug 9 will hit all four arms equally until submodule hydration lands (Bug 9 is orthogonal to this matrix).

If the read-out inverts expectation (effort dominates, or Sonnet+xhigh matches Opus+low), that's a much more interesting result — likely flip default in the harness + surface louder defaults in the UI.

## Non-goals

- Changing the cluster batch. Use `tfe-72adc928` as-is so comparisons are apples-to-apples.
- Per-cluster model routing (Opus for hard, Sonnet for easy). Out of scope — would invalidate the batch comparison.
- SDK-path arms (the `tfe-a1c6e15a` / `tfe-0a71bc1a` / `tfe-da58cf7e` family). Those already scored 0/N × 3; re-running with different models won't change that — it's an engine problem, not a model problem.

## Verification

After each arm completes:
- Check `/tmp/tfe-to-cc-changes-{ts}.json` exists and `validation_ok` is `true`
- Spot-check one or two committed clusters against the worktree's `git log --oneline origin/main..HEAD`
- Confirm `possibly_leaked_to_submodules` matches your expectation (0 or a small known set)

After all four arms complete:
- Collect the four JSON artifacts; tabulate by the metrics above
- Write a short follow-up doc `23-model-effort-matrix-results.md` with the findings and recommendation for default knob positions

## Follow-ups triggered by this matrix

- If arm C or D wins by a comfortable margin, bump harness defaults accordingly.
- If the matrix reveals a tail-chasing inflection, document the threshold in the CoSA TFE/BFE config INI entries as the recommended baseline.
- Fold whatever default we land on into the Done-queue UI's pre-selected dropdown values (currently hardcoded `opus-4-7` / `high`).
