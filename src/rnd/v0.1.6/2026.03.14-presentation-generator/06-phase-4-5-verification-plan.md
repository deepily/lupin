# Presentation Generator — Test & Verify Plan (Phases A-D)

**Date**: 2026-03-24
**Session**: 371
**Plan source**: `~/.claude/plans/memoized-popping-bunny.md`

## Context

Phases 1-5 are complete. This plan documents the verification strategy for testing the full pipeline from smoke tests through live E2E.

---

## Phase A: Smoke Tests — DONE

- [x] Run `python -m cosa.agents.presentation_generator --smoke-test` — 6/6 modules pass
- [x] Run narrative prompt smoke — pass
- [x] Run outline prompt smoke — pass
- [x] Run elaboration prompt smoke — pass

---

## Phase B: Enhanced Dry-Run Mode — DONE

Enhanced `--dry-run` to run real ingest, mock analysis/outline/elaborate, and real YAML serialization.

**Changes made**:
- `orchestrator.py`: Added `dry_run` parameter, mock data generation in `_analyze_async`, `_outline_async`, `_elaborate_async`, auto-approve in Gates 1-3
- `job.py`: Passes `dry_run` to orchestrator, removed old breadcrumb-only dry-run early-return
- `__main__.py`: Fixed `job_id` → `id_hash`, `execute_async()` → `_execute()`, removed print-only dry-run block

**Test result**:
```
Source: 01-strategy-and-design.md (2412 words, 30 sections, markdown)
Pipeline: Ingest(real) → Analyze(mock) → Gate1(auto) → Outline(mock) → Gate2(auto) → Elaborate(mock) → Gate3(auto) → Serialize(real) → Phases 6-8 (stubs)
Output: io/presentations/{user}/20260324-221221-mock--title-slide.yaml (4537 chars, 10 slides)
```

---

## Phase C: Dry-Run via Notifications UI — PENDING

Submit via CJ Flow queue card (same as Podcast Generator dry-run). Existing `_execute_dry_run()` sends breadcrumb notifications with `job_id` — conversation history panel will be exercised.

---

## Phase D: Live E2E Test — PENDING

Run with real Claude API calls (~$0.10-0.30, ~30-60s). Verify all 3 Claude calls + 3 voice I/O gates + YAML output.
