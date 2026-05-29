# Execution Log — Bounded ClaudeCodeJob Canonical Redesign

**Plan**: `01-design.md` (this directory).
**Session**: 6825e6af (2026-05-07).
**Status**: ⏳ Plan approved + serialized; awaiting PIP plan review (REUSE → Pass 1 → Pass 2, sequential) before code edits begin.

---

## Phase status

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 0 — Documentation (R&D doc + paired log) | ✅ DONE | 2026-05-07T20:30:00 | 2026-05-07T20:35:00 | `01-design.md` + this file. Plan serialized from `~/.claude/plans/so-it-looks-like-silly-map.md` (approved 2026-05-07 via ExitPlanMode). |
| **GATE — PIP plan review** | ⏸️ PARTIAL | 2026-05-07T20:30:00 | (in flight) | REUSE pre-pass ✅ CLOSED 2026-05-07. Pass 1 Fitness ⏸️ SUSPENDED at 4/11 findings applied (STRUCTURAL batch closed; 4 implementation-completeness + 3 operational findings remain). Pass 2 Adversarial pending. Resume with `/plan-review --from=fitness` (REUSE already closed). Implementation does NOT begin until Pass 2 closure. |
| 1 — `config.py` + `state.py` | 🔒 BLOCKED | | | Blocked on PIP review |
| 2a — Move + rename (orchestration → agents) | 🔒 BLOCKED | | | Blocked on PIP review |
| 2b — Update consumers (job.py / swe_team docstring / 4 manual tests / 3 integration tests) | 🔒 BLOCKED | | | Blocked on PIP review |
| 2c — Delete orphan `src/cosa/orchestration/` tree | 🔒 BLOCKED | | | Blocked on PIP review |
| 3 — `cosa_interface.py` + `voice_io.py` refactor | 🔒 BLOCKED | | | Blocked on PIP review |
| 4 — `job.py` rewire | 🔒 BLOCKED | | | Blocked on PIP review |
| 5 — `__main__.py` (CLI) | 🔒 BLOCKED | | | Blocked on PIP review |
| 6 — Tests (1 update + 5 new + 7 import-path updates) | 🔒 BLOCKED | | | Blocked on PIP review |
| 7a — Live `:7999` verification | 🔒 BLOCKED | | | Blocked on Phase 1-6 |
| 7b — Cross-agent regression (baseline + post check) | 🔒 BLOCKED | | | Baseline must be captured BEFORE Phase 4 lands |
| 7c — `:8000` scheduled full sweep | 🔒 BLOCKED | | | User-coordinated slot |
| 8 — Documentation refresh | 🔒 BLOCKED | | | After Phase 7 closure |
| 9 — Wrap (queue + history + commits) | 🔒 BLOCKED | | | After Phase 8 closure |

---

## Phase 0 — Documentation (DONE)

**2026-05-07** — Plan approved via ExitPlanMode (origin: `~/.claude/plans/so-it-looks-like-silly-map.md`). Serialized into this directory's `01-design.md`. Paired execution log scaffold created (this file).

R&D directory created: `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/`.

**Pre-existing context preserved**:
- Predecessor R&D: `src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/01-plan.md` (the rogue endpoint retirement)
- Predecessor R&D: `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/{01-design,90-execution-log}.md` (today's 503 cascade fix — same session 6825e6af)

---

## GATE — PIP plan review

### REUSE pre-pass — ✅ CLOSED 2026-05-07

**Outcome**: 18 findings. User decisions (via `AskUserQuestion`):
- F#3 `ClaudeCodeRunResult` reframed as rename-from-`TaskResult` (Recommended applied)
- F#8 INI key namespace expanded to `claude code bounded job *` (anticipates future `claude code interactive job *` namespace)
- F#18 `Task`/`TaskType` placement → `state.py` (Recommended applied)
- F#4 + SDK_AVAILABLE re-export + #16 deferral applied

**Edits to 01-design.md**: Phase 1 INI keys (4 new keys, atomic-rename approach), Phase 2a `ClaudeCodeRunResult` reframing + `write_transcript()` architectural-choice paragraph, Phase 2b SDK_AVAILABLE re-export bullet.

**Edits to 00-index.md**: Prior art referenced section appended (15 reuse-as-is + 6 extend-existing + genuinely-new tables); Open follow-up logged for #16 (presentation-filename helper extraction); skip-with-reason logged for Convention 5 false-positive Manual hits.

**Convergence**: 0 new TBD/Open-sub-question hits in 01-design.md + 90-execution-log.md ✓

### Pass 1 — Fitness — ⏸️ PARTIALLY CLOSED 2026-05-07; SUSPENDED at 4/11 findings applied

**Findings delivered**: 11 total + 0 TBDs + 0 Layer-3 Design Concerns. Severity-grouped.

#### ✅ Closed (4/4 STRUCTURAL findings, applied via single-finding `ask_yes_no` ratification)

| F# | Title | Resolution applied |
|----|-------|---------------------|
| F1 | Phase 1 INI key migration | Atomic rename approach (no shim) — rationale paragraph added to 01-design.md after the INI key list. The user's question "how does the shim differ from the standard pattern?" surfaced that the shim was overengineered; canonical pattern (`config_mgr.get(new_key, default=…)` + atomic rename in `lupin-app.ini`) chosen. |
| F4 | `run_bounded()` signature | Canonical "all args on `__init__` + parameterless run-mode methods + job-level routing" pattern adopted (matches Podcast `do_all_async` / `do_review_only_async` / `do_audio_only_async` mode-method shape). `ClaudeCodeOrchestrator` shape rewritten in 01-design.md Phase 2a; Phase 4 `_execute()` rewire description updated; AC17 + AC18 added. |
| F8 | `stream_thoughts_to_voice` unsourced field | Removed from `ClaudeCodeConfig` dataclass. User comment: *"this definitely predates how the canonical agentic tasks work"*. |
| F10 | Phase 7b baseline timing | Re-targeted "BEFORE Phase 4" → "**BEFORE Phase 1**" in 01-design.md Phase 7b + Verification block + 00-working-contract.md test-layer table + user-involvement gate item 5. Phase 2a's relocation alone could leak into sibling agents, so baseline must precede ALL code edits, not just Phase 4. |

**Convergence**: 0 new TBD/Open-sub-question hits in 01-design.md + 90-execution-log.md ✓
**Verification commands run**:
- `grep -nE "TBD|Open sub-question" 01-design.md 90-execution-log.md` → only meta-references in 00-index.md + 00-working-contract.md
- `grep stream_thoughts_to_voice 01-design.md` → 0 hits (F8 confirmed gone)
- `grep "BEFORE Phase 1" 01-design.md 00-working-contract.md` → 4 hits (F10 propagated correctly)

#### ⏸️ Suspended — 7 findings remaining (NOT YET applied)

User suspended the gate at session-end on 2026-05-07. Resume with `/plan-review --from=fitness` (skips REUSE which is already closed) and walk these 7 findings via the same single-finding `ask_yes_no` cadence the user established for the structural batch.

**Implementation-completeness batch** (4 findings):

| F# | File:Section | Type | Gap |
|----|--------------|------|-----|
| F2 | 01-design.md:243-248 Phase 3 `_get_sender_id(suffix=None)` | AMBIGUITY | What format is `suffix`? Always appended? `f"{base_id}#{suffix}"` or substring? Behavior when `base_id` is None/empty — error or graceful degrade? |
| F3 | 01-design.md:214 Phase 2a `write_transcript()` error paths | COMPLETENESS | Silent on file collision (existing transcript), missing transcript-dir (mkdir or fail?), empty `Gister` slug (fallback to timestamp?). |
| F5 | 01-design.md:264 Phase 3 notification contract | TESTABILITY | 5 notification types listed (start/preflight/dispatch/per-message/completion/failure) but no map of trigger → code location. Can't verify call sequence without spec. |
| F9 | 01-design.md:312-314 Phase 6 concurrent isolation test | TESTABILITY | Assertion shape undefined. How many concurrent jobs? Read ContextVar directly or compare return values? |

**Operational batch** (3 findings):

| F# | File:Section | Type | Gap |
|----|--------------|------|-----|
| F6 | 01-design.md:333-354 Phase 7b "zero new failures" | AMBIGUITY | "New failure" definition fuzzy. Pre-existing failures count? Comparison automation — diff JUnit XML, FAILED-line set diff, or manual? |
| F7 | 01-design.md:229 SDK_AVAILABLE re-export location | SCOPE | `__all__` placement: `cosa/agents/claude_code/__init__.py`, `orchestrator.py`, both? Module-level vs package-level relationship. (The placement-mandate language was added during REUSE apply; this F7 finding is whether the placement spec is detailed enough for a fresh implementer to act on.) |
| F11 | 01-design.md:375-381 Phase 9 commit ordering | AMBIGUITY | Which lands first — CoSA or Lupin parent? Lupin's tests will fail post-refactor until CoSA submodule pin updates. Submodule-pin mechanism unspecified (`git -C src/cosa checkout <hash>` or `git submodule update --remote`). |

**Resume protocol** for the next session:
1. `/plan-review --from=fitness --doc-set=src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/`
2. Skip the REUSE pre-pass (already closed; idempotency marker not yet set — set on Gate 2 close).
3. Re-run Pass 1 prompt — agent should re-discover the 7 above; cross-check by file:section to ensure no drift.
4. Walk via `ask_yes_no` (or `ask_multiple_choice` if there's a "neither" affordance by then — see TODO.md feature request filed this session).
5. After Pass 1 closure → Pass 2 Adversarial → Gate 2 → set `last-reviewed-at` in `00-index.md`.

### Pass 2 — Adversarial

(Pending. Awaits Pass 1 full closure.)

---

## Phase 1 — config.py + state.py

(To be filled.)

---

## Phase 2a — Move + rename

(To be filled. Will include: source/dest paths verified, class rename diff, method rename diff, dataclass relocation diff, py_compile evidence.)

---

## Phase 2b — Update consumers

(To be filled. Will include: per-file diff summaries, before/after import lines, residue grep results post-update.)

---

## Phase 2c — Delete orphan tree

(To be filled. Will include: pre-delete residue grep proof, `rm -rf` evidence, post-delete `ls` result.)

---

## Phase 3 — cosa_interface + voice_io refactor

(To be filled.)

---

## Phase 4 — job.py rewire

(To be filled. Will include: ContextVar isolation block diff, artifacts dict diff, INTERACTIVE method-stub additions.)

---

## Phase 5 — __main__.py (CLI)

(To be filled. Will include: `python -m cosa.agents.claude_code --dry-run --prompt "..."` returncode 0 evidence.)

---

## Phase 6 — Tests

(To be filled. Will include: per-test-file evidence, `pytest -v` outputs, coverage of the 4 manual + 3 integration test updates.)

---

## Phase 7a — Live :7999 verification

(To be filled. Will include: BOUNDED dry-run completion, transcript file path, concurrent-isolation test result.)

---

## Phase 7b — Cross-agent regression

### Pre-refactor baseline

(To be captured BEFORE any code edits. Paste pytest summary here.)

```
pytest src/tests/smoke/test_tfe_error_capture_smoke.py src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py src/tests/smoke/test_swe_team_dry_run_e2e.py src/tests/smoke/test_swe_team_orchestrator_dry_run_smoke.py src/tests/unit/test_tfe_to_cc_*.py -v --tb=no
```

(Result: not yet captured — fill at run time)

### Post-refactor regression

(After Phase 4 lands. Paste pytest summary here. Diff against baseline.)

```
pytest src/tests/smoke/test_tfe_error_capture_smoke.py src/tests/smoke/test_bfe_phase6_repair_loop_smoke.py src/tests/smoke/test_swe_team_dry_run_e2e.py src/tests/smoke/test_swe_team_orchestrator_dry_run_smoke.py src/tests/unit/test_tfe_to_cc_*.py -v --tb=no
```

(Result: not yet captured — must match baseline; fill at run time)

---

## Phase 7c — :8000 scheduled sweep

(To be filled. Will include: scheduled_at slot, suite scope, results.)

---

## Phase 8 — Documentation refresh

(To be filled.)

---

## Phase 9 — Wrap

(To be filled. Will include: bug-fix-queue tracking entry, commit hashes for both CoSA and Lupin parent commits.)

---

## Spec drifts + execute-time deviations

(Empty at start. Append any deviation from `01-design.md` here. Per `feedback_audit_plans_at_execute_time`, re-audit serialized plan diffs against feedback memories before applying.)
