# TODO

Last updated: 2026-02-03 (Session 129)

## Pending

### Skills Management (Session 118 Discovery)

Skill candidates identified - create with `/plan-skills-management-create <skill-name>`:
- [ ] **notification-patterns** (HIGH) - cosa-voice MCP usage patterns (~250 lines)
- [ ] **path-management** (MEDIUM) - `cu.get_project_root()` vs bootstrap (~150 lines)
- [ ] **code-style-preferences** (LOW) - Spacing, alignment, getattr prohibition (~100 lines)

### Before Branch Merge (This Week)

- [x] **[LUPIN] Verify CJ Flow Queueable Job Protocol Compliance** - Session 124: Investigation complete, implementation verified compliant. Session 128: Verification complete.
  - **Report**: `src/rnd/2026.02.02-cj-flow-protocol-compliance-report.md`
  - **Finding**: ClaudeCodeJob implements all 22 protocol requirements for both BOUNDED and INTERACTIVE modes
- [x] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for BOUNDED tasks** - Session 128: Complete
- [ ] **[LUPIN] CJ Flow verification: Dry run end-to-end testing for UNBOUNDED tasks** - Pending
- [x] **Run baseline testing plan** - Session 123: **COMPLETE** ✅
  - Unit tests: 168/199 (84.4%) → **195/195 (100%)**
  - All test infrastructure issues resolved
  - 4 debug scripts moved to `src/scripts/debug/`
  - See: `src/rnd/2026.02.02-test-suite-remediation-plan.md`
- [ ] **[LUPIN] Run agentic job intent LORA 1% sample training** - Requires GPUs to be freed. Run: `./src/scripts/run-agentic-intent-training.sh test`. **Session 124**: Unified training pipeline now includes agentic jobs (40,258 total examples, 600 agentic). **Scheduled: Evening session 2026-02-02** when GPU resources available.
- [ ] **[LUPIN] Fuzzy file matching for LORA adapter podcast generation routing** - Two cases to handle:
  1. User makes vague reference to research document contents (e.g., "make a podcast about that AI research")
  2. User references research document by approximate name/path
  - Voice mode especially needs fuzzy matching due to transcription variations
  - Similar implementation already exists in FastAPI endpoint called from notifications UI
  - **Reference**: `src/conf/prompts/fuzzy-file-matching.txt` (prompt template exists)
- [ ] **[LUPIN] Extended Parameter Training (Chunk 1.6)** - Extend LORA training data beyond simple topics/filenames to include occasional budget and runtime arguments:
  - `topic="quantum computing" budget=50`
  - `topic="AI safety" target_audience=beginner`
  - `document_path="/io/deep-research/report.md" languages=en,es max_segments=20`
  - Requires: New placeholder files for budgets, audience levels; update generation logic
- [ ] **[LUPIN] Disambiguation Agent for Missing Arguments** - Create agent to clarify unusual or missing arguments interactively:
  - Trigger when LORA model returns intent but args are incomplete/ambiguous
  - Use `ask_multiple_choice()` or `converse()` for clarification
  - Example prompts: "What budget would you like for this research?" "Which language(s) for the podcast?"
  - Affects: Voice routing pipeline, potentially new agent class
- [x] **Run Deep Research dry-run smoke test** - Session 115: All 5 tests passed (login, submit, structure, polling, verification). Job dr-6aa5d16d completed in ~10s with $0.00 cost.
- [x] **Run Podcast Generator dry-run API smoke test** - Session 115: All tests passed. Job pg-dd026977 completed in ~10s with $0.00 cost.
- [x] **Run Research→Podcast dry-run API smoke test** - Session 115: All tests passed. Job rp-221fe28e completed in ~14s with $0.00 cost.

### job_state_transition Implementation (Session 107 - Complete)

- [x] Phase 1: Add job_state_transition to config files
- [x] Phase 2: Add _emit_job_state_transition method to FifoQueue
- [x] Phase 3: Add server emissions (7 transition points)
- [x] Phase 4: Client subscription to job_state_transition
- [x] Phase 5: Client handler (handleJobStateTransition, insertJobMetadata)
- [x] Phase 6: Badge-only handlers
- [x] Phase 7: Placeholder DOM nodes in renderJobCard()
- [x] Phase 8: Remove cruft - data structures
- [x] Phase 9: Remove cruft - methods
- [x] Phase 10: Remove cruft - logic
- [x] WebSocket smoke tests after Phase 10
- [x] Manual browser verification of job transitions

### Bug Fix: Job Card Field Parity (Session 107 - For Next Session)

- [x] **Test bug fix**: WebSocket cards now include 6 missing fields (status, has_interactions, is_cache_hit, started_at, completed_at, duration_seconds)
- [x] Verify cards created via WebSocket match server-fetched cards after page refresh
- [x] Test with mock job submission (success path)
- [x] Test with mock job failure (error path)

### Implementation Plans

- [ ] **Config Migration**: Implement Claude Agent SDK config migration plan documented at `src/rnd/2026.01.27-claude-agent-sdk-config-migration-plan.md`

### Browser Testing (Agentic Job Submission)

- [x] **Test 1**: Deep Research submission - verify job queues with dr-xxxxxxxx ID
- [x] **Test 2**: Research→Podcast (checkbox) - verify rp-xxxxxxxx prefix and chained routing
- [x] **Test 3**: Podcast Generator - Direct path mode (immediate queue)
- [x] **Test 4**: Podcast Generator - Description mode (fuzzy match → multiple choice)
- [x] **Test 5**: Error handling - empty topic shows validation warning
- [x] **Test 6**: Dry-run mode - Deep Research breadcrumb notifications
- [x] **Test 7**: Dry-run mode - Podcast Generator breadcrumb notifications
- [x] **Test 8**: Dry-run mode - Chained workflow (both sets of breadcrumbs)

### Verification Checklist

- [x] Research card submits to `/api/deep-research/submit`
- [x] Checkbox routes to `/api/deep-research-to-podcast/submit`
- [x] Podcast card submits to `/api/podcast-generator/submit`
- [x] Job IDs use correct prefixes (dr-, rp-, pg-)
- [x] Jobs appear in queue UI after submission
- [x] STT buttons work for voice input
- [x] Loading spinners show during submission
- [x] Error messages display correctly

### Architecture Review

- [x] **Cache Hit Behavior**: Moved to bug-fix-queue.md - Session 118

### Future Considerations

- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.

### Carried Over from Session 102

- [x] Test math agent notification fixes (hard refresh, ask "What's 11+11?", verify console logs and TTS) - Session 109 ✅
- [x] Verify both notifications appear in job card (not sender card)
- [x] Future: Add `tts_raw` parameter to cosa-voice MCP server

### COSA Submodule (Needs Separate Commit)

- [x] Commit API consistency fix: `deep_research.py` derives user_email from JWT
- [x] Commit dry-run mode additions to routers and job classes
- [x] Commit new `mock_clients.py` for Podcast Generator

---

## Next Version: v0.1.4

Voice I/O enhancements driven by cosa-voice MCP notification system. Both require planning documents before implementation.

### Pre-Development Setup

- [ ] **[LUPIN] Create baseline test report for wip-v0.1.4 branch** - Run `/smoke-test-baseline` to establish pass/fail baseline before starting development work. This ensures we can detect regressions introduced during v0.1.4 development.

### Cache Freshness Policy (HIGH) - Session 121/122

- [x] **Create planning document**: `src/rnd/2026.02.02-cache-freshness-implementation-plan.md` - Session 121
- [x] **Simple fix implemented**: Always re-execute cached code in `_format_cached_result()` - Session 122
  - Trade-off: Math queries re-execute unnecessarily (~100ms) but ensures time queries are always fresh
  - Full policy system (Phases 1-4) deferred until simple fix proves insufficient
- [ ] **Phase 1**: Foundation - Create `cache_freshness_policy.py`, add `cache_policy` to SolutionSnapshot, update LanceDB schema, add config keys
- [ ] **Phase 2**: Agent integration - Add property overrides to DateAndTimeAgent (VOLATILE), MathAgent (IMMUTABLE), WeatherAgent (VOLATILE)
- [ ] **Phase 3**: Enforcement - Add `_is_cache_immutable()` and `_handle_volatile_cache()` to running_fifo_queue.py
- [ ] **Phase 4**: Semantic match confirmation (deferred - add `ask_yes_no()` for approximate matches)

### Semantic Cache Hit Confirmation (MEDIUM) - Merged into Cache Freshness

- [x] **Planning document**: Merged into Cache Freshness Policy plan (`src/rnd/2026.02.02-cache-freshness-implementation-plan.md`)
- [ ] **Implementation**: Part of Cache Freshness Phase 4 (deferred)

### Voice Module Audit (MEDIUM)

- [ ] **Review cosa_interface.py vs voice_io.py** - Audit for overlap, redundancy, and execution flow clarity
  - **Files**: `src/cosa/agents/claude_code/cosa_interface.py`, `src/cosa/agents/claude_code/voice_io.py`
  - **Goal**: Understand and document the relationship between these modules
  - **Deliverable**: Refactor if redundancy found, or document if distinct purposes

### CJ Flow Persistence (HIGH)

- [ ] **Add persistence for CJ Flow job tracking** - Jobs are currently transient
  - **Goal**: Durable storage for ClaudeCode Job tracking state
  - **Affects**: Job state survives server restarts, enables job history/resume

### Post-Execution Feedback Loop (HIGH)

- [ ] **Create planning document**: `src/rnd/2026.02.XX-post-execution-feedback-plan.md`
- [ ] **Implementation**
  - **Goal**: After AgentBase-derived objects complete execution, collect user feedback via voice
  - **Questions to ask** (via `ask_yes_no()` or `ask_multiple_choice()`):
    1. "Was this response correct?" (yes/no)
    2. "Was the language and tone appropriate?" (yes/no)
  - **Data Collection**: Store feedback for potential fine-tuning / RLHF training data
  - **Affects**: `agent_base.py`, `todo_fifo_queue.py`, possibly new feedback storage table

---

## Completed (Recent)

- [x] **Deprecated util_xml.py Elimination**: Migrated all production code to Pydantic XML I/O - Session 116
  - Removed fallbacks from gister.py, confirmation_dialog.py
  - Added Pydantic to todo_fifo_queue.py, multimodal_munger.py
  - Removed ALL deprecated fallbacks from agent_base.py, bug_injector.py, raw_output_formatter.py
  - Rewrote xml_parser_factory.py to Pydantic-only (removed baseline and hybrid strategies)
  - Added deprecation warnings to util_xml.py
  - 12 files modified, all smoke tests passing
- [x] **Math Agent TTS Fix**: job_id pattern + user_email pipeline - Session 109, 110
  - Fix: Updated regex in `notification_models.py` to accept compound hash format
  - Fix: Added `user_email` as first-class constructor parameter (Session 110)
  - Verified: TTS now works for math questions via /api/push
- [x] job_state_transition Phases 6-10 (badge handlers, DOM nodes, cruft removal) - Session 107
- [x] WebSocket smoke tests for job_state_transition - Session 107
- [x] Bug fix implementation: Add 6 missing fields to WebSocket metadata - Session 107
- [x] Rename `currentUser` to `currentUserEmail` in notifications.js - Session 106
- [x] Remove redundant `user_email` from Deep Research JS request body - Session 106
- [x] Fix job cards not rendering when queue collapsed - Session 105
- [x] Fix TTS notification duplication in job cards - Session 104
- [x] Add dry-run checkboxes to agentic job submission UI - Session 103

---

*Completed items older than 7 days can be removed or archived.*
