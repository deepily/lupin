# 2026.05.07 — Bounded ClaudeCodeJob Canonical Redesign

**Status**: ⏳ Plan approved + serialized + conventions amended; PIP plan-review gate in flight (REUSE pre-pass next).
**Pattern**: Pattern 5 (Refactor) in scope, Pattern 3 in shape (single-design-doc + execution log; no Pattern A/B/C scaffolding).
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`
**last-reviewed-at**: (not yet — will populate on Gate 2 closure)

---

## Quick Navigation

| Doc | Purpose |
|-----|---------|
| [00-index.md](00-index.md) | This file — master navigation + idempotency marker |
| [00-working-contract.md](00-working-contract.md) | Layer 2 anchor — rules of engagement (test-layer enumeration, user-involvement gate, cannot-execute rule, phase-complete definition) |
| [01-design.md](01-design.md) | Full design: context, locked decisions Q1/Q2/Q3, architecture target, sibling-agent dependency surface, 9 phases, ACs, risks, out-of-scope |
| [90-execution-log.md](90-execution-log.md) | Phase status table + per-phase evidence (populated as work progresses) |

---

## Project Overview

**Why**: The `/api/claude-code/dispatch` rogue endpoint cluster was retired on 2026-05-05 (commit `73bee1b`, session `1a8900ee`). The cj-flow successor `claude_code_queue.py` + `ClaudeCodeJob` works for BOUNDED submission but is structurally incomplete vs the canonical agentic-job pattern (only 4 of 8 canonical files; missing `config.py`, `state.py`, `orchestrator.py`, `__main__.py`; no `set_dispatch_context()` ContextVar isolation; output truncated to 500 chars).

**What this redesign solves**: bring `ClaudeCodeJob` to first-class CJ Flow agentic-job status — drop-in compatible with the same lifecycle / notification / artifacts contract used by Deep Research, Podcast Generator, Presentation Generator. Plus relocate `src/cosa/orchestration/claude_code/` (Claude-Code-only orphan tree outside the canonical containment) into `src/cosa/agents/claude_code/`.

**Predecessor R&D**: [2026.05.05-claude-code-dispatch-retirement](../2026.05.05-claude-code-dispatch-retirement/01-plan.md) — retired the rogue endpoint cluster.

---

## Key Decisions (FROZEN 2026-05-07)

See [01-design.md §"Locked design decisions"](01-design.md) for full rationale.

| Q | Question | ✅ Decision |
|---|----------|------------|
| Q1 | INTERACTIVE forward-compat scope | BOUNDED with extensibility hooks (reserved method names + state-machine slots; `NotImplementedError` stubs) |
| Q2 | Output persistence strategy | Full transcript to file at `io/claude-code/YYYY.MM.DD-at-HH:MM-EST-<slug>.md`, mirror DeepResearch's `report_path` pattern |
| Q3 | Voice clarifications mid-task | Direct cosa-voice MCP from spawned subprocess; RAE used only for `expeditor_required_args=("prompt",)` |

---

## Phase Summary

| Phase | Status | Notes |
|-------|--------|-------|
| 0 — Documentation | ✅ DONE | This file + 00-working-contract + 01-design + 90-execution-log all serialized |
| **GATE — PIP plan review** | ⏸️ PARTIAL (suspended 2026-05-07) | REUSE ✅ closed; Pass 1 Fitness ⏸️ 4/11 findings applied (STRUCTURAL batch); 7 findings + Pass 2 remain. Resume with `/plan-review --from=fitness`. Detail in `90-execution-log.md` § Pass 1 Suspended. |
| 1 — `config.py` + `state.py` | 🔒 BLOCKED on plan-review |
| 2a — Move + rename (orchestration → agents) | 🔒 BLOCKED |
| 2b — Update consumers (job.py, swe_team docstring, 4 manual + 3 integration tests) | 🔒 BLOCKED |
| 2c — Delete orphan `src/cosa/orchestration/` tree | 🔒 BLOCKED |
| 3 — `cosa_interface.py` + `voice_io.py` refactor | 🔒 BLOCKED |
| 4 — `job.py` rewire | 🔒 BLOCKED |
| 5 — `__main__.py` (CLI) | 🔒 BLOCKED |
| 6 — Tests | 🔒 BLOCKED |
| 7a — Live `:7999` verification | 🔒 BLOCKED |
| 7b — Cross-agent regression (baseline pre, post post Phase 4) | 🔒 BLOCKED |
| 7c — `:8000` scheduled full sweep | 🔒 BLOCKED on user slot |
| 8 — Documentation refresh | 🔒 BLOCKED |
| 9 — Wrap (queue + history + commits) | 🔒 BLOCKED |

---

## Doc Conventions Status

Per `workflow/p-is-p-02-documenting-the-implementation.md` §"Doc Conventions for Plan-Review Compatibility":

| Convention | Where | Status |
|-----------|-------|--------|
| 1 — Working-contract | `00-working-contract.md` | ✅ Created 2026-05-07 |
| 2 — Decision-anchor format (Q-N FROZEN) | `01-design.md` §"Locked design decisions" | ✅ Reformatted 2026-05-07 |
| 3 — `EXECUTOR: AI / HUMAN` tagging | `01-design.md` Phase 6 + Phase 7a/7b/7c + Verification section | ✅ Added 2026-05-07 |
| 4 — `TBD` / `Open sub-question` markers | `01-design.md` | ✅ N/A — all decisions locked, no design TBDs (only 2 false-positive "Result: TBD" placeholders in `90-execution-log.md` scaffold; not design TBDs) |
| 5 — "Manual E2E" semantics | `01-design.md` | ⚠️ Hits exist but are directory references (`src/tests/manual/`) and "manual experimental scripts" — **not** semantic "Manual E2E" claims. Pass 2 grep will surface these as false positives; flag during gate as not-applicable. |

---

## Open follow-ups

- **2026-05-07 — Extract central presentation-filename helper** (REUSE finding #16, deferred per user). Pattern (`YYYY.MM.DD-at-HH:MM-EST-<slug>.md`) currently duplicated across DR (inline in `job.py:237-244`), Podcast (`config.py:346-390` `get_output_path()`), and now ClaudeCode. Extraction candidate: `cosa/agents/utils/presentation_filename.py`. **Trigger**: 4th agent that needs the pattern. Defer until then to avoid premature abstraction.

### Skip-with-reason log

- **2026-05-07 — Pass 2 Convention 5 ("Manual E2E")**: 21 grep hits in `01-design.md` are directory references (`src/tests/manual/`) and prose ("manual experimental scripts"). NONE are semantic "Manual E2E" claims. Pass 2 will be advised to filter these as false positives; no convention violation present.

---

## Prior art referenced

REUSE pre-pass output (per canonical `workflow/plan-review.md` §4). All `reuse-as-is` + `extend-existing` verdicts captured here for code-write-time reference. Source: 2026-05-07 Explore-agent grep against `src/cosa/`, `src/fastapi_app/`, `src/tests/`.

### `reuse-as-is` (verified to copy verbatim or use directly)

| Pattern | Source (file:line) |
|---------|---------------------|
| `set_dispatch_context()` ContextVar isolation | `src/cosa/agents/deep_research/cosa_interface.py:91-132` ✅ verified |
| Agent-bound `voice_io.py` wrapper | `src/cosa/agents/deep_research/voice_io.py:1-56` ✅ verified |
| `Gister` slug generation (`gister.get_gist(prompt, prompt_key=...)`) | `src/cosa/memory/gister.py:71-120` (shared utility); consumer pattern at `src/cosa/agents/deep_research/job.py:237-244` ✅ verified |
| `_execute()` ContextVar block + `voice_io.set_job_id`/`clear_job_id` | `src/cosa/agents/deep_research/job.py:246-262, 391` ✅ verified |
| `artifacts["transcript_path"]` artifact-key pattern (key name varies; `transcript_path` here, `report_path` in DR, `audio_path` in Podcast) | `src/cosa/agents/deep_research/job.py:339` |
| `ClaudeCodeConfig` dataclass shape (`@dataclass + from_config(config_mgr, debug=False)` classmethod) | `src/cosa/agents/deep_research/config.py:16-120`, `src/cosa/agents/podcast_generator/config.py:252`, `src/cosa/agents/bug_fix_expediter/config.py:13` |
| `__main__.py` CLI module (vs. DR's separate `cli.py` variant) | `src/cosa/agents/podcast_generator/__main__.py`, `src/cosa/agents/swe_team/__main__.py`, `src/cosa/agents/presentation_generator/__main__.py` |
| Presentation-filename slug + timestamp formatting (deferral candidate; currently duplicated) | Podcast `config.py:346-390` `get_output_path()`, DR `cli.py:788-850` `save_report_with_frontmatter` |

### `extend-existing` (rename / relocate / add fields — NOT net-new)

| Plan claim | Existing source | What changes |
|------------|----------------|--------------|
| `ClaudeCodeRunResult` dataclass | `TaskResult` at `cosa/orchestration/claude_code/dispatcher.py:101-111` (8 fields: `task_id`, `success`, `session_id`, `result`, `cost_usd`, `duration_ms`, `error`, `exit_code`) | Rename class; relocate to `state.py`; add `transcript_path: str`; rename `result` → `output_text` |
| `ClaudeCodeOrchestrator.run_bounded()` method | `ClaudeCodeDispatcher.dispatch(Task)` BOUNDED branch, `dispatcher.py:122+` | Rename class + method; signature changes (Task → individual args); BOUNDED logic preserved verbatim |
| INI keys (Phase 1 `config.py`) | Existing keys at `lupin-app.ini:388-389`: `claude code job max turns default`, `claude code job timeout seconds default` | Adopt `claude code bounded job *` namespace (anticipates future `claude code interactive job *`); drop `default` suffix (defaults belong in dataclass, not key names); add 2 new keys (`transcript dir`, `narrate progress`) |
| `Task`/`TaskType`/`TaskResult`/`SessionInfo` dataclasses | Currently inside `dispatcher.py:68-111` | Relocate to `state.py` (per Q1 locked decision: state.py groups all agent-internal types); no field changes |
| `MessageHistory` class | `cosa/orchestration/claude_code/message_history.py` | Verbatim move to `cosa/agents/claude_code/message_history.py`; only internal imports update |
| `cosa_interface.set_dispatch_context()` (porting block from DR) | `cosa/agents/deep_research/cosa_interface.py:91-132` | Add this block to CC's `cosa_interface.py` (currently lacks it); not a copy-paste — adapt sender_id suffix logic to CC's `base_id` shape |

### Genuinely-new (no prior art; novelty justified)

| Item | Why novel |
|------|-----------|
| `ClaudeCodeState` enum (PRE_FLIGHT → DISPATCHING → EXECUTING → PERSISTING → COMPLETED/FAILED + 3 INTERACTIVE-reserved values) | Linear bounded flow specific to BOUNDED execution; sibling agents (DR, SWE) have richer multi-phase state machines (CLARIFYING / PLANNING / RESEARCHING). Reserved INTERACTIVE values are extensibility hooks per Q1. |
| INTERACTIVE `inject` / `interrupt` / `end_session` stub methods raising `NotImplementedError` | Reservation-of-name pattern not used elsewhere in CoSA. This IS the extensibility hook Q1 locked. |
| `ClaudeCodeOrchestrator.write_transcript()` on orchestrator class | DR uses utility function, TFE/BFE use job-level methods; CC chooses orchestrator-level (intentional architectural choice; rationale documented in 01-design.md §Phase 2a). |
| 5 new unit tests + 1 new CLI smoke test for CC | No CC unit tests exist today; mirrors DR/TFE/BFE test layout. |
| `src/docs/agents/claude-code-job-guide.md` | Sibling guides exist (`bug-fix-expediter-guide.md`, `podcast-generator-guide.md`, `deep-research-guide.md`); CC's guide doesn't. Net-new content; structure mirrors siblings. |
