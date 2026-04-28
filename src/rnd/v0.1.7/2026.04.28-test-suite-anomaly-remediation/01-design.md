# 2026.04.28 — Test-Suite Anomaly Remediation (Design)

**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**Trigger**: 2026-04-27 22:35 EDT scheduled `:8000` test-suite run (`ts-90890bae`)
**Result of trigger**: 4422 P / 23 F / 19 E / 47 S; 1 orphan in `run`; 8 reaped Calculator jobs in `dead`; downstream TFE (`tfe-d9786eea`) stalled at `proposing` with `voice_gate_timeout`.

## Context

The test-suite run produced anomalies that cluster into 8 distinct root causes plus an orphan job stuck in the `run` queue. None are behavioral regressions of Lupin code — they are environment, harness, gating and image-rebuild gaps that have silently accumulated, plus one design gap (TFE has no fallback when its voice gate is unanswered after-hours).

This design doc captures the consolidated remediation plan. Each working group (WG-1 through WG-9) has a paired `02-wg-N-…md` design doc with full implementation detail, plus per-WG entries in `90-execution-log.md`.

## Working-group index

| WG | Theme | Failures covered | Doc |
|----|-------|------------------|-----|
| WG-1 | Docker image — restore Playwright fonts | 12 e2e visual ERRORs | `02-wg-1-docker-fonts.md` |
| WG-2 | Smoke-test prereq skip discipline | 7 ERRORs + ~9 FAILs | `02-wg-2-skip-discipline.md` |
| WG-3 | **BURN** GPU-touching tests | 6 FAILs (deleted) | `02-wg-3-burn-gpu-tests.md` |
| WG-4 | Optional `peft` import guard | 3 FAILs | `02-wg-4-peft-import-guard.md` |
| WG-5 | Optional `lxml` dep + audit | 1 FAIL | `02-wg-5-lxml-import.md` |
| WG-6 | Investigate 2 surviving FAILs | 2 FAILs (post WG-1/2/5) | `02-wg-6-survivor-investigations.md` |
| WG-7 | Websocket suite false-FAIL parser | 1 spurious suite FAIL | `02-wg-7-websocket-parser.md` |
| WG-8 | Run-queue orphan + consumer-stall guardrails | 1 stuck + 8 reaped | `02-wg-8-orphan-and-stall-guardrails.md` |
| WG-9 | TFE voice-gate auto-fallback | 1 stalled TFE run | `02-wg-9-tfe-voice-gate-fallback.md` |

## Standing-rule constraints (applied to every WG)

1. **No GPU touching in tests** — see `feedback_never_grab_gpu` corollary added 2026-04-28: tests that touch CUDA/embedding engines must be DELETED, not guarded. Tests call `/api/embeddings/batch` instead.
2. **No auto-promotion of build tags** — Docker rebuilds (WG-1) park at candidate tag (`lupin:1.0.0-fonts`), never overwrite `lupin:1.0.0` until user confirms.
3. **No auto-commit / auto-push** — every commit waits for explicit user authorization.
4. **`:8000` is monopolize-mode** — verification re-run goes through `POST /api/test-suite/submit` with user-confirmed `scheduled_at`. No ad-hoc injection.
5. **Documentation-First** — these doc stubs exist before any source edit lands. (Phase 0.)

## Acceptance criteria (end-to-end)

A scheduled `:8000` re-run after all WGs land must:
- 0 ERRORs in e2e suite (visual-regression all green)
- smoke FAILs ≤ 2 (only WG-6 leftovers permitted)
- websocket suite classified PASS (not the prior 0/0/0/0 FAIL)
- 0 jobs orphaned in `run` after run completes
- TFE either auto-ratifies (if WG-9 default flipped from `stall`) or stalls cleanly without losing proposals

## Suggested execution order

| Phase | WGs | Why |
|-------|-----|-----|
| 0 | (these doc stubs) | Documentation-First gate |
| 1 | WG-3 (deletes), WG-4, WG-5 (deps only), WG-2 | Pure-code, no image rebuild |
| 2 | WG-1 + WG-5 image piggy-back | Image rebuild + baseline regen — fixes 12 e2e ERRORs |
| 3 | WG-7 | Parser fix |
| 4 | WG-8 cleanup + observability | Orphan + heartbeat |
| 5 | WG-9 | TFE voice-gate fallback |
| 6 | WG-6 | Re-run, root-cause survivors |
| Verify | Schedule full `:8000` run | Single end-to-end gate |

## References

- Plan file (Claude planning artifact): `~/.claude/plans/floating-greeting-bentley.md`
- TFE stalled report: `io/swe-team/reports/interactive.job.tester@lupin.deepily.ai/2026.04.27-at-23:03-EST-ts-90890bae-stalled-test_fix_expediter-report.md`
- All-results report: `io/test-suite/2026.04.27-at-22:35-EDT-all-results.md`
