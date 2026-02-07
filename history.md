# Lupin Project History

### 2026.02.06 - Session 142 | Bug Fix Mode

### Fixes

#### Fix 1: DataFrameGroupBy.apply DeprecationWarning
- **Source**: ad-hoc (observed during PEFT validation runs)
- **Problem**: `groupby("command").apply(lambda)` included grouping columns in the lambda, triggering pandas DeprecationWarning about future behavior change
- **Files**: `src/cosa/training/peft_trainer.py` (line 597-600)
- **Solution**: Added `include_groups=False` to `.apply()` and adjusted index handling with `.droplevel(1).reset_index()` to preserve the "command" column
- **Test**: Unit 423/423 PASS, custom validation PASS
- **Commit**: afbfa7d (docs), CoSA pending

### Session Summary
(Will be completed at session close)

---

### 2026.02.06 - Session 141 | PEFT Phase 2: Model Swap + Disambiguation Tests

**Accomplishments**:
- Swapped PEFT model config from Spring 2025 (Phase 1) to 2026-02-05 Phase 2 training run (product name disambiguation + stratified validation)
- Verified 15/15 disambiguation unit tests pass (TestProductNameMapping: 3, TestConfirmAgenticRouting: 12)
- Full unit regression: 350/350 passed, zero regressions
- Last night's trained router confirmed working end-to-end

**Files Modified**: src/conf/lupin-app.ini (model path swap)
**Files Created**: src/tests/unit/test_agentic_disambiguation.py (15 tests)
**Checkpoint**: 423b217

---

### 2026.02.06 - Session 140 | Agentic Voice Workflow v2.0 Expansion

**Checkpoint 1**: Expanded workflow document from v1.0 (1,114 lines) to v2.0 (3,461 lines)

**Accomplishments**:
- Added Part I: CONCEPT — Why Agentic Jobs Exist, Architecture Overview (ASCII diagram), comparison table, decision checklist
- Expanded Part II: BUILD — Phase 0 pre-flight checks (API key firewall, ConfigurationManager, dependency verification), Phase 1-2 mock clients template, renamed Phase 5+ → Phase 5
- Added Phases 6-10: LLM Client Integration, Cost Tracking (thread-safe budget enforcement), Rate Limiting (sliding window), External Service Integration (WebSocket streaming, audio, caching), Advanced Orchestration (chained agents, progressive narrowing, parallel subagents)
- Added Part III: VALIDATE — The Testing Ladder with 5 surfaces ordered cheapest→most expensive: Unit+Smoke (free), Mock Endpoint (free), UI Cards+LLM ($0.001), PEFT Training ($5-50), Voice Pipeline ($0.01)
- Added complete new-agent checklist spanning CONCEPT → BUILD → VALIDATE → FINAL VERIFICATION
- Expanded Reference Implementations with all 16 key reference files
- All code templates follow Lupin code style (spaces inside parens, vertical alignment, Design by Contract)

**Files**: src/workflow/agentic-voice-workflow.md

---

### 2026.02.06 - Session 139 | Yes/No Comment Mic Button Styling Fix

**Accomplishments**:
- Unified yes/no comment mic button with shared `.response-mic-button` styles
- Removed ~25 lines of duplicate CSS (base, hover, recording, processing states)
- Added `response-mic-button` class to mic button element in JS template
- Kept minimal `.response-mic-button.yes-no-comment-mic` compound selector for `flex-shrink: 0`
- CSS specificity issue fixed: compound selector overrides later-declared base styles
- 335/335 unit tests passing, zero regressions

**Files**: notifications.js, notifications.css
**Checkpoint**: e2d92d2

---

### 2026.02.06 - Session 136 | Bug Fix Mode

**Checkpoint 1**: PEFT Phase 1 results + pending docs
- PEFT optimization plan updated with Phase 1 actual results: 92.2% exact match (target: 89%)
- Agentic job training data regenerated (train/test/validate JSONL)
- DataFrame CRUD design doc added (`src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`)

**Checkpoint 2**: PEFT Phase 2 — Disambiguation + Validation Improvements
- **Product name disambiguation**: Deep Dive (deep research), PodMaker (podcast generator), Doc-to-Pod (research to podcast)
- **Template expansion**: 50→65 templates per agentic command with product name variants + contrastive anchors
- **Code: file-loaded templates** in `xml_coordinator.py` — replaced 10 hardcoded patterns with 65 file-loaded templates per command
- **Code: stratified validation** in `peft_trainer.py` — equal samples per command instead of random sampling
- **Code: disambiguation confirmation loop** in `todo_fifo_queue.py` — voice prompt before agentic routing
- **Google Scholar anchor fixes**: 98 missing "Scholar" in new-tab, 97 missing "Google" in current-tab templates
- **None examples**: 200→250 with 50 near-miss examples (vague commands that resemble valid commands)
- **Document paths**: 24→50 placeholders, eliminating research_to_podcast sample gap
- **Training data regenerated**: 18,510 total (14,808 train / 1,851 test / 1,851 validate), 640 train/command for agentic
- **research_to_podcast**: 145→640 training samples (+341%)
- 335/335 unit tests passing, zero regressions

### Fixes
- **6b41a24** | `ask_yes_no()` missing `priority` parameter — was hardcoded to `MEDIUM`, preventing TTS read-aloud. Added `priority: str = "medium"` param matching `converse()` and `ask_multiple_choice()` signatures. File: `src/lupin_mcp/cosa_voice_mcp.py`

### Session Summary
- **Total Fixes**: 1
- **Files Changed**: src/lupin_mcp/cosa_voice_mcp.py
- **Commits**: 6b41a24

**Status**: Session closed 2026.02.06

---

### 2026.02.06 - Session 138 | Yes/No Comment Feature for Voice Notifications

#### Checkpoint 1 (8834751) | Optional comment field for ask_yes_no()

**Accomplishments**:
- Added expandable comment field to yes/no blocking notifications (compact hint: "Press C to add comment")
- Voice-first comment input using existing RecordingManager pattern (mic button + text input)
- Keyboard shortcut C toggles comment field; input guard prevents Y/N/P keys from firing while typing
- MCP `ask_yes_no()` return type changed from `bool` to annotated `str`: `"yes [comment: ...]"` or plain `"yes"`
- ~90 lines CSS (collapsible container with max-height transition, mic recording/processing states)
- **No regressions**: 335/335 unit tests, 50/50 websocket smoke tests passing

**Files**: notifications.js, notifications.css, cosa_voice_mcp.py
**Commit**: 8834751

---

### 2026.02.06 - Session 137 | DataFrame CRUD Phase 1 Implementation

#### Checkpoint | 2026.02.06 15:00 | Phase 1 DataFrame CRUD Storage Layer complete

**Accomplishments**:
- Implemented complete Phase 1 storage layer for voice-driven DataFrame CRUD operations
- Created `src/cosa/crud_for_dataframes/` package (5 modules):
  - `schemas.py` — 3 schemas (todo, calendar, generic) aligned with existing CSV conventions
  - `xml_models.py` — CRUDIntent BaseXMLModel with 12 fields, 8 convenience methods
  - `storage.py` — DataFrameStorage with per-user parquet I/O, datetime conversion at boundary
  - `crud_operations.py` — 10 stateless CRUD functions (create/delete/list/add/delete/update/mark_done/query/get_schema_info)
  - `__init__.py` — Public API exports, v0.1.0
- Added 4 config keys to `lupin-app.ini` + matching `lupin-app-splainer.ini` entries
- Created prompt template stub for Phase 2 intent extraction
- Created R&D documentation: `src/rnd/headless-cc-for-dataframe-crud/` (4 docs)
- **91 unit tests** + **16 smoke tests**, all passing
- **No regressions**: 335/335 existing unit tests still passing

**Issues found & fixed**:
1. Pydantic ClassVar: `VALID_OPERATIONS`/`DESTRUCTIVE_OPERATIONS` needed `ClassVar[List[str]]`
2. XML None coercion: xmltodict returns None for empty tags — added `field_validator`
3. Timestamp truncation: Added `allow_truncated_timestamps=True` for ns→ms parquet write

**Files**: schemas.py, xml_models.py, storage.py, crud_operations.py, __init__.py (+10 more)
**Commit**: [pending]

---

### 2026.02.05 - Session 135 [COSA] | Branch Transition v0.1.3 → v0.1.4

**Accomplishments**:
- Completed COSA branch transition via PR merge workflow
- Stashed 11 modified + 3 untracked WIP files, created PR #15 (8 commits, 55 files, +4,316/-1,380)
- PR merged, main fast-forwarded, created `wip-v0.1.4-2026.02.05-tracking-lupin-work`
- Restored WIP changes cleanly (RuntimeArgumentExpeditor, agentic_job_factory, training pipeline)

**PR**: https://github.com/deepily/cosa/pull/15

---

### 2026.02.05 - Session 134 | PEFT Training Optimization - Phase 1 Data Preparation

**Accomplishments**:
- Created 3-phase PEFT training optimization plan targeting 85% → 96%+ accuracy
- Identified 5 struggling commands (50-67% accuracy) due to semantic ambiguity, alias fragmentation, implicit context
- Implemented Phase 1 quick wins:
  - Added 15 "receptionist" keyword variants to placeholders (The Receptionist, Front Desk Receptionist, etc.)
  - Added 40 weather-keyword templates with explicit "weather" in queries
  - Regenerated training data: 17,236 total samples → 13,788 train / 1,724 test / 1,724 validate
  - receptionist and weather commands now at 640 training samples each (was underrepresented)

**Files**: 3 new/modified
- `src/rnd/2026.02.05-peft-trainer-optimization-plan.md` (NEW - full 3-phase plan)
- `src/ephemera/prompts/data/placeholders-receptionist-titles.txt` (+15 variants)
- `src/ephemera/prompts/data/synthetic-data-agent-routing-weather.txt` (+40 templates)
- `voice-commands-xml-*.jsonl` (regenerated, gitignored)

**Checkpoint**: 1ac1a4d

**Next**: Run PEFT trainer to validate Phase 1 improvements

---

### 2026.02.05 - Session 132 | DataFrame CRUD Implementation Plan

**Accomplishments**:
- Created comprehensive 4-phase implementation plan for Voice-Driven DataFrame CRUD
- Pattern 1 (Multi-Phase): Storage layer → Agent implementation → Queue integration → Voice I/O
- Key design decisions: per-user parquet storage with `list_name` column, ConfigurationManager pattern, BaseXMLModel reuse, RuntimeArgumentExpeditor reuse
- Added to TODO.md with Phase 1 marked "CONTINUES TOMORROW"

**Files**: 2 new, 1 modified
- `src/rnd/2026.02.05-crud-for-dataframes-implementation.md` (NEW) - Full implementation plan
- `src/rnd/README.md` (entry added)
- `TODO.md` (DataFrame CRUD section added)

**Design Doc Reference**: `src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`

---

### 2026.02.05 - Session 133 | Agentic Voice Workflow Skill Expansion Plan

**Accomplishments**:
- Created comprehensive expansion plan for `lupin-new-claude-agent-sdk-voice-workflow` skill
- Gap analysis: current workflow covers ~30% of real agent complexity (1,100 lines vs ~4,000 in reference agents)
- Proposed structure: CONCEPT → BUILD → TEST lifecycle with 16 sequential phases
- Key additions: LLM client integration, cost tracking, rate limiting, external service integration, advanced orchestration patterns, comprehensive test phases

**Files**: 1 new (+250 lines)
- `src/rnd/2026.02.05-agentic-voice-workflow-expansion-plan.md` (NEW)
- `src/rnd/README.md` (added entry)

---

### 2026.02.05 - Session 131 | Bug Fix Mode

### Fixes

#### Fix 1: PEFT Trainer False Positive Error Detection
- **Source**: ad-hoc (observed during LORA validation runs)
- **Problem**: `print_server_output()` used overly broad `"Error:" in line` check, triggering false positives on model-generated output containing error-related text
- **Files**: `src/cosa/training/peft_trainer.py` (lines 1365-1377)
- **Solution**: Replaced broad string matching with precise patterns:
  - `line.strip().startswith( "Error:" )` - only match line-start errors
  - `line.strip().startswith( "ERROR" )` - Python logging ERROR level
  - `line.strip().startswith( "Traceback" )` / `startswith( "RuntimeError" )` - Python exceptions
  - `"AsyncEngineDeadError"` / `"EngineDeadError"` in line - vLLM-specific errors
- **Test**: Existing smoke tests pass (no regressions)
- **Commit**: 9b0e6a7 (docs-only, CoSA code change pending separate commit)

### Session Summary
- **Total Fixes**: 1
- **Files Changed**: 1 (src/cosa/training/peft_trainer.py - CoSA submodule, pending separate commit)
- **Commits**: 9b0e6a7 (docs-only)

**Status**: Session closed 2026.02.05

#### Checkpoint | 2026.02.05 11:00 | Runtime Argument Expeditor test suite

**Summary**: Created comprehensive test suite for Runtime Argument Expeditor. Unit tests (49) cover ExpeditorResponse model, _parse_lora_args, _inject_system_args, agent registry + get_cli_help, and create_agentic_job factory — all mocked, no server needed, 0.54s runtime. Smoke tests (5) cover login, health check, standard mock job baseline (3 automated, passing), plus 2 interactive tests (expeditor voice routing + dry-run verification) gated behind `LUPIN_INTERACTIVE_TESTS=true`.
**Files**: test_runtime_argument_expeditor.py (NEW), test_expeditor_mock_job_smoke.py (NEW), TODO.md
**Commit**: 8135a5d

#### Checkpoint | 2026.02.05 11:20 | Testing plan R&D document

**Summary**: Copied testing plan to `src/rnd/2026.02.05-runtime-argument-expeditor-testing-plan.md` with execution status header. Added entry to `src/rnd/README.md`.
**Files**: 2026.02.05-runtime-argument-expeditor-testing-plan.md (NEW), rnd/README.md
**Commit**: 3e2d66b

---

### 2026.02.04 - Session 130 | Runtime Argument Expeditor + LORA Training Fixes

**Accomplishments**:
- Implemented RuntimeArgumentExpeditor (8 phases, 16 files) — runtime argument disambiguation layer between LORA intent classification and agentic job creation
- Fixed `get_model` AttributeError and `NotImplementedError` in LORA training pipeline
- Added GPU memory release gate for vLLM→fine-tune transitions
- Created shared `agentic_job_factory.py` DRY factory for voice + REST job creation paths
- All smoke tests passing (expeditor 5/5, registry 3/3, xml_models, prompt_template_processor 15/15)

**Checkpoints**: fe770a0 (rebalancing plan docs), 13ff105 (expeditor), 3883765 (NotImplementedError fix), e3e3392 (get_model fix), 3d9958f (GPU memory gate)

#### Checkpoint | 2026.02.04 20:15 | Runtime Argument Expeditor implementation (Phases 1-8)

**Summary**: Implemented RuntimeArgumentExpeditor — runtime argument disambiguation layer between LORA intent classification and agentic job creation. All 8 phases complete: agent registry (3 agents), ExpeditorResponse XML model + MODEL_MAPPING, prompt template, config keys (ini + splainer), router template commands, core expeditor class with LLM gap analysis + voice prompting, TodoFifoQueue elif integration, shared agentic_job_factory.py (DRY refactor for voice + REST paths), mock job expeditor test mode. 16 files total (6 new, 10 modified). All smoke tests passing (expeditor 5/5, registry 3/3, xml_models, prompt_template_processor 15/15).
**Files**: lupin-app.ini, lupin-app-splainer.ini, agent-router-template.txt, agent-router-template-completion.txt, runtime-argument-expeditor.txt (NEW), rnd/README.md (+11 CoSA files pending separate commit)
**Commit**: 13ff105

---

#### Checkpoint | 2026.02.04 20:45 | Rebalancing plan docs + TODO reference

**Summary**: Added rebalancing plan reference to TODO.md (deferred until after first full training run review). Added R&D README entry for `2026.02.04-rebalancing-xml-training-datasets.md`. Plan addresses 19x imbalance across 32 routing commands — unified sample_size param, interjections for simple vox, len() bug fixes, distribution verification. Target: 400 samples/command.
**Files**: TODO.md, src/rnd/README.md, history.md
**Commit**: fe770a0

---

#### Checkpoint | 2026.02.04 19:45 | NotImplementedError fix + training distribution analysis

**Summary**: Applied factory fix for `NotImplementedError` in `llm_client_factory.py:447-449` — replaced guard with dynamic `CompletionClient` creation for local vLLM (localhost:3000). Created smoke test (3/3 passing). Created `analyze-training-distribution.py` script revealing 19x imbalance across 32 commands (28,686 training rows): top tier at 1,600 samples vs clipboard variants at 83-160, agentic jobs at 200.
**Files**: llm_client_factory.py (CoSA submodule), test_vllm_dynamic_client_smoke.py (NEW), analyze-training-distribution.py (NEW)
**Commit**: 3883765

---

#### Checkpoint | 2026.02.04 18:00 | Fix get_model AttributeError + plan NotImplementedError fix

**Summary**: Fixed `AttributeError: module 'cosa.agents.llm_client' has no attribute 'get_model'` by renaming import alias `llm_v010` → `llmc` and adding class qualifier `LlmClient.get_model()` (6 changes in peft_trainer.py). Diagnosed deeper `NotImplementedError` in `llm_client_factory.py:449` — dynamic vLLM model keys bypass config lookup and hit unimplemented guard. Plan designed for factory fix.
**Files**: peft_trainer.py (CoSA submodule - pending separate commit), llm_client_factory.py (planned, not yet applied)
**Commit**: e3e3392

---

#### Checkpoint | 2026.02.04 17:05 | GPU memory release gate for LORA training OOM fix

**Files**: peft_trainer.py, xml_prompt_generator.py (CoSA submodule - pending separate commit)
**Summary**: Added `_wait_for_gpu_memory_release()` polling gate to prevent CUDA OOM when vLLM→fine-tune transition happens before GPU memory is freed. Commented out phind entries in xml_prompt_generator.py.
**Commit**: 3d9958f

---

#### Checkpoint | 2026.02.04 10:20 | Install PR workflow command

**Files**: `.claude/commands/plan-branch-pr-and-merge.md` (NEW)
**Commit**: 4fc6910

---

### 2026.02.04 - Session 129 (cont.) | Bug Fix Mode - MathAgent Protocol Verification

**Bug Investigated**: MathAgent fails QueueableJob protocol check on /api/push

**Investigation Results**:
- Protocol compliance test: **PASS** (MathAgent implements all 18 required attributes + 3 methods)
- API test: `/api/push` with math question returns **200 OK** with `{"status":"queued"}`
- **No code changes required** - bug was already fixed in Sessions 110-112

**Root Cause Analysis**:
- The QueueableJob protocol was introduced in Session 109-110
- AgentBase (parent of MathAgent) already implements all protocol requirements:
  - Identity: `id_hash`, `push_counter`
  - Ownership: `user_id`, `session_id`, `routing_command`, `user_email`
  - Timestamps: `run_date`, `created_date`, `started_at`, `completed_at`
  - Question/Answer: `question`, `last_question_asked`, `answer`, `answer_conversational`
  - Type: `job_type` (property returning class name)
  - Status: `is_cache_hit`, `status`, `error`
  - Methods: `do_all()`, `code_ran_to_completion()`, `formatter_ran_to_completion()`

**Bug Fix Queue Status**: Empty (all bugs resolved or verified)

### Session 129 Summary
- **Total Items Verified/Fixed**: 3
  1. Notifications UI cleanup → commit: 425568a
  2. CJ flow compliance → Verified working (no changes)
  3. MathAgent protocol → commit: 34f4874 (docs-only)
- **Files Changed**: 2 (notifications.html, notifications.js)
- **Commits**: 425568a, 34f4874
- **Status**: Session closed 2026.02.04

---

### 2026.02.04 - Session 129 | Notifications UI Claude Code Submission Cleanup

**Accomplishments**:
- Replaced cluttered radio buttons with two compact dropdown selects
- Task Type dropdown: "Bounded" / "Unbounded (Interactive)"
- Flow Type dropdown: "CJ Flow" (default) / "Socket"
- Added CJ Flow branding: "Cosa Jobs Flow: Current States" for Job Queues section
- Updated JavaScript selectors from radio to select elements

**Files Modified**:
- `src/fastapi_app/static/html/notifications.html` - Dropdown UI, CJ Flow title
- `src/fastapi_app/static/js/notifications.js` - Updated selectors and event listeners

**Bug Fixed**: Notifications UI Claude Code submission layout clumsy (bug-fix-queue.md)

---

### 2026.02.03 - Session 128 | Planning Workflow Installation Wizard

**Accomplishments**:
- Ran `/plan-install-wizard` to check for missing planning-is-prompting workflows
- Installed new `/plan-session-checkpoint` command (mid-session commits)
- Lupin project now has complete 29/29 workflow coverage

**Files Modified**:
- `.claude/commands/plan-session-checkpoint.md` - NEW: Mid-session commit workflow

**Session Checkpoint Use Cases**:
- Save progress during long work sessions (2+ hours)
- Commit before anticipated context clear
- Create save points while continuing work

---

### 2026.02.03 - Session 126 (cont.) | Job Card Disappearing Bug Fix

**Bug**: Job cards disappeared after `refreshAllQueues()` was called, showing "No jobs in this queue" despite API returning correct data.

**Root Cause**: Two field name mismatches in `notifications.js`:
1. `loadQueueJobCards()` used `jobsHtml.length` but API returns `*_jobs_metadata` not `*_jobs`
2. `processQueueUpdate()` used `data.{queue}_jobs.length` but API returns `total_jobs` count

**Files Modified**:
- `src/fastapi_app/static/js/notifications.js` - Fixed field references in `loadQueueJobCards()` (lines 4789-4793) and `processQueueUpdate()` (lines 4532-4565)

**Testing**: Submit Claude Code dry-run job → Job card appears and persists after queue refresh

---

### 2026.02.03 - Session 126 | Mock Claude Code Job + Dry-Run Support

**Accomplishments**:
- Implemented dry-run mode for ClaudeCodeJob (matching Deep Research/Podcast patterns)
- Fixed blocking import bug in `claude_code_queue.py` (ModuleNotFoundError)
- Created dedicated `voice_io.py` wrapper for Claude Code agent
- Added dry-run checkbox to notifications UI (checked by default)

**Files Modified (Lupin)**:
- `src/fastapi_app/static/html/notifications.html` - Added dry-run checkbox
- `src/fastapi_app/static/js/notifications.js` - Pass dry_run to queue submission

**Files Modified (CoSA)** - Requires separate commit:
- `src/cosa/rest/routers/claude_code_queue.py` - Fixed import bug, added dry_run field
- `src/cosa/agents/claude_code/job.py` - Added dry_run param, _execute_dry_run() method
- `src/cosa/agents/claude_code/voice_io.py` - NEW: Voice I/O wrapper

**Smoke Tests**: All passing (router + job)

---

### 2026.02.03 - Session 127 | WebSocket JWT Auth Fix & PR Merge Requirements

**Accomplishments**:
- Fixed WebSocket smoke tests to use JWT authentication instead of deprecated mock tokens
- WebSocket tests now 100% passing (50/50) - up from 46% (23/50)
- Removed stale "92% pass rate" from documentation
- Added PR MERGE REQUIREMENTS section to CLAUDE.md

**Files Modified**:
- `src/tests/websocket_smoke/infrastructure/smoke_test_runner.py` - JWT auth (2 locations)
- `src/tests/websocket_smoke/core/test_authentication_flow.py` - JWT auth (~10 locations)
- `src/tests/websocket_smoke/core/test_session_management.py` - JWT auth (~13 locations)
- `src/tests/websocket_smoke/core/test_event_system.py` - JWT auth (~10 locations)
- `CLAUDE.md` - Removed pass rate, added PR MERGE REQUIREMENTS section
- `src/tests/README.md` - Removed stale pass rate

**Test Results**:
| Category | Before | After |
|----------|--------|-------|
| Core | 19/25 (76%) | 25/25 (100%) |
| Integration | 2/22 (9%) | 22/22 (100%) |
| Performance | 2/2 (100%) | 2/2 (100%) |
| Load | 0/1 (0%) | 1/1 (100%) |
| **Total** | **23/50 (46%)** | **50/50 (100%)** |

---
## Navigation

### Archive Links
- **[Jan 19 - Feb 2, 2026](history/2026-01-19-to-02-02-history.md)** - Sessions 57-124: Podcast Generator Phase 2, Deep Research CLI UX, LORA Training Integration, Test Suite Remediation, Cache Freshness, Queue Protocol Refactoring
- **[Jan 13-19, 2026](history/2026-01-13-to-19-history.md)** - Sessions 56-74b: Conversation Identity, Deep Research Agent, Podcast Generator Phase 1, Job Queue Progressive Disclosure UI
- **[Nov 23, 2025 - Jan 12, 2026](history/2025-11-23-to-2026-01-12-history.md)** - Sessions 7-55: MCP Voice, Directory Rename, Claude Code Dispatcher
- **[Oct 16 - Nov 22, 2025](history/2025-10-16-to-11-22-history.md)** - Sessions 1-6: Admin Dashboard, LanceDB, PostgreSQL Migration
- **[Oct 16-30, 2025](history/2025-10-16-to-30-history.md)** - SSE Notification System Phase 2
- **[Oct 1-15, 2025](history/2025-10-01-to-15-history.md)** - JWT/OAuth, User Filtering
- **[Sep 3-23, 2025](history/2025-09-03-to-23-history.md)** - History Management, WebSocket Architecture
- **[August 2025](history/2025-08-history.md)** - TTS Streaming, Audio Pipeline, WebSocket Enhancements
- **[July 2025](history/2025-07-history.md)** - Progressive TTS, User Routing Architecture
- **[June 2025](history/2025-06-history.md)** - Lupin Renaming, Notification System Foundation
- **[May 2025 and Earlier](history/2025-05-and-earlier-history.md)** - PEFT Training, Agent Migrations, Flask to FastAPI
- **[Archive Index](history/README.md)** - Full archive listing with descriptions

### Implementation Documents
- **Current Focus**: Cold Call Flow Path 1 - Claude Code UI Card Testing
- **Path 1 Plan**: `src/rnd/2026.01.08-cold-call-path-1-ui-card-plan.md`
- **Cold Call Flow Planning (updated)**: `src/rnd/2025.12.31-claude-code-via-mcp-and-cosa-vox/2026.01.02-03-cold-call-flow-planning.md`
- **Session 47 Plan File**: `/home/rruiz/.claude/plans/expressive-plotting-charm.md`
- **Project Status Overview**: `/home/rruiz/.claude/plans/clever-napping-clover.md`

### Quick Navigation
- **Run FastAPI server**: `src/scripts/run-fastapi-lupin.sh` (port 7999)
- **Run GUI client**: `src/scripts/run-lupin-gui.sh`
- **Integration tests**: `./src/tests/run-integration-tests.sh -v`
- **Smoke tests**: `src/scripts/run-websocket-smoke-tests.sh`

### Current Development Areas
- Directory Rename (COMPLETE - genie-in-the-box → lupin, Sessions 36-40)
- MCP Voice Integration (COMPLETE - Phases 1-5)
- Option A Dispatcher (COMPLETE - ClaudeCodeDispatcher working)
- Cold Call Flow Path 1 (IMPLEMENTED - UI Card needs testing, Session 47)
- Cold Call Flow Path 2 (DEFERRED - Intent parsing after Path 1 proven)
- Notifications UI (ONGOING - polish and improvements)
