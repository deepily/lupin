# Working Contract — Bounded ClaudeCodeJob Canonical Redesign

**Status**: ACTIVE | **Project**: Lupin | **Milestone**: 2026.05.07 BOUNDED ClaudeCodeJob redesign
**Layer**: 2 (Project anchor — instantiates Layer 1 `~/.claude/CLAUDE.md` for this milestone)

---

## Rules of Engagement

Before closing any phase of this milestone, the AI MUST have executed, on its own initiative, every verification step that is AI-executable. Phase-close is gated on observable evidence (commit hash, file path, test result), not on plausibility.

---

## Test-Layer Enumeration (per Lupin CLAUDE.md §TESTING VENUES)

| Layer | Who runs it | Trigger | Notes |
|-------|-------------|---------|-------|
| `py_compile` + import-chain | AI on `:7999` (or local) | After any `.py` edit | Mandatory floor per `~/.claude/CLAUDE.md` POST-EDIT VERIFICATION |
| Unit tests (`src/tests/unit/`) | AI on `:7999` (AI-discretionary) | After Phase 1, Phase 3, Phase 4, Phase 6 | Non-destructive; runs locally without server |
| Smoke tests (`src/tests/smoke/test_claude_code_*.py`, `test_claude_code_cli_smoke.py`) | AI on `:7999` (AI-discretionary) | After Phase 4, Phase 5 | Dry-run only; no real LLM spend |
| Integration tests (`src/tests/integration/test_dispatcher_{e2e,bidirectional}.py`, `test_sdk_validation.py`) | AI on `:7999` for BOUNDED-only subset | After Phase 2b consumer updates | INTERACTIVE-method tests skip-marked |
| Cross-agent regression baseline (TFE / BFE / swe_team / tfe_to_cc tests) | AI on `:7999` | **BEFORE Phase 1** code edits land | Baseline must precede Phase 1 — Phase 2a's relocation alone could leak into sibling agents, so a baseline captured between Phase 1 and Phase 4 would already reflect partial-refactor state and miss the regression. Post-refactor diff captured AFTER Phase 4 against the same target. |
| `:8000` scheduled full sweep | AI submits via `POST /api/test-suite/submit`; user confirms slot | After Phase 7a/7b green | Monopolize-mode; never side-door inject per `feedback_test_server_monopolize_mode` |
| Live API probe (`:7999`) | AI | Phase 7a concurrent isolation test | 2 jobs back-to-back with different JWTs to verify ContextVar isolation |

The AI runs every layer above without prompting, except `:8000` which requires user slot confirmation. CLI smoke (`python -m cosa.agents.claude_code --dry-run`) is AI-executed.

---

## User-Involvement Gate

The user's involvement is gated to **5 things and ONLY these 5 things**:

1. **Design decisions** — already collected (Q1, Q2, Q3 frozen in `01-design.md` §"Locked design decisions"). New design challenges surface via Layer-3 Design Concerns lane (canonical workflow §11), not in-line edits.
2. **Plan-review gate decisions** — Gate 1 (post-Pass 1 Fitness) and Gate 2 (post-Pass 2 Adversarial) per canonical `workflow/plan-review.md` §6 + §9. AI delivers findings; user picks which to apply.
3. **`:8000` slot confirmation** — for the Phase 7c full regression sweep. Slot availability is the user-ask, NOT budget approval per `feedback_test_server_monopolize_mode`.
4. **Commit authorization** — per `feedback_never_auto_commit_push`, every commit requires explicit user "commit" / "push". Phase 9 fires 1 CoSA commit (user-driven) + 1 Lupin-parent commit (user-driven).
5. **Pre-Phase-1 cross-agent baseline confirmation** — AI captures baseline (TFE / BFE / swe_team / tfe_to_cc smoke + unit tests, all green); user acknowledges the baseline files exist before ANY Phase 1 code edits land. Belt-and-suspenders against the regression-guard contract failing silently. The baseline must precede Phase 1 because Phase 2a's relocation could leak into sibling agents — capturing baseline between Phase 1 and Phase 4 would already reflect partial-refactor state.

**Anything outside these 5 categories is a violation of the contract.** In particular: code changes, test runs, residue greps, file moves, dispatcher relocation, and convention-amendment work are all AI-executable; the AI does NOT ask the user "should I run X?" for AI-executable steps.

---

## Cannot-Execute Rule

If the AI cannot execute a verification step, it MUST name the specific blocker (e.g., "needs GPU", "needs `:8000` slot", "needs human visual judgment") and ASK — not skip, not defer, not declare done.

Specific applications for this milestone:

- **GPU-touching workloads** — none planned. If one surfaces, it goes to user per `feedback_never_grab_gpu`.
- **`:8000` runs** — AI cannot self-schedule against a contended monopolize-mode server. Submit via `/api/test-suite/submit` with user-confirmed `scheduled_at` only.
- **CoSA git commands** — AI cannot run git inside `src/cosa/` per `feedback_lupin_only_never_cosa`. Edits in `src/cosa/agents/claude_code/` are fine; git ops happen in user's CoSA-context session.
- **INTERACTIVE method runtime testing** — out of scope. Methods exist as `NotImplementedError` stubs. Future runtime testing is a separate milestone.

---

## Phase-Complete Definition

A phase closes only when **both** are true:

1. Every verification checkbox has executed-and-reported evidence (test counts, file paths, commit hashes, transcript-output snippets — not "tests appeared to pass").
2. Commit hash is filed for the phase's deliverables. For Phase 9, this means BOTH commits land (CoSA submodule + Lupin parent), with hashes recorded in `90-execution-log.md`.

Anything less = contract violation. The AI does NOT mark a phase ✅ DONE in `90-execution-log.md` until both conditions are observable.

---

## Convergence Re-grep Contract (Resolution Loop)

After every Plan-Review Gate fix-application:
- Pass 1 fixes → re-run `grep -rn "TBD\|confirm during impl\|decide at impl time\|tbd\|Open sub-question" {{GREP_TARGETS}}` against this doc-set; assert convergence (zero new hits).
- Pass 2 fixes → re-run the three Pass-2 greps (`Manual\|manual`, `EXECUTOR: HUMAN`, bare-checkbox regex) against this doc-set; assert convergence.

Per canonical §7: "without it, 'resolved' is self-reported by the same agent that just generated the fixes — exactly the rubber-stamping failure mode the gates exist to prevent."

---

## Cross-References

- **Layer 1 anchor**: `~/.claude/CLAUDE.md` — TEST OWNERSHIP MANDATE + DOCUMENTATION-FIRST PROTOCOL
- **Layer 3 anchor (this milestone)**: `01-design.md` §"Locked design decisions" (Q1, Q2, Q3 frozen 2026-05-07)
- **Plan-review canonical**: `$PLANNING_IS_PROMPTING_ROOT/workflow/plan-review.md`
- **Auto-memory feedback rules cited**: `feedback_lupin_only_never_cosa`, `feedback_never_auto_commit_push`, `feedback_test_server_monopolize_mode`, `feedback_pip_plan_review_is_sequential`, `feedback_documentation_first`, `feedback_documentation_step_stops_at_doc`, `feedback_audit_plans_at_execute_time`
