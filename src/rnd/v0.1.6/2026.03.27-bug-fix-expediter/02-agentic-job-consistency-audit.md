# Phase 0: Agentic Job Consistency Audit & Remediation

**Created**: 2026-03-27 (Session 381)
**Status**: Planning
**Scope**: Fix critical consistency gaps across all AgenticJobBase implementations before building BugFixExpediterJob

---

## Audit Findings

### Jobs Analyzed

| Job | Location | Config Pattern | Voice I/O Pattern |
|-----|----------|---------------|-------------------|
| DeepResearchJob | `src/cosa/agents/deep_research/job.py` | `from_config()` | `voice_io` module |
| PodcastGeneratorJob | `src/cosa/agents/podcast_generator/job.py` | `from_config()` | `voice_io` module |
| SweTeamJob | `src/cosa/agents/swe_team/job.py` | Direct construction | `voice_io` module |
| ClaudeCodeJob | `src/cosa/agents/claude_code/job.py` | Class-level defaults | `cosa_interface` (different API) |
| PresentationGeneratorJob | `src/cosa/agents/presentation_generator/job.py` | `from_config()` | `voice_io` module |
| DeepResearchToPodcastJob | `src/cosa/agents/deep_research_to_podcast/job.py` | Inherited | Inherited |
| MockAgenticJob | `src/cosa/agents/mock_agentic/job.py` | None | Hard-coded deep_research import |

---

## Critical Gaps (4 items — must fix)

### Gap 1: Voice I/O API Divergence

**Problem**: ClaudeCodeJob uses `cosa_interface.notify_progress()` directly instead of the `voice_io` module pattern used by all other jobs.

**Impact**: Notification routing, job card activity log, and queue_name parameter handling differ between ClaudeCodeJob and all other jobs.

**Fix**: Audit ClaudeCodeJob's notification calls and align with the `voice_io` wrapper pattern. Either:
- (A) Add a `voice_io.py` module to `src/cosa/agents/claude_code/` following the established pattern, or
- (B) Refactor ClaudeCodeJob to call through its existing `cosa_interface` but with the same parameters (job_id, queue_name) that voice_io enforces

**Recommendation**: Option B — ClaudeCodeJob has unique bidirectional messaging needs (INTERACTIVE mode) that justify its own cosa_interface, but it should pass `queue_name` and use `set_job_id()`/`clear_job_id()`.

**Files to modify**:
- `src/cosa/agents/claude_code/job.py`
- `src/cosa/agents/claude_code/cosa_interface.py`

---

### Gap 2: `set_job_id()` / `clear_job_id()` Missing

**Problem**: Only DeepResearchJob and PodcastGeneratorJob call `voice_io.set_job_id()` on entry and `voice_io.clear_job_id()` in the `finally` block. SweTeamJob, ClaudeCodeJob, and MockAgenticJob skip this.

**Impact**: Job card activity log routing may not work — notifications emitted without job_id context won't appear under the correct job card in the UI.

**Fix**: Add `set_job_id(self.id_hash)` at the start of `_execute()` and `clear_job_id()` in the `finally` block for:
- `src/cosa/agents/swe_team/job.py`
- `src/cosa/agents/claude_code/job.py`
- `src/cosa/agents/mock_agentic/job.py`

**Pattern to follow** (from DeepResearchJob):
```python
async def _execute( self ):
    voice_io.set_job_id( self.id_hash )
    try:
        # ... execution logic ...
    finally:
        voice_io.clear_job_id()
```

---

### Gap 3: `queue_name` Parameter Missing

**Problem**: Several jobs omit the `queue_name="run"` parameter from their `notify()` calls during live execution. DeepResearchJob includes it consistently; PodcastGeneratorJob, ClaudeCodeJob, and MockAgenticJob don't.

**Impact**: Queue position tracking and notification routing to the correct queue bucket may not function correctly.

**Fix**: Add `queue_name="run"` to all `notify()` / `notify_progress()` calls in live execution paths for:
- `src/cosa/agents/podcast_generator/job.py` (and its voice_io module)
- `src/cosa/agents/claude_code/job.py` (and its cosa_interface)
- `src/cosa/agents/mock_agentic/job.py`
- `src/cosa/agents/swe_team/job.py` (live mode — already present in dry-run)

---

### Gap 4: Config Loading Pattern Divergence

**Problem**: Three different config loading patterns exist:
1. `from_config(config_mgr)` — DeepResearch, Podcast, Presentation (correct)
2. Direct construction — SweTeam (`SweTeamConfig(dry_run=False, trust_mode=...)`)
3. Class-level defaults — ClaudeCode (`cls._default_max_turns = config_mgr.get(...)`)

**Impact**: Inconsistent override behavior, harder to maintain, new developers copy the wrong pattern.

**Fix**:
- Add `from_config()` classmethod to `SweTeamConfig` in `src/cosa/agents/swe_team/config.py`
- Refactor ClaudeCodeJob to use an instance-level config object with `from_config()`
- Update job constructors to call `Config.from_config(config_mgr)` with job param overrides

**Note**: This was partially addressed in Session 364 (Config Migration Phases 0-4) for DeepResearch, Podcast, and LLM Client Factory. SweTeam and ClaudeCode were deferred.

---

## High Priority Gaps (2 items — should fix)

### Gap 5: Cancellation State Missing

**Problem**: Only DeepResearchJob handles a `cancelled` status. All other jobs go straight from `running` to `failed` if interrupted.

**Impact**: No way to distinguish "job was cancelled by user" from "job crashed" in the job history UI or persistence layer.

**Recommendation**: Add cancellation support to AgenticJobBase itself via a `request_cancel()` method and a `_cancelled` event that orchestrators can check. Defer to Phase 1+ (not blocking for Bug Fix Expediter).

### Gap 6: MockAgenticJob Module Coupling

**Problem**: MockAgenticJob hard-codes `from cosa.agents.deep_research import voice_io`, coupling it to a specific agent implementation.

**Fix**: Create a lightweight notification helper in MockAgenticJob or import from a shared location.

---

## Remediation Plan

### Task Breakdown

| # | Task | Files | Status |
|---|------|-------|--------|
| 0.1 | Audit all `notify()` calls across 6 jobs — catalog params | All job.py files | DONE (Session 381) |
| 0.2 | Add `set_job_id()`/`clear_job_id()` to SweTeamJob live path | `swe_team/job.py` | DONE (Session 381) |
| 0.3a | Add `queue_name="run"` to PodcastGeneratorJob (live + dry-run) | `podcast_generator/job.py` | DONE (Session 381) |
| 0.3b | Add `queue_name="run"` to ClaudeCodeJob (all 13 calls) | `claude_code/job.py` | DONE (Session 381) |
| 0.3c | Add `queue_name="run"` to PresentationGeneratorJob (live + dry-run) | `presentation_generator/job.py` | DONE (Session 381) |
| 0.4 | Align ClaudeCodeJob notification API with voice_io pattern | - | Deferred — cosa_interface already supports queue_name |
| 0.5 | Add `from_config()` to SweTeamConfig + update job.py | `swe_team/config.py`, `swe_team/job.py` | DONE (Session 381) |
| 0.6 | Decouple MockAgenticJob from deep_research voice_io | - | N/A — MockAgenticJob not found in codebase |
| 0.7 | Update agentic-voice-workflow skill template with enforcement checklist | 1 skill file | Pending |
| 0.8 | Run full unit test suite — verify no regressions | - | In Progress |
| 0.9 | Run integration test suite (`--bg`) — verify job lifecycle | - | Pending |

### Skill Template Updates (Task 0.7)

Add to the agentic-voice-workflow skill:

**Mandatory Compliance Checklist** (gate for new job creation):
```
□ Config class has from_config(config_mgr, debug) classmethod
□ _execute() calls voice_io.set_job_id(self.id_hash) on entry
□ _execute() calls voice_io.clear_job_id() in finally block
□ All notify() calls include queue_name="run" in live execution
□ _execute_dry_run() is a separate method (not flag check in _execute)
□ Job emits state transitions via emit_job_state_transition()
□ Dry-run mode sends breadcrumb notifications with job_id routing
□ Cost summary stored in self.artifacts["cost_summary"]
□ answer_conversational set before job completes
□ Error stored in self.error on failure
```

### Verification

- Unit tests: `pytest src/tests/unit/ -v` (expect ~2100+ pass)
- Integration tests: `./src/tests/run-integration-tests.sh --bg -v`
- Smoke: Dry-run each job type via API to verify notification routing
