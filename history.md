# Lupin Project History

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

> **✅ SESSION 124 COMPLETE**: Unified LoRA Training Integration (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#02ebea7d
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
>
> **Integrated 3 agentic job intents into unified LoRA training pipeline**:
> - `agent router go to deep research`
> - `agent router go to podcast generator`
> - `agent router go to research to podcast`
>
> **Changes Made**:
> 1. Created 3 synthetic data files for agentic commands (50 templates each)
> 2. Added agentic commands to `_get_simple_agent_router_commands()` in xml_prompt_generator.py
> 3. Updated `build_all_training_prompts()` to include agentic jobs parameter
> 4. Updated `build_agentic_job_training_prompts()` to use shared agent router instruction template
> 5. Updated `run-agentic-intent-training.sh` for unified approach
>
> **Results**:
> | Metric | Before | After |
> |--------|--------|-------|
> | Total training examples | ~38,000 | 40,258 |
> | Agentic train examples | 240 (isolated) | 600 (unified) |
> | Commands in agentic instruction | 3 | 10 (all agent router commands) |
>
> **Files Created (Lupin)**:
> - `src/ephemera/prompts/data/synthetic-data-agent-routing-deep-research.txt`
> - `src/ephemera/prompts/data/synthetic-data-agent-routing-podcast-generator.txt`
> - `src/ephemera/prompts/data/synthetic-data-agent-routing-research-to-podcast.txt`
> - `src/rnd/2026.02.02-unified-lora-training-integration-plan.md`
>
> **Files Modified (Lupin)**:
> - `src/scripts/run-agentic-intent-training.sh` (+74/-14)
> - `src/ephemera/prompts/data/voice-commands-xml-{train,test,validate}.jsonl` (regenerated)
> - `src/ephemera/prompts/data/agentic-job-xml-{train,test,validate}.jsonl` (regenerated)
>
> **Files Modified (CoSA)** - Requires separate commit:
> - `src/cosa/training/xml_prompt_generator.py` - Added 3 agentic commands
> - `src/cosa/training/xml_coordinator.py` - Added agentic jobs to unified pipeline
>
> ---

> **✅ SESSION 123 COMPLETE**: Test Suite Remediation - Phase 3 (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#d1c3ccff
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Test Suite Remediation Complete
>
> **Problem**: Baseline report showed 61 failing tests (76.8% overall pass rate). All failures were test infrastructure issues, not production bugs.
>
> **Final Results**:
> | Category | Original | After Phase 1-2 | After Phase 3 |
> |----------|----------|-----------------|---------------|
> | Unit Tests | 168/199 (84.4%) | 190/199 (95.5%) | **195/195 (100%)** ✅ |
>
> **Phase 3 Fixes Applied**:
> 1. **JWT Timing** (2 tests): Fixed `fromtimestamp()` → `utcfromtimestamp()` for UTC consistency
> 2. **Config Loader** (2 tests): Added `monkeypatch.delenv('LUPIN_ENV')` for test isolation
> 3. **Notifications API** (1 test): Added `patch('fastapi_app.main.config_mgr')` for proper mocking
> 4. **Debug Scripts** (4 files): Moved non-test scripts from `tests/unit/` to `scripts/debug/`
>
> **Files Modified**:
> - `src/tests/unit/test_jwt_service.py` - UTC timestamp fix
> - `src/tests/unit/test_config_loader.py` - LUPIN_ENV cleanup
> - `src/tests/unit/test_notifications_api.py` - config_mgr mock
> - `src/rnd/2026.02.02-test-suite-remediation-plan.md` - Updated status
>
> **Files Moved** (via git mv):
> - `test_queue_endpoint_simple.py` → `src/scripts/debug/debug_queue_endpoint.py`
> - `test_queue_state_monitoring_debug.py` → `src/scripts/debug/debug_queue_state_monitoring.py`
> - `test_simple_websocket_connection.py` → `src/scripts/debug/debug_websocket_connection.py`
> - `test_websocket_auth_validation_simple.py` → `src/scripts/debug/debug_websocket_auth_validation.py`
>
> ---

> **✅ SESSION 122 COMPLETE**: Cache Freshness Fix - Simple Approach (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#4949b964
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Bug Fix
>
> **Problem**: Cache hits returned stale `answer_conversational` for time-sensitive queries like "What time is it?" - the cached time was returned instead of re-executing the stored code.
>
> **Solution**: Added code re-execution in `_format_cached_result()` (lines 689-699) that runs `cached_snapshot.run_code()` and `cached_snapshot.run_formatter()` before returning.
>
> **Trade-off Accepted**: Math queries like "4+4" will also re-execute (~100ms overhead) but this is harmless - correctness trumps minor performance cost.
>
> **Files Modified (CoSA)**:
> - `src/cosa/rest/running_fifo_queue.py:689-699` - Added 10 lines for code re-execution
>
> **Testing**:
> - Smoke tests: 9/9 PASS
> - Unit tests: Module imports verified
> - Manual testing: Pending (ask "What time is it?" twice)
>
> **Commit**: 3cff850 (Lupin), CoSA pending
>
> ---

> **✅ SESSION 121 COMPLETE**: Cache Freshness Policy Planning (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#49a88ad2
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
>
> **Bug Analysis**: Investigated cache hit behavior in `running_fifo_queue.py:_format_cached_result()` - returns cached `answer_conversational` without re-executing code, breaking time-sensitive queries.
>
> **Design Decision**: Binary freshness policy (IMMUTABLE/VOLATILE) - no TTL complexity.
>
> **Implementation Plan Created**: Comprehensive 4-phase implementation plan:
> - **Phase 1**: Foundation - `cache_freshness_policy.py`, SolutionSnapshot field, LanceDB schema, config keys
> - **Phase 2**: Agent integration - property overrides in DateAndTimeAgent (VOLATILE), MathAgent (IMMUTABLE), WeatherAgent (VOLATILE)
> - **Phase 3**: Enforcement - `_is_cache_immutable()` and `_handle_volatile_cache()` in running_fifo_queue.py
> - **Phase 4**: Semantic match confirmation (deferred)
>
> **Key Design Elements**:
> - Three-tier policy resolution: explicit > auto-detect > agent default
> - Code pattern detection for datetime.now(), requests.*, pd.read_csv
> - Feature flag (OFF by default) for backward compatibility
>
> **Files Created**:
> - `src/rnd/2026.02.02-cache-freshness-implementation-plan.md` (~400 lines)
>
> **Status**: Planning complete, ready for implementation
>
> ---

> **✅ SESSION 120 COMPLETE**: Agentic Job Intent LORA Training - Chunk 1.5 (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#379d8015
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
>
> **Chunk 1.5: Added Argument Extraction Ground Truth**
>
> Fixed training data generation to include extracted arguments as ground truth labels. Previously, all training examples had empty `<args></args>` fields - the model could learn intent classification but not parameter extraction.
>
> **Changes Made**:
> - Changed `args_template: ""` → `args_key: "topic"` for deep research and podcast generator commands
> - Changed `args_template: ""` → `args_key: "document_path"` for research-to-podcast command
> - Updated generation logic to dynamically populate args when placeholder is substituted
> - Templates without placeholders correctly produce empty args (intent-only classification)
>
> **Training Data Stats**:
> - 300 examples regenerated (240 train / 30 test / 30 validate)
> - 180 examples with populated args (75%)
> - 60 examples with empty args (25%) - templates without placeholders
>
> **Example Outputs**:
> ```xml
> <args>topic="space exploration and Mars colonization"</args>
> <args>document_path="/io/deep-research/social-media-analysis.md"</args>
> <args></args>  <!-- intent-only, no placeholder in template -->
> ```
>
> **Files Modified (CoSA)** - Requires separate commit:
> - `src/cosa/training/xml_coordinator.py` (lines 652-700, 741-753)
>
> **Files Modified (Lupin)**:
> - `src/rnd/2026.02.02-agentic-job-intent-lora-training.md` - Status and session log updated
> - `src/ephemera/prompts/data/agentic-job-xml-{train,test,validate}.jsonl` - Regenerated
> - `TODO.md` - Added 3 future enhancements (Extended Parameters, Dual Argument Types, Disambiguation Agent)
>
> **Next**: Run 1% sample training when GPUs available: `./src/scripts/run-agentic-intent-training.sh test`
>
> ---

> **✅ SESSION 119 COMPLETE**: Agentic Job Intent LORA Training - Chunk 1 (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#379d8015
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
>
> **Phase 1.0: Code Cleanup - Removed `gpt_message` field**
> - Removed `_get_gpt_messages_dict()` method and all GPT training file generation
> - Changed `_get_6_empty_lists()` to `_get_5_empty_lists()`
> - Simplified all 4 build methods in `xml_coordinator.py`
> - Removed `format_gpt_message()` from `xml_prompt_generator.py`
> - Removed `extract_gpt_message` parameter from `peft_trainer.py`
>
> **Phase 1.1: Created 8 placeholder files** for agentic job training data:
> - `placeholders-research-topics.txt` (50 entries)
> - `placeholders-budget-values.txt` (7 entries)
> - `placeholders-language-codes.txt` (7 entries)
> - `placeholders-document-paths.txt` (24 entries)
> - `placeholders-audience-levels.txt` (4 entries)
> - `placeholders-audience-contexts.txt` (24 entries)
> - `placeholders-max-segments.txt` (5 entries)
> - `placeholders-agentic-templates.txt` (35 entries)
>
> **Phase 1.2: Updated training infrastructure**
> - Added 3 new commands to `xml_models.py`: `agent router go to deep research`, `agent router go to podcast generator`, `agent router go to research to podcast`
> - Added 8 placeholder getter methods to `xml_prompt_generator.py`
> - Added `build_agentic_job_training_prompts()` method to `xml_coordinator.py`
> - Added `get_agentic_job_train_test_validate_split()` and `write_agentic_job_ttv_split_to_jsonl()` methods
>
> **Phase 1.3-1.4: Generated and validated training data**
> - Generated 300 training examples (240 train, 30 test, 30 validate)
> - Balanced command distribution: 80/80/80 per command
> - All JSONL files validated with 5 required fields
>
> **Phase 2.1: Created training shell script**
> - `run-agentic-intent-training.sh` with generate/validate/test/full modes
>
> **Phase 2.2: BLOCKED** - Requires GPU resources to be freed
>
> **Files Modified (CoSA)**:
> - `src/cosa/training/xml_coordinator.py`
> - `src/cosa/training/xml_prompt_generator.py`
> - `src/cosa/training/peft_trainer.py`
> - `src/cosa/agents/io_models/xml_models.py`
>
> **Files Created**:
> - 8 placeholder files in `src/ephemera/prompts/data/`
> - 3 JSONL training files: `agentic-job-xml-{train,test,validate}.jsonl`
> - `src/scripts/run-agentic-intent-training.sh`
>
> **Smoke Tests**: All pass (xml_coordinator, xml_models, peft_trainer structural)
>
> ---

> **✅ SESSION 118 COMPLETE**: Skills Management Commands Installation + Discovery (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#7eeef663
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
>
> **Skills Management Slash Commands Installed**:
> Installed 5 mode-specific skills management slash commands from planning-is-prompting repo, adapted for LUPIN project:
> - `/plan-skills-management-discover` - Find skill candidates in documentation
> - `/plan-skills-management-create` - Build new skill from documentation
> - `/plan-skills-management-edit` - Update existing skill
> - `/plan-skills-management-audit` - Check skills health against documentation
> - `/plan-skills-management-delete` - Remove obsolete skill
>
> **Files Created**:
> - `.claude/commands/plan-skills-management-discover.md`
> - `.claude/commands/plan-skills-management-create.md`
> - `.claude/commands/plan-skills-management-edit.md`
> - `.claude/commands/plan-skills-management-audit.md`
> - `.claude/commands/plan-skills-management-delete.md`
>
> **Skills Discovery Run**:
> Executed discovery workflow and identified 3 new skill candidates (added to TODO.md):
> - **notification-patterns** (HIGH) - cosa-voice MCP usage patterns (~250 lines)
> - **path-management** (MEDIUM) - `cu.get_project_root()` vs bootstrap (~150 lines)
> - **code-style-preferences** (LOW) - Spacing, alignment, getattr prohibition (~100 lines)
>
> **Files Modified**:
> - `TODO.md` - Updated session number, added skill candidates section
>
> ---

> **✅ SESSION 117 COMPLETE**: Fix Podcast Generator Dry-Run Notifications (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#8594147a
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Bug Fix
> Podcast Generator dry-run notifications not routing to job cards in notifications UI.
>
> **Root Cause**: Notifications in `_execute_dry_run()` were missing `job_id` parameter.
>
> **Fix**: Added `job_id=self.id_hash` to all 6 notifications (5 breadcrumbs + 1 completion).
>
> **Files Modified (CoSA)**:
> - `src/cosa/agents/podcast_generator/job.py` - Lines 284, 288, 292, 296, 300, 329-334
>
> **Verification**: Smoke test passes
>
> ---

> **✅ SESSION 116 COMPLETE**: Fuzzy File Matching + util_xml.py Deprecation (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#817f2e64
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
>
> **Part 1: Fuzzy File Matching for Podcast Generator**
> - Added `FuzzyFileMatchResponse` Pydantic XML model with `get_example_for_template()` and `get_matches_list()` helpers
> - Integrated with `PromptTemplateProcessor` for automatic XML example injection
> - Rewrote `match_research_docs()` to use LlmClientFactory with kaitchup/phi_4_14b
> - Changed Flow B to block for user selection (was fire-and-forget notification)
>
> **Part 2: DEPRECATED util_xml.py - Pydantic-Only Migration**
> Eliminated all production usage of deprecated `cosa/utils/util_xml.py` in favor of Pydantic XML I/O.
>
> **Phase 1**: Removed fallbacks from Pydantic-enabled code
> - `gister.py`, `confirmation_dialog.py` - Now Pydantic-only, no baseline fallback
>
> **Phase 2**: Added Pydantic to queue/router code
> - `todo_fifo_queue.py`, `multimodal_munger.py` - Replaced `dux.get_value_by_xml_tag_name()` with `CommandResponse.from_xml()`
>
> **Phase 3**: Migrated agent classes
> - `agent_base.py` - Removed ALL deprecated fallback code
> - `bug_injector.py`, `raw_output_formatter.py` - Removed fallbacks
>
> **Phase 4**: Updated parser factory
> - `xml_parser_factory.py` - **COMPLETELY REWRITTEN**: Removed `BaselineXmlParsingStrategy`, `HybridXmlParsingStrategy`, `XmlParsingStrategy` abstract base. Only `PydanticXmlParser` remains.
>
> **Phase 5**: Added deprecation warnings
> - `util_xml.py` - Module-level and per-function deprecation warnings
> - Added `remove_xml_escapes()` to `util_xml_pydantic.py`
>
> **Additional cleanup**: Removed unused imports from `iterative_debugging_agent.py`, `solution_snapshot.py`, `math_agent.py`
>
> **Verification**: All smoke tests pass (gister, confirmation_dialog, xml_parser_factory)
>
> **Files Modified (CoSA)**: 12 files
> - `cosa/memory/gister.py`
> - `cosa/agents/confirmation_dialog.py`
> - `cosa/rest/todo_fifo_queue.py`
> - `cosa/rest/multimodal_munger.py`
> - `cosa/agents/agent_base.py`
> - `cosa/agents/bug_injector.py`
> - `cosa/agents/raw_output_formatter.py`
> - `cosa/agents/io_models/utils/xml_parser_factory.py`
> - `cosa/utils/util_xml.py`
> - `cosa/agents/io_models/utils/util_xml_pydantic.py`
> - `cosa/agents/iterative_debugging_agent.py`
> - `cosa/memory/solution_snapshot.py`
> - `cosa/agents/math_agent.py`
>
> ---

> **✅ SESSION 115 COMPLETE**: Push Method Bug Fix + Smoke Tests (2026.02.02)
> **Owner**: claude.code@lupin.deepily.ai#8594147a
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
> Fixed `push_job()` → `push()` method bug in Podcast Generator and Research→Podcast routers.
>
> **Root Cause**: Routers called `todo_queue.push_job( job, user_id, session_id )` which expects a string question, not a pre-built job object. Also used non-existent `get_position()` method.
>
> **Fix Applied**:
> - Import `user_job_tracker` from `cosa.rest.queue_extensions`
> - Associate user/session BEFORE push (race condition prevention)
> - Use `todo_queue.push( job )` for pre-built job objects
> - Use `todo_queue.size()` instead of `get_position()`
>
> **Files Modified (COSA)**:
> - `src/cosa/rest/routers/podcast_generator.py` (+8/-2 lines)
> - `src/cosa/rest/routers/deep_research_to_podcast.py` (+8/-2 lines)
>
> **Files Created (Lupin)**:
> - `src/tests/smoke/test_research_to_podcast_dry_run_smoke.py` - New smoke test for rp- prefix jobs
>
> **Files Modified (Lupin)**:
> - `src/tests/smoke/test_podcast_generator_dry_run_smoke.py` - Fixed None abstract handling
>
> **Verification** (all 3 dry-run smoke tests pass):
> - ✓ Deep Research: dr-6aa5d16d completed in 10s, $0.00 cost
> - ✓ Podcast Generator: pg-dd026977 completed in 10s, $0.00 cost
> - ✓ Research→Podcast: rp-221fe28e completed in 14s, $0.00 cost
>
> **Commits**: eab45bf (partial), pending (smoke test + docs)
>
> ---

> **✅ SESSION 114 COMPLETE**: Bug Fix Mode (2026.01.31 - 2026.02.01)
> **Owner**: claude.code@lupin.deepily.ai#42b5bbd7
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Fixes
> - **Fix 1**: Consolidate voice recording toggle handlers
>   - **Symptom**: Podcast Generator recording button stuck in recording mode (clicking doesn't stop)
>   - **Root Cause**: `handleSTTButtonClick()` missing toggle logic - just called `startRecording()` directly
>   - **Fix**: Added toggle logic to `handleSTTButtonClick()` (if recording → stop, else if not processing → start)
>   - **Cleanup**: Converted `handleQASTTButtonClick()` and `handleCCSTTButtonClick()` from duplicate implementations (~28 lines total) to thin wrappers (~8 lines total)
>   - **Files (Lupin)**: `src/fastapi_app/static/js/notifications.js`
>   - **Test**: Browser verification needed (Ctrl+Shift+R to hard refresh)
>   - **Commit**: f4f6cc8
>
> ### Session Summary
> - **Total Fixes**: 1
> - **Files Changed**: `src/fastapi_app/static/js/notifications.js`
> - **Commits**: f4f6cc8
>
> **Status**: Session closed 2026.02.01
>
> ---

> **✅ SESSION 113 COMPLETE**: Bug Fix Mode - Deep Research Dry-Run Smoke Test (2026.01.31)
> **Owner**: claude.code@lupin.deepily.ai#d9d74b04
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
> Implemented plan from plan mode for Deep Research dry-run smoke test and bug fix verification.
>
> **Findings**:
> - **Bug fix already applied**: The `SessionSummary` dataclass fix in `job.py:396-401` was already implemented (replacing the mock `type()` object that didn't serialize to JSON)
> - **Smoke test already exists**: `src/tests/smoke/test_deep_research_dry_run_smoke.py` (~250 lines) was already created with full test coverage
> - **Test not executed**: Deferred to next session due to time constraints
>
> **Documentation Updates**:
> - Updated `TODO.md` with priority item to run dry-run smoke test
> - Added future consideration: Silent flag for notifications during automated testing
>
> ### Session Summary
> - **Total Fixes**: 0 (bug already fixed in prior session)
> - **Files Changed**: `TODO.md` (2 edits)
> - **Commits**: None (documentation-only session)
> - **Test Status**: Pending - deferred to next session
>
> **Status**: Session closed 2026.01.31
>
> ---

> **✅ SESSION 112 COMPLETE**: Deep Research Protocol Compliance Fix (2026.01.30)
> **Owner**: claude.code@lupin.deepily.ai#bd42074b
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
> Fixed Deep Research job submission failure: "Job must implement QueueableJob protocol, got DeepResearchJob"
>
> **Root Cause**: `QueueableJob` protocol (expanded in Session 111) requires `is_cache_hit: bool`, but `AgenticJobBase` was missing this attribute. The protocol had `is_cacheable` (property returning False) but not `is_cache_hit` (instance attribute).
>
> **Fix**: Added `self.is_cache_hit = False` to `AgenticJobBase.__init__()` with comment "Agentic jobs are never cache hits"
>
> **Verification**: All smoke tests pass:
> - `deep_research` router import: OK
> - `AgenticJobBase` smoke test: 8/8 tests passed
> - `QueueableJob` protocol smoke test: All tests passed
> - Protocol compliance check: `is_queueable_job()` returns True
>
> **Files Modified (COSA)**:
> - `src/cosa/agents/agentic_job_base.py` (+1 line)
>
> **Commit**: 0e0ecfc (Lupin tracking), COSA pending
>
> ---
>
> **✅ SESSION 111 COMPLETE**: Defensive Attribute Access Refactoring (2026.01.30)
> **Owner**: claude.code@lupin.deepily.ai#bd42074b
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Accomplishments
> Implemented Phases 1-4 of the defensive attribute access refactoring plan to replace fragile `getattr()`/`hasattr()` patterns with trusted Protocol-based direct attribute access.
>
> **Phase 1 - Enforce Protocol at Boundaries**:
> - Added `is_queueable_job()` validation in `FifoQueue.push()` method
> - Objects are now validated ONCE on queue entry, enabling downstream code to trust the interface
>
> **Phase 2 - Replace getattr Chains (~89 replacements)**:
> - `running_fifo_queue.py`: ~62 replacements across 6 metadata construction blocks
> - `queue_consumer.py`: 7 replacements in `consumer_worker()`
> - `todo_fifo_queue.py`: 8 replacements in `push()` metadata
> - `queues.py`: 12 replacements in done queue endpoint
>
> **Phase 3 - Replace hasattr with isinstance**:
> - Replaced `hasattr(job, 'JOB_TYPE') and hasattr(job, 'artifacts')` duck-typing
> - Now uses explicit `isinstance(job, AgenticJobBase)` type check
>
> **Phase 4 - Protocol Expansion**:
> - Added 6 missing attributes to QueueableJob Protocol: `user_email`, `started_at`, `completed_at`, `is_cache_hit`, `status`, `error`
> - Updated smoke test mocks to implement full Protocol
>
> **Verification**: All 5 smoke tests pass (queue_protocol, fifo_queue, todo_fifo_queue, running_fifo_queue, queue_consumer)
>
> **Documentation**: Created `src/rnd/2026.01.30-defensive-attribute-access-anti-pattern.md` with implementation addendum
>
> **Files Modified (COSA - pending commit)**:
> - `fifo_queue.py`, `todo_fifo_queue.py`, `running_fifo_queue.py`, `queue_consumer.py`
> - `routers/queues.py`, `queue_protocol.py`
> - 7 agent files (agent_base.py + 6 traditional agents) - from earlier user_email work
> - `solution_snapshot.py` - from earlier user_email work
>
> ---
>
> **✅ SESSION 110 COMPLETE**: Bug Fix Mode (2026.01.30)
> **Owner**: claude.code@lupin.deepily.ai#bd42074b
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Fixes
> - **Fix 1**: Unknown badge for WebSocket-created job cards
>   - **Symptom**: Badge shows "Unknown" instead of "Math" when jobs transition via WebSocket (works after page reload)
>   - **Root Cause**: Defensive `getattr()` chains masked missing implementation; e.g., `getattr(job, 'agent_class_name', getattr(job, 'JOB_TYPE', 'Unknown'))`
>   - **Fix**: All queueable objects implement `job_type` property - replaced 8 defensive chains with direct `job.job_type` access
>   - **Files (COSA)**: `queue_consumer.py`, `todo_fifo_queue.py`, `running_fifo_queue.py`
>   - **Test**: Smoke tests PASS (all 3 files)
>   - **Commit**: f8e3bda (Lupin tracking), COSA pending
>
> - **Fix 2**: user_email injection refactoring
>   - **Problem**: Ugly attribute injection `agent.user_email = user_email` after instantiation
>   - **Fix**: Added `user_email` as first-class constructor parameter to AgentBase, all 6 traditional agents, and SolutionSnapshot
>   - **Files (COSA)**: `agent_base.py`, `math_agent.py`, `calendaring_agent.py`, `weather_agent.py`, `receptionist_agent.py`, `todo_list_agent.py`, `date_and_time_agent.py`, `solution_snapshot.py`, `todo_fifo_queue.py`, `fifo_queue.py`
>   - **Test**: Smoke tests PASS, syntax validation PASS
>   - **Commit**: 7243a31 (Lupin tracking), COSA pending
>
> ### Session Summary
> - **Total Fixes**: 2 (+ Session 111 defensive refactoring + Session 112 protocol fix)
> - **Files Changed**: Multiple COSA files (pending commit in COSA context)
> - **Commits (Lupin)**: f8e3bda, 7243a31, 9ddfa99, 2da5467
> - **Status**: Bug fix session closed 2026.01.30
>
> ---

> **✅ SESSION 109 COMPLETE**: Bug Fix Mode (2026.01.29)
> **Owner**: claude.code@lupin.deepily.ai#0bd32185
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Fixes
> - **Fix 1**: Math Agent TTS - job_id pattern validation ✅ VERIFIED
>   - **Symptom**: Math agents produced no TTS; Pydantic validation error on compound hash job_id
>   - **Root Cause**: `notification_models.py` job_id pattern didn't accept `SHA256::UUID` compound format
>   - **Fix**: Updated regex to accept compound hashes: `^([a-z]+-[a-f0-9]{8}|[a-f0-9]{64}(::[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?)$`
>   - **File**: `src/cosa/cli/notification_models.py` (2 locations: NotificationRequest, AsyncNotificationRequest)
>
> - **COSA Changes** (pending commit in COSA repo):
>   - Added `user_email` parameter to `push_job()` and `_queue_best_snapshot()`
>   - Simplified `_notify()` with direct `target_user` parameter
>   - Removed `_get_target_user_email()` method (47 lines deleted)
>   - Set `user_email` on agents/jobs at creation time for TTS routing
>
> ### Session Summary
> - **Total Fixes**: 1 (Math Agent TTS)
> - **Files Changed**: 5 (1 Lupin tracking, 4 COSA pending)
> - **Commits (Lupin)**: f0a5c33, 7736b44, bce5639
> - **Queued for Tomorrow**: 2 bugs (user_email refactoring, unknown badge fix)
>
> **Status**: Session closed 2026.01.29
>
> ---

> **✅ SESSION 108 COMPLETE**: Bug Fix Mode + Math Agent TTS Investigation (2026.01.29)
> **Owner**: claude.code@lupin.deepily.ai#21a62c05
> **Branch**: `wip-v0.1.3-2026.01.29-spit-and-polish-for-agentic-jobs-and-notifications-ui`
>
> ### Fixes
> - **Fix 1**: Job card styling inconsistency (WebSocket vs server-fetched)
>   - **Symptom**: Done queue cards looked different when inserted via WebSocket vs fetched from server
>   - **Root Cause**: `insertJobMetadata()` used raw HTML instead of CSS-classed structure from `renderJobCard()`
>   - **Fix**: Extracted `renderAbstractSection()` and `renderReportLinkSection()` helpers; unified rendering
>   - **File**: `src/fastapi_app/static/js/notifications.js`
>
> - **Fix 2**: Badge/card count mismatch in queue updates
>   - **Symptom**: Badge showed correct count but cards didn't match after WebSocket updates
>   - **Fix**: Synchronized badge and card rendering in queue update handlers
>
> ### Investigation: Math Agent TTS Not Working
> - **Symptom**: Math jobs complete successfully but produce NO TTS audio (mock jobs DO work)
> - **Root Cause Identified**: Two issues found:
>   1. **Race Condition** (Fixed in earlier commit): `associate_job_with_user()` called AFTER `push()` - consumer thread could grab job before user mapping existed
>   2. **Missing user_email Attribute** (Pending fix): Math agents lack `user_email` attribute that mock jobs have, causing TTS to route to wrong user (falls back to default email)
> - **R&D Document**: `src/rnd/2026.01.29-math-agent-tts-bug-investigation.md`
> - **Implementation Plan**: Look up `user_email` in `push_job()`, set on agents at creation time
>
> ### Workflow Installation
> - Installed `/plan-bug-fix-mode-wrap` slash command (was missing from Lupin)
>
> ### Session Summary
> Fixed job card UI issues, investigated Math Agent TTS bug to root cause, documented findings with implementation plan for next session.
>
> ---

> **✅ SESSION 107 COMPLETE**: job_state_transition WebSocket Event (2026.01.28)
> **Owner**: claude.code@lupin.deepily.ai
> **Branch**: `wip-v0.1.2-2026.01.28-job-state-change-refactoring`
>
> ### Problem Solved
>
> Job cards get stuck in run queue after completion because existing `queue_*_update` events only signal count changes, not which specific job moved. **Fixed** with new `job_state_transition` event that sends job-specific metadata on every queue transition.
>
> ### Accomplishments
>
> **Git Workflow**:
> - Created PR #10 for v0.1.1 merge to main (156 files, +42k/-8k lines)
> - Created development branch `wip-v0.1.2-2026.01.28-job-state-change-refactoring`
>
> **Server-Side** (Phases 1-3 Complete):
> - Added `job_state_transition` WebSocket event to config
> - Created `queue_util.py` with standalone `emit_job_state_transition()` utility
> - Implemented 8 emission calls at queue transition points
> - Added 6 fields to WebSocket metadata: status, has_interactions, is_cache_hit, started_at, completed_at, duration_seconds
>
> **Client-Side** (Phases 4-10 Complete):
> - Added event subscription and handler `handleJobStateTransition()`
> - Implemented DOM reparenting for card movement between queues via `insertJobMetadata()`
> - Changed `queue_*_update` handlers to badge-only updates
> - Added 5 missing fields to JS job object for field parity with server-fetched cards
> - Removed cruft: data structures, methods, logic from legacy approach
>
> **Bug Fix**: Job card field parity (WebSocket vs server-fetched)
> - Cards created via WebSocket now have same fields as server-fetched cards
> - Fields added: completed_at, status, error, has_interactions, duration_seconds
>
> **Documentation**:
> - Created `src/rnd/job-state-transition/` with 6 tracking documents
> - Added research doc on large repo documents as skills
>
> ### Commits
> - `e9c8a51` - Session 107: job_state_transition Phases 1-3 server complete
> - `75f0593` - Session 107: Trim history entry, update phase tracking
> - `247c08b` - Add 4 Agent Skills for intent-based knowledge activation
> - `57a9fbb` - Session 107: Fix job card field parity (WebSocket vs server-fetched)
>
> ### Pending (CoSA Submodule)
> - `running_fifo_queue.py` - Server-side WebSocket metadata (6 fields)
> - `queue_consumer.py`, `todo_fifo_queue.py` - Related queue changes
> - `queue_util.py` - New file for emit utility
>
> ---

> **✅ SESSION 106 COMPLETE**: API Consistency + Job Notification Routing (2026.01.27)
> **Owner**: claude.code@lupin.deepily.ai
>
> ### Accomplishments
>
> **API Consistency Fixes**:
> - Removed redundant `user_email` from `DeepResearchSubmitRequest` - now derived from JWT token
> - Renamed `currentUser` → `currentUserEmail` in notifications.js (16 occurrences) for clarity
> - Consistent with Podcast Generator and Research→Podcast endpoints
>
> **Job Notification Routing Fix** (Phase 6 Improvements):
> - Created provisional job registration system for race condition handling
> - `createProvisionalJobRegistration()` - creates placeholder when notification arrives before job fetch
> - `ensureJobCardExists()` - creates DOM card for provisional job
> - `updateJobCardMetadata()` - upgrades provisional to full metadata preserving activity log
> - `cleanupRunQueueCard()` - removes card and stops timer when job completes
> - `scheduleQueueRefreshForJob()` - debounced refresh for full metadata
> - `inferAgentTypeFromJobId()` - maps job ID prefix to agent type for badges
>
> **Bug Fix Mode Closure**:
> - Marked LanceDB nprobes warning as already fixed (Session 7, commit 24b463b)
> - Bug fix queue now empty
>
> **Infrastructure**:
> - Created `TODO.md` for persistent task tracking across sessions
> - Added `/plan-todo` slash command for TODO management
>
> ### Commits
> - `3b45937` - Rename currentUser to currentUserEmail for clarity
> - `893b8f0` - Session 105: Fix agentic job notification routing to job cards
>
> ### Pending (CoSA Submodule)
> - `deep_research.py` - user_email derived from JWT (API consistency)
> - `notification_models.py` - sender_id regex for job ID format
> - `mock_clients.py` - new file for dry-run mode
> - Dry-run mode additions to routers and job classes
>
> ---

> **✅ SESSION 105 COMPLETE**: Job Card Rendering + Notification Routing Fixes (2026.01.27)
> **Owner**: claude.code@lupin.deepily.ai
>
> ### Accomplishments
> - **Fix 1**: Job cards not rendering when queue collapsed → commit: f13a8f1
>   - Reset `state.loaded = false` when data arrives, not just when expanded
> - **Fix 2**: sender_id regex rejects job ID format (CoSA - pending)
>   - Added `[a-z]+-[a-f0-9]{8}` pattern for job IDs like `dr-a0ebba60`
> - **Fix 3**: Agentic job progress notifications route to sender cards instead of job cards
>   - Extract job_id from sender_id suffix in frontend routing logic
>
> ### Commits
> - `f13a8f1` - Session 105: Fix job cards not rendering when queue collapsed
> - `5ad2c78` - Session 105: Fix job notification routing + add Claude Code queue mode
>
> ---

> **✅ SESSION 104 COMPLETE**: TTS Notification Duplication Fix (2026.01.27)
> **Owner**: claude.code@lupin.deepily.ai
>
> ### Accomplishments
> - Fixed TTS notification duplication in job cards
> - Added dry-run checkboxes to agentic job submission UI
>
> ### Commits
> - `5bb6c10` - Session 104: Fix TTS notification duplication in job cards
> - `329e2af` - Add dry-run checkboxes to agentic job submission UI
>
> ---

> **✅ SESSION 103 COMPLETE**: Bug Fix Mode - gist_cache.lance Corruption (2026.01.27)
> **Owner**: claude.code@lupin.deepily.ai#8cc66d0d
>
> ### Fixes
> - **Fix 1**: gist_cache.lance corruption auto-recovery (carried over from Session 100-101)
>   - **Symptom**: `get_cached_gist()` failed with "Object at location .../gist_cache.lance/data/<uuid>.lance not found"
>   - **Root Cause**: LanceDB stores data in UUID-named `.lance` fragments; manual deletion or crash leaves manifest referencing missing files
>   - **Fix**: Added `_is_table_corrupted()` method that performs actual data scan (not just `count_rows()` which only reads metadata)
>   - **Auto-Recovery**: On corruption detection, drops and recreates table with fresh schema (acceptable data loss - it's a cache)
>   - **Files (CoSA)**: `src/cosa/memory/gist_cache_table.py` - needs separate commit in CoSA context
>   - **Tests**: 8 smoke tests including corruption detection and auto-recovery verification
>   - **Commit**: 0b8c915 (Lupin docs) + pending CoSA commit
>
> - **Fix 2**: LanceDB nprobes warning → Already fixed (Session 7, commit 24b463b)
>   - Verified existing fix: `warnings.filterwarnings()` + logger levels to ERROR
>   - Configurable via `suppress lancedb warnings = true`
>
> ### Session Summary
> Bug fix mode session completed. Queue cleared - no remaining bugs.
>
> ---

> **✅ SESSION 102 COMPLETE**: Bug Fix Mode Closure + Documentation (2026.01.26)
> **Owner**: claude.code@lupin.deepily.ai#514f7e7a
>
> ### Accomplishments
> - **Bug Fix Mode Closure**: Closed Session 100-101 bug fix queue
>   - 4 fixes completed (clearAllNotifications TypeError, Boolean config parsing, LanceDB corruption recovery, etc.)
>   - 2 bugs carried over (LanceDB nprobes warning, gist_cache.lance corruption)
>
> - **Verified Session 101 Implementation**: Confirmed Phase 6 FIX code already committed
>   - Race condition fix (cache unregistered job notifications)
>   - tts_raw flag support for TTS rendering control
>   - Replay mechanism for cached notifications
>
> ### TODO for Next Session
> - Test math agent notification fixes (hard refresh, ask "What's 11+11?", verify console logs and TTS)
> - Verify both notifications appear in job card (not sender card)
> - Future: Add `tts_raw` parameter to cosa-voice MCP server
>
> ---

> **✅ SESSION 101 COMPLETE**: Agentic Job UI Cards - Phases 3-6 Implementation (2026.01.26)
> **Owner**: claude.code@lupin.deepily.ai#63cce923
>
> ### Accomplishments
> **Phase 3 - Job Classes** (CoSA):
> - Created `agents/podcast_generator/job.py` - PodcastGeneratorJob wrapping PodcastOrchestratorAgent
> - Created `agents/deep_research_to_podcast/job.py` - DeepResearchToPodcastJob wrapping chained workflow
> - Both extend AgenticJobBase with JOB_TYPE/JOB_PREFIX for queue integration
> - Smoke tests passing for both job classes
>
> **Phase 4 - API Routers** (Lupin - cosa/rest/routers/):
> - Created `podcast_generator.py` with smart input detection:
>   - Direct path mode: `/io/deep-research/user@email/file.md` → immediate job creation
>   - Description mode: natural language → LLM fuzzy matching + ask_multiple_choice notification
> - Created `deep_research_to_podcast.py` - standard query-based submission
> - Endpoints: POST `/api/podcast-generator/submit`, POST `/api/deep-research-to-podcast/submit`
> - Smoke tests passing for both routers
>
> **Phase 5 - UI Submission Cards** (Lupin):
> - Added toolbar button (📝) for job submission section
> - Added "Submit Research Job" card with voice input (🎤), budget field, podcast checkbox
> - Added "Generate Podcast from Research" card with smart input + voice input
> - Smart input hint: "Describe research → confirm selection | Paste path → generates immediately"
>
> **Phase 6 - Router Registration + JS Handlers** (Lupin):
> - Updated `main.py` - imported and registered new routers (93 routes total)
> - Updated `notifications.js` - added `setupJobSubmitEventListeners()` and submit handlers
> - `submitResearchJob()`: Handles checkbox toggle between DR and DR→Podcast endpoints
> - `submitPodcastJob()`: Handles smart input response (queued vs matching status)
>
> ### TODO for Next Session
> - Test UI cards in browser with running server
> - Verify fuzzy matching notification flow
> - Test voice input (🎤) for job submission
>
> **Note**: CoSA submodule changes (Phase 3) need separate commit in CoSA context
>
> ---

> **✅ SESSION 100 COMPLETE**: Agentic Job UI Cards - Phases 0-2 + Bug Fix 4 + Expertise Level (2026.01.26)
> **Owner**: claude.code@lupin.deepily.ai#63cce923
> **Plan**: `/home/rruiz/.claude/plans/federated-prancing-lagoon.md`
>
> ### Accomplishments
> **Phase 0 - Consolidated voice_io Modules** (CoSA):
> - Created `agents/utils/voice_io.py` - unified implementation with all features
> - Updated `agents/deep_research/voice_io.py` - thin wrapper using consolidated module
> - Updated `agents/podcast_generator/voice_io.py` - thin wrapper with new features
>
> **Phase 1 - DeepResearchToPodcastAgent Wrapper** (CoSA):
> - Created `agents/deep_research_to_podcast/` package with `agent.py` and `state.py`
>
> **Phase 2 - CLI Entry Point** (CoSA):
> - Created `agents/deep_research_to_podcast/__main__.py`
> - Usage: `python -m cosa.agents.deep_research_to_podcast --query "..." --user-email ...`
>
> **Bug Fix 4 - run_research() Missing user_email**:
> - Fixed wrapper agent to pass `user_email=self.user_email` to `run_research()`
>
> **Expertise Level / Target Audience Configuration** (NEW):
> - Added `target_audience` (beginner/general/expert/academic) and `audience_context` to ResearchConfig
> - Added config keys to `lupin-app.ini` and `lupin-app-splainer.ini` (Lupin commit: bcf386a)
> - Added `--audience` and `--audience-context` CLI flags to Deep Research CLI
> - Created AUDIENCE_GUIDELINES dictionaries in 3 prompt files:
>   - `prompts/planning.py` - decomposition guidelines per audience level
>   - `prompts/subagent.py` - source selection guidelines per audience level
>   - `prompts/synthesis.py` - writing style guidelines per audience level
> - Wired audience params through `cli.py` → all prompt functions
> - Added `--audience` and `--audience-context` to wrapper agent CLI (`__main__.py`)
> - Updated wrapper `agent.py` to pass audience config to ResearchConfig
> - **All smoke tests passing**: config, planning, subagent, synthesis modules
>
> ### Remaining Work (Phases 3-6)
> - Phase 3: PodcastGeneratorJob class for queue integration
> - Phase 4: API endpoints (`/api/podcast-generator/submit`, `/api/chained-job/submit`)
> - Phase 5: UI cards in notifications.html
> - Phase 6: Router registration in main.py
>
> **Note**: CoSA submodule changes need separate commit
>
> ---

> **✅ SESSION 99 COMPLETE**: Bug Fix Mode - LanceDB Corruption Recovery (2026.01.25)
> **Owner**: claude.code@lupin.deepily.ai#454f9eca
>
> ### Fixes
> - **Fix 1**: LanceDB embedding cache corruption auto-recovery (ad-hoc)
>   - **Symptom**: `get_cached_embedding()` failed with "Not found" error when internal data fragment files missing
>   - **Root Cause**: LanceDB stores data in UUID-named `.lance` fragments; manual deletion or crash leaves manifest referencing missing files
>   - **Fix**: Added `_is_table_corrupted()` method that performs actual data scan (not just `count_rows()` which only reads metadata)
>   - **Auto-Recovery**: On corruption detection, drops and recreates table with fresh schema (acceptable data loss - it's a cache)
>   - **Files (CoSA)**: `src/cosa/memory/embedding_cache_table.py` - needs separate commit
>   - **Files (Lupin)**: `src/tests/unit/test_embedding_cache_corruption.py` (313 lines, 9 tests)
>   - **Tests**: 6 unit tests (mocked scenarios), 3 integration tests (real LanceDB corruption)
>   - **Commit**: 77ab971 (Lupin unit tests only)
>
> ### Session Summary
> - **Total Fixes**: 1
> - **Files Changed**: embedding_cache_table.py (CoSA), test_embedding_cache_corruption.py (Lupin)
> - **Commits**: 77ab971 (Lupin)
> - **Note**: CoSA submodule changes require separate commit in CoSA context
>
> **Status**: Session closed 2026.01.25
>
> ---

> **✅ SESSION 98 COMPLETE**: TTS Migration Completion + Phase 7 Browser Testing Done (2026.01.25)
> **Owner**: claude.code@lupin.deepily.ai#194f142f
>
> ### Accomplishments
> - **Bug Fix: Cache Hit ID Mismatch** (`running_fifo_queue.py:530-533`)
>   - Root cause: When cache hit occurs, `for_current_user()` creates copy with cached snapshot's `id_hash`
>   - But user association in `user_job_tracker` uses running job's `id_hash`
>   - Result: `get_jobs_for_user()` returned 0 jobs for cache hits
>   - Fix: Added `done_queue_entry.id_hash = original_job.id_hash` after copy creation
> - **Migrated 3 remaining `emit_speech_callback` calls** in `todo_fifo_queue.py`
>   - Line ~640: Unimplemented command case → `_notify()`
>   - Line ~655: After agent creation → `_notify(msg, job=agent)`
>   - Line ~772: Queue size announcement → `_notify(msg, job=job)`
> - **Bug Fix: Phase 6 TTS Routing** (`notifications.js:3728-3745`)
>   - Problem: Job-card routed notifications had no TTS playback (cached results silent)
>   - Problem: Regular notifications used verbose "Important! task notification:" prefix
>   - Fix: Added TTS queuing to Phase 6 with direct message (no prefix)
>   - Result: Answers now play clean (e.g., "14" not "Important! task notification: 14")
> - **✅ Phase 7 Browser Testing - COMPLETE**
>   - Job Queue Progressive Disclosure UI verified working
>   - Spinning indicator, duration timer, job cards all functional
>   - TTS playback for both fresh and cached results confirmed
> - **Smoke Tests**: All 4 passed (fifo_queue, running_fifo_queue, todo_fifo_queue, notification_models)
>
> ### Session Summary
> Completed TTS migration from legacy `_emit_speech` WebSocket system to notification service. Fixed critical cache hit bug that prevented done queue jobs from appearing for users. Fixed Phase 6 TTS routing for clean answer playback. Phase 7 Browser Testing marked complete.
>
> **Note**: Queue code changes are in CoSA submodule - require separate commit in CoSA context.
>
> ---

> **✅ SESSION 97 COMPLETE**: TTS Migration Phase 0-3 (2026.01.25)
> **Owner**: claude.code@lupin.deepily.ai#454f9eca
>
> ### Accomplishments
> - **Phase 0**: Added `suppress_ding` field to NotificationRequest and AsyncNotificationRequest
> - **Phase 0**: Added retry parameters (`retry_on_timeout`, `max_attempts`, `backoff_multiplier`) to `notify_user_sync()`
> - **Phase 0**: Updated `job_id` pattern to accept SHA256 hashes: `^([a-z]+-[a-f0-9]{8}|[a-f0-9]{64})$`
> - **Phase 1**: Added `_notify()`, `_get_notification_job_id()`, `_get_target_user_email()` to FifoQueue base class
> - **Phase 1**: Added user_service lookup for email resolution in `_get_target_user_email()`
> - **Phase 2**: Migrated all 7 `_emit_speech` calls in `running_fifo_queue.py` to `_notify()`
> - **Phase 2**: Migrated blocking query (line 480) in `todo_fifo_queue.py` to `notify_user_sync()` with retry
> - **Phase 3**: Commented out legacy `_emit_speech()` in `fifo_queue.py`
> - **Phase 3**: Set `emit_speech_callback=None` in `main.py` queue initialization
>
> ### Session Summary
> Major TTS migration implementing the plan from Session 96. Replaced legacy WebSocket-based `_emit_speech` with notification service. Added `suppress_ding=True` for conversational TTS without notification sounds. Job cards now receive TTS via job_id routing.
>
> ---

> **✅ SESSION 96 COMPLETE**: TODO Review + TTS Investigation Planning (2026.01.23)
> **Owner**: claude.code@lupin.deepily.ai#2adf6d65
>
> ### Accomplishments
> - Reviewed all outstanding TODO items from Session 95
> - Marked as DONE: Podcast Generator Full Audio Test, Job Queue Progressive Disclosure UI
> - Added new future TODO: TTS Consolidation Investigation
> - Began TTS consolidation research - investigated `_emit_speech` (5 callers in queue code) vs notification service
> - **Key user correction**: MCP is facade over notification service; latency assumptions need re-evaluation
> - Created investigation plan: `/home/rruiz/.claude/plans/modular-wondering-fox.md`
>
> ### Session Summary
> Light session focused on TODO management and initial TTS architecture investigation. Investigation deferred to tomorrow pending deeper analysis of notification service capabilities (not just MCP facade).
>
> ---

> **✅ SESSION 95 COMPLETE**: Bug Fix Mode (2026.01.23)
> **Owner**: claude.code@lupin.deepily.ai#6fa77d02
>
> ### Fixes
> - **Fix 1**: cosa-voice MCP project detection order bug (CoSA detected as Lupin) - Fixed prior to session start
> - **Fix 2**: LanceDB/PostgreSQL permissions issue (from Session 94 TODO #1)
>   - Root cause: `lupin.lancedb` owned by root, `postgresql-dev-data` had 700 permissions (no group access)
>   - Fixed: Changed ownership and permissions via sudo chown/chmod
>   - Impact: Database recreation and embedding cache errors in smoke tests now resolved
> - **Fix 3**: Podcast Generator - English audio generated when not requested
>   - Root cause: `scripts_by_language` unconditionally initialized with English (`orchestrator.py:441-442`)
>   - Fixed: Conditional English inclusion - only add to dict if `"en" in self.target_languages`
>   - Updated notification message for non-English-only generation
>   - File: `src/cosa/agents/podcast_generator/orchestrator.py` (lines 441-462)
>   - Smoke Tests: 10/10 PASSED
> - **Fix 4**: Podcast Generator - English audio notifications missing language identifier
>   - Root cause: `do_audio_only_async()` used generic messages without language specification
>   - Fixed: Added "English" to notification messages (matching `do_all_async()` pattern)
>   - File: `src/cosa/agents/podcast_generator/orchestrator.py` (lines 917-919, 943)
>   - Commit: 329ad9b (COSA repo)
>
> ### Session Summary
> - **Total Fixes**: 4
> - **Files Changed**: orchestrator.py, lupin.lancedb permissions, postgresql-dev-data permissions
> - **Commits**: 9df9149 (Lupin), 329ad9b (COSA)
>
> **Status**: Session closed 2026.01.23
>
> ---

> **✅ SESSION 94 COMPLETE**: Queue System Class Hierarchy Unification (2026.01.22)
> - **Goal**: Unify naming conventions across AgentBase, SolutionSnapshot, and AgenticJobBase
> - **Phase 1**: Cleared LanceDB database for schema-free refactoring (fresh start)
> - **Phase 2**: Added unified properties to all three classes:
>   - `AgenticJobBase`: Added `question`, `answer`, `job_type`, `created_date` properties
>   - `SolutionSnapshot`: Added `job_type` property (maps to `agent_class_name`)
>   - `AgentBase`: Added `job_type` (class name), `created_date` properties
> - **Phase 3**: Created `QueueableJob` Protocol (`src/cosa/rest/queue_protocol.py`) documenting unified interface
> - **Phase 4**: Simplified `queues.py` - replaced `getattr()` chains with direct attribute access using `job.job_type`
> - **Files Created**: `src/cosa/rest/queue_protocol.py` (~180 lines)
> - **Files Modified**: `agentic_job_base.py`, `agent_base.py`, `solution_snapshot.py`, `queues.py`
> - **Smoke Tests**: All PASSED (AgenticJobBase, SolutionSnapshot, AgentBase, QueueableJob Protocol)
> - **Benefit**: Clean code, type safety via Protocol, consistent `job_type` across all job types, IDE autocomplete works
>
> ---
>
> **📋 IMMEDIATE TODO**:
> 1. **Deep Research UI Card**: Simple UI for creating new deep research tasks
> 2. **Podcast Generator UI Card**: Simple UI for creating new podcast generation tasks
>
> **📋 FUTURE TODO**:
> 1. **Deep Research Phase 8**: COSA Router Integration for natural language job submission
> 2. **Podcast Generator Phase 3**: COSA Router Integration for natural language podcast generation
>
> **✅ Recently Completed**:
> - Conversation Identity Phases 4-5 (Session 101)
>
> **✅ COMPLETED (Session 98)**:
> - ~~🔊 TTS Consolidation Investigation~~ - Migrated to notification service
> - ~~🧪 Phase 7 Browser Testing~~ - Job Queue Progressive Disclosure UI verified
> - ~~🔬 Deep Research Queue Integration - BROWSER TESTING~~ - Phase 6 frontend notification routing working
>
> **✅ SESSION 93 COMPLETE**: Podcast Generator Multi-Language Translation Support (2026.01.22)
> - **Feature**: Added support for generating podcasts in multiple languages (English default, Spanish opt-in)
> - **ISO Codes**: en, es, es-ES (Castilian), es-MX (Mexican), es-AR (Argentinian)
> - **Native Generation**: Claude generates scripts directly in target language (not post-translation)
> - **Phase 4b Loop**: After English approval, generates/reviews each additional language with full user approval flow
> - **TTS Support**: Language-aware voice lookup with multilingual model fallback (eleven_multilingual_v2)
> - **Prosody Validation**: Verifies prosody markers preserved across translations
> - **CLI**: Added `--languages` / `-l` argument (e.g., `--languages en,es-MX`)
> - **Files Created/Modified**: config.py, tts_client.py, prompts/script_generation.py, state.py, orchestrator.py, __main__.py, lupin-app.ini, lupin-app-splainer.ini
> - **Smoke Tests**: 10/10 PASSED
>
> ---
>
> **📋 TODO FOR NEXT SESSION (Session 94)**:
> 1. **🏗️ DESIGN: Unify SolutionSnapshot/AgenticJobBase Interface**: Queue system mixes `SolutionSnapshot` (legacy COSA) and `AgenticJobBase` (new agentic jobs) without shared interface. Current `getattr()` hack in `queues.py:508-517` needs principled design. Options: Protocol/Interface, Adapter Pattern, Attribute Alignment.
> 2. **🧪 Phase 7 Browser Testing**: Continue verification - spinning indicator, live duration timer, abstract/report link, cost summary, error display.
> 3. **🔬 Deep Research Queue Integration - BROWSER TESTING**: Test Phase 6 frontend notification routing.
> 4. **🎙️ Podcast Generator - FULL AUDIO GENERATION TEST**: Ready for full 20-segment test.
> 5. **⏰ Job Queue Progressive Disclosure UI - MANUAL TESTING**: See plan: `/home/rruiz/.claude/plans/cheeky-leaping-scone.md`
> 6. **Deep Research Phase 8 (PENDING)**: COSA Router Integration for natural language job submission
> 7. **Conversation Identity Phases 4-5 (FUTURE)**: Phase 1 complete. Remaining: Phase 4 = AgentBase History, Phase 5 = Lifecycle.
> 8. Voice discovery/configuration for notification TTS UI still pending
> 9. **Future TODO**: Config mapping female/male voices, consolidate voice_io.py, evaluate config.py dataclasses, migrate /api/deep-research/report
>
> **🔧 SESSION 91 COMPLETE**: Phase 7 Browser Testing - Bug Fixes in get_job_interactions Endpoint
> - **BUG #1**: Wrong import path in `queues.py:484` - changed `cosa.rest.db.models.notification` to `cosa.rest.postgres_models`
> - **BUG #2**: AttributeError - `MockAgenticJob` missing `agent_class_name`, `question`, `answer`, `created_date` attributes
> - **TEMP FIX**: Used `getattr()` with safe defaults in `queues.py:508-517` (marked as needing proper design)
> - **DESIGN TODO**: Need principled interface contract for queue items (SolutionSnapshot vs AgenticJobBase)
> - **Files Modified**: `src/cosa/rest/routers/queues.py` (2 edits)
>
> **✅ SESSION 90 COMPLETE**: Podcast Generator Notification Enhancements + Bug Discovery
> - **Implemented**: Clickable links (script, audio, research) and audio cost tracking in all 3 notification methods
> - **Changes**: Added `character_count` to `TTSSegmentResult`, `ELEVENLABS_COST_PER_1K_CHARS` constant, fixed `do_all_async`/`do_review_only_async`/`do_audio_only_async` notifications
> - **Bug Found**: Research link shows "edit-mode" in audio-only mode - needs fix (see TODO #1)
> - **Smoke Tests**: 10/10 PASSED
> - **Files**: `tts_client.py` (+2 lines), `orchestrator.py` (+60 lines)
>
> **✅ SESSION 89 COMPLETE**: Bug Fix Mode - Gist Enhancement
> - **Fix 1**: Enhance Session Gist Generation with Abstract Fields (commit: f24337f)
> - **Details**: Frontend now collects both messages and abstracts; backend prioritizes first 5 abstracts + first 5 messages for richer gist generation; CSS width increased from 180px to 225px
> - **Files**: notifications.js, notifications.py, notifications.css
>
> **✅ SESSION 88 COMPLETE**: Bug Fix Day - Multiple notification/UI bugs fixed in single session.
> - **Fix 1**: Clear-All-Notifications bulk delete endpoint (notifications.py, notification_repository.py, notifications.js)
> - **Fix 2**: PostgreSQL Backup Integration via pg_dump (backup-postgres.sh, backup.sh, rsync-exclude.txt)
> - **Status**: All fixes complete and tested.
>
> **🧪 SESSION 87 COMPLETE**: Phase 7 Browser Testing + Mock Job User Association Bug Fix. CURL testing complete, browser UI testing ongoing.
>
> **✅ SESSION 86 COMPLETE**: Podcast Generator Phase 2 Bug Fixes + Progress Enhancement. See details below.
>
> **🧪 SESSION 85 AWAITING BROWSER TESTING**: Phase 7 - Unified Queue View + MockAgenticJob Test Harness. See details below.
>
> **✅ SESSION 84 COMPLETE**: Notification UI Tweaks - System Status Refresh Button. See details below.
>
> **✅ SESSION 83 COMPLETE**: Deep Research API Testing + Phase 5-6 Implementation. See details below.
>
> **✅ SESSION 82 COMPLETE**: Podcast Generator Phase 2 Enhancements - Audio-Only Flag, Smoke Tests & Progress Notifications. See details below.
>
> **✅ SESSION 81 COMPLETE**: Docker Path Bug Fixes. See details below.

> **🎯 CURRENT**: 2026.01.21 (Session 87) - PHASE 7 BROWSER TESTING + MOCK JOB BUG FIX! Testing Phase 7 Unified Queue View with MockAgenticJob. **BUG DISCOVERED**: Mock jobs weren't appearing in user's queue view despite being pushed to the queue. Jobs showed in WebSocket events but API returned empty arrays with `filtered_by: user_id`. **ROOT CAUSE**: `mock_job.py` called `todo_queue.push(job)` directly, bypassing the `UserJobTracker.associate_job_with_user()` call that happens in `TodoFifoQueue.push_job()`. Jobs were in the queue but not associated with the submitting user. **FIX**: Added import for `user_job_tracker` and two association calls after push: `user_job_tracker.associate_job_with_user(job.id_hash, user_id)` and `user_job_tracker.associate_job_with_session(job.id_hash, session_id)`. **CURL TESTING COMPLETE**: (1) `failure_probability: 0` - Jobs correctly flow through todo → running → done queues ✅, (2) `failure_probability: 1` - Jobs correctly flow through todo → running → dead queues ✅. **FILES MODIFIED**: `src/cosa/rest/routers/mock_job.py` (+3 lines: import + 2 association calls). **STATUS**: CURL testing complete, browser UI testing in progress. 🧪🔄
>
> **🎯 PREVIOUS**: 2026.01.20 (Session 86) - PODCAST GENERATOR PHASE 2 BUG FIXES + PROGRESS ENHANCEMENT! Manual end-to-end testing session that discovered and fixed 4 bugs, plus implemented a progress reporting enhancement. **PART 1 - MAX-SEGMENTS FLAG**: Added `--max-segments` / `-m` CLI flag to limit TTS generation to first N segments (cost control during testing). Modified `__main__.py` (+15 lines), `orchestrator.py` (+15 lines: `max_segments` parameter in `__init__` and `from_saved_script()`, segment slicing in `_generate_audio_async()`). **PART 2 - BUG #1: WRONG USER_ID IN OUTPUT PATH**: Output path used default `user@example.com` instead of actual user. **FIX**: Added `extract_user_id_from_path()` function that parses email from paths like `io/podcasts/{email}/script.md`. Auto-extracts when `--user-id` not explicitly provided. **PART 3 - BUG #1b: DUPLICATE "PODCAST" IN FILENAME**: Audio filename template `{topic}-podcast.mp3` combined with topic "untitled-podcast" created "untitled-podcast-podcast.mp3". **FIX**: Changed template in `config.py` from `{timestamp}-{topic}-podcast.mp3` to `{timestamp}-{topic}.mp3`. **PART 4 - BUG #2/3: CLICKABLE LINKS IN NOTIFICATIONS**: MP3 and script paths were plain text, not clickable. **FIX**: Created new generic file serving endpoint `/api/io/file` in `src/cosa/rest/routers/io_files.py` (~170 lines). Supports .md, .mp3, .pdf, .wav, .txt, .json with proper content-type detection. Security: path validation, directory traversal prevention. Updated `orchestrator.py` completion notification to use markdown links: `[View Script](/api/io/file?path=...)`, `[Download MP3](/api/io/file?path=...)`. Registered router in `main.py`. **PART 5 - BUG #4: DURATION SHOWS 0.0 MINUTES**: Script loaded with `Duration: ~0.0 minutes`. **ROOT CAUSE**: Claude may not provide `estimated_duration_minutes` in response, and fallback was missing. **FIX**: Added `calculated_duration_minutes` property to `PodcastScript` in `state.py` that calculates from word count (~150 words/minute speaking rate) when estimate is 0. Updated orchestrator notifications to use `calculated_duration_minutes`. **PART 6 - PROGRESS ENHANCEMENT**: Changed progress reporting from "every 10 segments" to "every 10% milestone". **BEFORE**: Notifications at segment 10, 20, 30... (variable count). **AFTER**: Notifications at 10%, 20%, 30%... 100% (consistent ~10 notifications). Added `_reported_milestones` set tracking in orchestrator, updated `_audio_progress_callback()` to calculate percentage milestones. **FILES CREATED**: `src/cosa/rest/routers/io_files.py` (~170 lines). **FILES MODIFIED**: `src/cosa/agents/podcast_generator/__main__.py` (+50 lines), `src/cosa/agents/podcast_generator/orchestrator.py` (+50 lines), `src/cosa/agents/podcast_generator/config.py` (1 line), `src/cosa/agents/podcast_generator/state.py` (+20 lines), `src/fastapi_app/main.py` (+2 lines). **SMOKE TESTS**: 10/10 PASSED. **ENDPOINT VERIFIED**: `curl "http://localhost:7999/api/io/file?path=..."` returns correct content. **STATUS**: All bug fixes complete, tested with `--max-segments 3`, ready for full audio generation test. 🎙️🔧✅

> **🎯 PREVIOUS**: 2026.01.20 (Session 85) - PHASE 7: UNIFIED QUEUE VIEW + MOCKAGENTICJOB TEST HARNESS! Implemented comprehensive Phase 7 for Deep Research background job integration. **PART 1 - MOCKAGENTICJOB TEST HARNESS**: Created zero-cost testing infrastructure for the queue system at `src/cosa/agents/test_harness/`. `MockAgenticJob` class simulates long-running agentic jobs without inference costs. Features: configurable iteration count (random or fixed), configurable sleep duration between phases, configurable failure probability for testing dead queue, real notifications via cosa-voice MCP with `job_id` routing, mock artifacts (report_path, abstract, cost_summary) for UI testing. **API ENDPOINT**: `POST /api/mock-job/submit` accepts parameters: `iterations_min/max`, `sleep_min/max`, `failure_probability`, `fixed_iterations`, `fixed_sleep`, `description`. Returns job_id, queue_position, and config summary. **PART 2 - BACKEND QUEUE API ENHANCEMENTS**: Modified `src/cosa/rest/routers/queues.py` to expose job artifacts in metadata. Done queue now includes: `report_path`, `abstract`, `cost_summary`, `started_at`, `completed_at`, `duration_seconds`, `status`, `error`. Todo/Run queues now return `*_jobs_metadata` arrays (previously HTML only). Auto-detection of AgenticJobBase vs SolutionSnapshot objects. **PART 3 - COSA-VOICE JOB_ID PARAMETER FIX**: Updated `voice_io.py` and `cosa_interface.py` to accept and pass through `job_id` parameter for notification routing to job cards. **PART 4 - FRONTEND JAVASCRIPT ENHANCEMENTS**: Modified `notifications.js` with ~150 new lines. Added `durationTimers` Map for tracking running job timers. Enhanced `renderJobCard()` to show: (1) Running jobs: spinning status indicator, live duration timer with auto-update every second, (2) Done jobs: abstract section with green left border, "View Full Report" button, cost summary grid (cost/duration/tokens), completion badge (✓/✗), (3) Dead jobs: error display section with red styling, failed badge. New functions: `formatDuration()` (seconds → "Xm Ys"), `startDurationTimer()`, `stopDurationTimer()`, `stopAllDurationTimers()`. **PART 5 - CSS STYLING**: Added ~150 lines to `notifications.css` for new components: `.status-indicator.spinning` with rotation animation, `.completion-badge.success/failed`, `.job-duration-line` with blue background, `.job-abstract` with green left border, `.report-link-btn` with hover state, `.job-cost-summary` with yellow grid, `.job-error` with red styling. **FILES CREATED**: `src/cosa/agents/test_harness/__init__.py`, `src/cosa/agents/test_harness/mock_job.py` (~340 lines), `src/cosa/agents/test_harness/README.md` (~180 lines), `src/cosa/rest/routers/mock_job.py` (~130 lines). **FILES MODIFIED**: `src/fastapi_app/main.py` (router registration), `src/cosa/rest/routers/queues.py` (~80 lines), `src/cosa/agents/deep_research/voice_io.py` (+job_id param), `src/cosa/agents/deep_research/cosa_interface.py` (+job_id param), `src/fastapi_app/static/js/notifications.js` (~150 lines), `src/fastapi_app/static/css/notifications.css` (~150 lines). **VERIFICATION**: Python syntax checks PASSED, JavaScript syntax check PASSED, MockAgenticJob smoke test PASSED. **PLAN FILE**: `/home/rruiz/.claude/plans/tidy-doodling-pizza.md` (Phase 7 status: AWAITING BROWSER TESTING). **STATUS**: Code implementation complete, awaiting browser testing and debugging. 🧪🔬

> **🎯 PREVIOUS**: 2026.01.20 (Session 84) - NOTIFICATION UI TWEAKS - SYSTEM STATUS REFRESH BUTTON! Quick enhancement session adding a refresh button to the System Status section in the notifications page. **FEATURE**: Added ↻ refresh button to "System Status" section header that refreshes all status information without full page reload. Clicking triggers: (1) WebSocket connection state evaluation (readyState mapping), (2) Auth verification via token check with auto-refresh if expired, (3) Session ID display updates, (4) Health monitor status refresh via existing `checkWebSocketHealth()`. **VISUAL FEEDBACK**: Button spins during refresh using existing `@keyframes spin` animation, disables to prevent double-clicks. **FILES MODIFIED**: (1) `notifications.html:361-370` - Added refresh button wrapped in `.section-header-actions` div with `event.stopPropagation()` to prevent section collapse, (2) `notifications.css:121-150` - Added styles for `.section-header-actions` (flexbox container), `.refresh-link` (button base), hover/disabled/spinning states, (3) `notifications.js:1071-1188` - Added 4 methods: `refreshAllStatus()` (main orchestrator), `refreshWebSocketStatus()` (evaluates queueWS/audioWS readyState), `refreshAuthStatus()` (token validation with refresh), `refreshSessionDisplay()` (updates session ID spans). **PATTERN**: Matches existing "↻ Reload" button in Config section. **STATUS**: Implementation complete. 🔄✅
>
> **🎯 PREVIOUS**: 2026.01.20 (Session 83) - DEEP RESEARCH API TESTING + PHASE 5-6 IMPLEMENTATION! Multi-part session implementing auth testing documentation and Deep Research notification routing. **PART 1 - AUTH TESTING QUICK-REFERENCE**: Created `src/tests/AUTH-TESTING-GUIDE.md` (~120 lines) documenting the critical distinction between destructive (integration) and non-destructive (smoke/unit/manual) testing contexts. Includes Python and CURL patterns for authenticated API testing with environment variable-based credentials (security best practice). **PART 2 - DEEP RESEARCH SUBMIT SMOKE TEST**: Created `src/tests/smoke/test_deep_research_submit_smoke.py` (~115 lines) to test `POST /api/deep-research/submit` endpoint. 5-step test: login, submit job, verify response structure, verify expected values (status=queued, job_id format), check queue access. Ran test successfully with `ricardo.felipe.ruiz@gmail.com` - job `dr-c0ed19ef` queued at position 1. **PART 3 - PHASE 5: cosa-voice MCP ENHANCEMENT**: Added `job_id: Optional[str]` parameter to notification system for job-based routing. **Files modified**: (1) `src/cosa/cli/notification_models.py` - Added `job_id` field with regex validation `^[a-z]+-[a-f0-9]{8}$` to both `NotificationRequest` and `AsyncNotificationRequest`, updated `to_api_params()` methods. (2) `src/lupin_mcp/cosa_voice_mcp.py` - Added `job_id` parameter to all 4 tools: `notify()`, `ask_yes_no()`, `converse()`, `ask_multiple_choice()`. Backward compatible: `job_id=None` uses existing routing. **PART 4 - PHASE 6: NOTIFICATION ROUTER (FRONTEND)**: Implemented job-based notification routing in UI. **Files modified**: (1) `src/fastapi_app/static/js/notifications.js` (+150 lines) - Added `registeredJobs` Map for tracking active jobs (todo/running), `updateJobRegistration()` called when queues load, modified `handleNotificationUpdate()` to check for `job_id` and route to job card, added `appendNotificationToJobCard()`, `createJobActivityLog()`, `createActivityLogEntry()` methods. (2) `src/fastapi_app/static/css/notifications.css` (+45 lines) - Activity log styling with priority-based border colors. **ROUTING FLOW**: `response_requested=true` → Action Required card (unchanged), `job_id + registered` → Job card activity log (NEW), else → Sender card (unchanged). **FILES CREATED**: `src/tests/AUTH-TESTING-GUIDE.md`, `src/tests/smoke/test_deep_research_submit_smoke.py`. **FILES MODIFIED**: `src/cosa/cli/notification_models.py`, `src/lupin_mcp/cosa_voice_mcp.py`, `src/fastapi_app/static/js/notifications.js`, `src/fastapi_app/static/css/notifications.css`. **PLAN FILE**: `/home/rruiz/.claude/plans/tidy-doodling-pizza.md` (Phases 5-6 now complete). **STATUS**: Implementation complete, awaiting browser testing to verify Phase 6 notification routing. 🔬📋✅
>
> **🎯 PREVIOUS**: 2026.01.20 (Session 82) - PODCAST GENERATOR PHASE 2 ENHANCEMENTS! Continuation session implementing progress notification improvements and audio-only CLI mode for the Podcast Generator. **PART 1 - SMOKE TEST RUNNER UPDATES**: Added `tts_client` and `audio_stitcher` modules to the smoke test runner in `__main__.py`. Module count increased from 8 to 10. All 10 smoke tests passing. **PART 2 - AUDIO-ONLY CLI FLAG**: Added `--generate-audio` / `-a` flag to generate audio from an existing script (skips script generation and review phases). New `run_audio_generation()` async function loads script via `from_saved_script()`, calls new `do_audio_only_async()` method that jumps directly to Phase 5 (GENERATING_AUDIO) → Phase 6 (STITCHING_AUDIO) → COMPLETED. **PART 3 - PROGRESS NOTIFICATION ENHANCEMENTS**: (1) **ETA Tracking**: Added timing tracking in `generate_all_segments()` - calculates average segment duration and estimates remaining time. Progress callback signature updated to include `eta_seconds: float`. Notifications now show "Audio progress: 20/47 segments (42%), ~45s remaining". (2) **Retry Notifications**: Added `retry_callback` parameter to `PodcastTTSClient`. When a segment fails and will be retried, sends low-priority notification: "Segment 15 (Nora) failed, retrying (2/3)...". (3) **Callback Methods**: Added `_audio_retry_callback()` method to orchestrator, updated `_audio_progress_callback()` to accept and display ETA. **NOTIFICATION PRIORITY CLARIFICATION**: Progress and retry notifications use "low" priority (ding only, no TTS). Partial failure prompts use blocking `ask_yes_no()` which gets high priority (spoken via TTS). **FILES MODIFIED**: `src/cosa/agents/podcast_generator/__main__.py` (+70 lines: run_audio_generation, --generate-audio arg, smoke test modules), `src/cosa/agents/podcast_generator/orchestrator.py` (+80 lines: do_audio_only_async, _audio_retry_callback, updated _audio_progress_callback with ETA), `src/cosa/agents/podcast_generator/tts_client.py` (+40 lines: retry_callback parameter, timing tracking, ETA calculation). **SMOKE TESTS**: 10/10 PASSED (config, state, prompts.script_generation, prompts.personality, cosa_interface, voice_io, api_client, tts_client, audio_stitcher, orchestrator). **CLI USAGE**: `python -m cosa.agents.podcast_generator --generate-audio path/to/script.md --cli-mode --debug`. **PLAN FILE**: `/home/rruiz/.claude/plans/elegant-fluttering-narwhal.md`. **STATUS**: Implementation complete, awaiting manual end-to-end testing. 🎙️📊✅
>
> **✅ SESSION 79 BRIEF**: API Testing Setup - Server health verified, authentication approach discussed. User will provide credentials in Session 80 for Deep Research API testing.
>
> **✅ SESSION 78 COMPLETE**: Deep Research CLI UX Improvements + Docker Path Bug Fixes. See details below.
>
> **✅ SESSION 77 COMPLETE**: Multiple-Choice TTS Verification Testing. See details below.
>
> **✅ SESSION 76 COMPLETE**: Podcast Generator Save Timing & Version Suffix Fixes. See details below.
>
> **✅ SESSION 75 COMPLETE**: Podcast Generator Bugs 7 & 8 Fixed (iterative review + filename preservation). See details below.

> **🎯 CURRENT**: 2026.01.19 (Session 80) - PODCAST GENERATOR PHASE 2 PLANNING! Created comprehensive implementation plan for TTS audio generation feature. **SCOPE**: Convert approved podcast scripts into spoken MP3 files using ElevenLabs multi-voice synthesis. **ARCHITECTURE DECISIONS**: (1) Use pydub library for audio processing (PCM→MP3, silence insertion, concatenation), (2) ElevenLabs PCM 24000 output format (matches existing speech.py pattern), (3) Memory buffer storage during generation (write only final MP3), (4) Per-segment progress notifications. **FILES TO CREATE**: (1) `tts_client.py` (~250 lines) - ElevenLabs WebSocket batch generation with TTSSegmentResult dataclass, voice mapping, retry logic, (2) `audio_stitcher.py` (~150 lines) - pydub-based concatenation with 300ms silence on speaker changes. **FILES TO MODIFY**: (1) `orchestrator.py` (+80 lines) - Add Phase 5 (GENERATING_AUDIO) and Phase 6 (STITCHING_AUDIO) after script approval, (2) `requirements.txt` - Add pydub==0.25.1. **KEY PATTERNS**: WebSocket logic extracted from `speech.py:863-993`, voice mapping (Alex→Sarah voice, Jordan→Arnold voice), error handling with 3x retry and partial failure recovery. **VERIFICATION**: Smoke tests per module, manual integration test with real ElevenLabs API (~$2.40/podcast). **PLAN FILE**: `/home/rruiz/.claude/plans/compressed-marinating-tarjan.md`. **STATUS**: Planning complete, ready for implementation in next session. 🎙️📝✅
>
> **🎯 PREVIOUS**: 2026.01.19 (Session 78) - DEEP RESEARCH CLI UX IMPROVEMENTS + DOCKER PATH BUG FIXES! Multi-part session implementing planned UX improvements and fixing discovered bugs. **PART 1 - MULTIPLE-CHOICE CLARIFICATION UX**: Implemented plan from previous session to improve query clarification UX. When Deep Research CLI needs clarification, it now presents structured multiple-choice options instead of free-text input. **CHANGES**: (1) `prompts/clarification.py` - Added `options` array to JSON schema with 2-4 label/description pairs, updated all examples. (2) `voice_io.py` - Updated `choose()` to accept `Union[List[str], List[dict]]` with `allow_custom` parameter, CLI fallback shows descriptions. (3) `cli.py` - Uses `voice_io.choose()` when ≥2 options provided, falls back to `get_input()` otherwise. **PART 2 - REPORT VIEWER BROKEN LINK**: User reported 404 error when clicking "View Report" link after Deep Research completion. **ROOT CAUSE**: CLI sent absolute path (`/mnt/DATA01/.../io/deep-research/user@email/file.md`) but API expected relative path (`user@email/file.md`). **FIX**: `cli.py` now extracts relative path from `io/deep-research` base before URL encoding. **PART 3 - DOCKER VOLUME MOUNT MISMATCH**: Report viewer still returned 404 even with relative path fix. **ROOT CAUSE**: Docker container mounted `io/` to `/var/io` but code expected `/var/lupin/io`. **DIAGNOSIS**: `get_project_root()` returns `/var/lupin`, so code looks in `/var/lupin/io/deep-research/`. But Docker mount was `-v .../io:/var/io` (wrong destination). **FIXES**: (1) Created symlink inside container: `ln -s /var/io /var/lupin/io` (immediate fix). (2) Updated `lupin_client.py` - Changed 4 hardcoded `/var/io/` paths to `/var/lupin/io/`. (3) Updated `start-docker-lupin.sh` - Changed line 358 from `-v "$LUPIN_ROOT/io:/var/io"` to `-v "$LUPIN_ROOT/io:/var/lupin/io"` (permanent fix). **FILES MODIFIED**: `src/cosa/agents/deep_research/prompts/clarification.py`, `src/cosa/agents/deep_research/voice_io.py`, `src/cosa/agents/deep_research/cli.py`, `src/lib/clients/lupin_client.py`, `$DEEPILY_PROJECTS_DIR/scripts/server/start-docker-lupin.sh`. **SMOKE TESTS**: clarification.py ✓, voice_io.py ✓, CLI dry-run ✓. **STATUS**: All fixes complete and verified. 🔧✅🐳✅

> **🎯 PREVIOUS**: 2026.01.19 (Session 77) - MULTIPLE-CHOICE TTS VERIFICATION TESTING! Verification session to confirm Sessions 71-72 fixes still work correctly. **TESTS PERFORMED**: (1) Ran smoke tests for `notification_utils`, `deep_research/cosa_interface`, and `podcast_generator/cosa_interface` - all passed. (2) Sent live `ask_multiple_choice()` notifications to verify TTS behavior. (3) Confirmed options are NOT read aloud in TTS (UI-only display working). (4) Confirmed multi-select hint ("You can select multiple options") works correctly. (5) Noted: high/urgent priority required for TTS to speak. **KEY FINDING**: Session 71-72 fixes remain functional - no regressions detected. **FILES VERIFIED**: `src/cosa/utils/notification_utils.py`, `src/cosa/agents/deep_research/cosa_interface.py`, `src/cosa/agents/podcast_generator/cosa_interface.py`. **STATUS**: Verification complete, no changes needed. ✅🔊
>
> **🎯 PREVIOUS**: 2026.01.19 (Session 76) - PODCAST GENERATOR SAVE TIMING & VERSION SUFFIX FIXES! Fixed two issues from manual testing of `--edit-script` mode. **ISSUE 1 - PREMATURE SAVE**: Script was being saved at the TOP of the review loop BEFORE user made any decision - debug output showed "Script saved to: ..." before presenting review choices. **ROOT CAUSE**: Both `do_all_async()` and `do_review_only_async()` called `_save_script_async()` immediately when entering the review `while` loop. **FIX**: Moved save to AFTER user approves (final save) or AFTER revision is generated (versioned save). Now shows "Will save to:" preview path instead of actually saving. **ISSUE 2 - NO VERSION SUFFIX**: Revised scripts overwrote the original file instead of creating versioned copies. User expected: original preserved, revisions as `-v2.md`, `-v3.md`. **ROOT CAUSE**: `_save_script_async()` always reused `self._original_script_path` without version suffix. **FIX**: Added `is_revision: bool = False` parameter to `_save_script_async()`. When `is_revision=True`, generates versioned path: `stem-v{revision_num}.md`. Example: `2026.01.19-153550-voice-script.md` → `2026.01.19-153550-voice-script-v2.md`. **FILES MODIFIED**: `src/cosa/agents/podcast_generator/orchestrator.py` (~60 lines: save timing in both review methods + version suffix in _save_script_async). **SMOKE TESTS**: 8/8 PASSED. **PLAN FILE**: `/home/rruiz/.claude/plans/humble-dancing-beacon.md`. **STATUS**: Implementation complete, awaiting manual verification. 🎙️🔧✅
>
> **🎯 PREVIOUS**: 2026.01.19 (Session 75) - PODCAST GENERATOR BUGS 7 & 8 FIXED! User reported two critical bugs from manual testing of the `--edit-script` feature. **BUG 7 - NON-DESCRIPTIVE FILENAME**: Revised scripts were saved as `2026.01.19-160333-untitled-podcast-script.md` instead of preserving the original filename. Root cause: `_save_script_async()` generated a NEW filename each time based on current `script.title`. **FIX**: Added `_original_script_path` attribute to track original filename across revisions. Updated `from_saved_script()` to store original path, modified `_save_script_async()` to check and reuse original path for all subsequent saves. **BUG 8 - REVIEW NOT ITERATIVE (CRITICAL)**: After providing revision feedback and LLM regenerating the script, the process immediately EXITED instead of looping back to show the updated script for further review. User expected: review → feedback → regenerate → review again → repeat until explicit approval. Root cause: No `while` loop around review phase - code fell through to `script_approved = True` after revision. **FIX**: Wrapped entire review phase in `while not script_approved:` loop in BOTH `do_all_async()` and `do_review_only_async()` methods. Loop structure: (1) Save current draft (overwrites previous), (2) Present script preview with file path, (3) Handle choice - "Approve" exits loop, "Revise" or "Other" triggers regeneration and loops back, "Cancel" cleans up and returns None. **KEY CODE CHANGES**: (1) Added `self._original_script_path: Optional[str] = None` in `__init__`, (2) Store path in `from_saved_script()` with `agent._original_script_path = script_path`, (3) Modified `_save_script_async()` to reuse original path or generate new one only on first save, (4) Rewrote Phase 4 review section with iterative loop pattern. **FILES MODIFIED**: `src/cosa/agents/podcast_generator/orchestrator.py` (~80 lines: filename tracking + iterative review loop in both methods). **SMOKE TESTS**: 8/8 PASSED (config, state, prompts.script_generation, prompts.personality, cosa_interface, voice_io, api_client, orchestrator). **PLAN FILE**: `/home/rruiz/.claude/plans/mellow-chasing-tiger.md`. **STATUS**: Bug fixes complete, awaiting manual verification. 🎙️🐛✅
>
> **✅ SESSION 74 COMPLETE**: Podcast Generator Bug Fixes + Script Resume Feature. See details below.
>
> **✅ SESSION 74b COMPLETE**: Progressive Narrowing Test Harness - Isolated testing module for Deep Research theme clustering. See details below.
>
> **✅ SESSION 73 COMPLETE**: Notification UI bug fixes and updates. See details below.
>
> **✅ SESSION 72 COMPLETE**: Unified `_format_questions_for_tts()` implementations into shared utility. See details below.
>
> **✅ SESSION 71 COMPLETE**: Fix duplicate multiple-choice option rendering in agent interfaces. See details below.
>
> **✅ SESSION 70 COMPLETE**: Podcast Generator Agent Phase 1 - Script generation infrastructure. See details below.
>
> **✅ SESSION 69b COMPLETE**: Deep Research Background Job Integration - Phases 1-4 Backend Implementation. See details below.
>
> **✅ SESSION 69 COMPLETE**: Robust right-justification for sender stats in notification UI. See details below.
>
> **✅ SESSION 68 COMPLETE**: Reduce TTS verbosity for ask_multiple_choice - options now UI-only, not spoken. See details below.
>
> **✅ SESSION 67 COMPLETE**: Fix Sender ID and Session Name Separation for Deep Research CLI. See details below.
>
> **✅ SESSION 66 COMPLETE**: Fixed literal `\n` in abstract field breaking markdown rendering. See details below.
>
> **✅ SESSION 65 COMPLETE**: Markdown rendering for abstract field with XSS protection. See details below.
>
> **✅ SESSION 64 COMPLETE**: Deep Research Agent - Semantic Session IDs + Rate Limit Error Handling. See details below.
>
> **✅ SESSION 63 COMPLETE**: MCP Documentation Fix - `abstract` parameter. See details below.
>
> **✅ SESSION 62 COMPLETE**: Grace Period Message Bug Fix. See details below.
>
> **✅ SESSION 61 COMPLETE**: History Filter Race Condition Fix + Dropdown UX + UI Reorder. See details below.
>
> **✅ SESSION 60 COMPLETE**: Notifications UI Minor Tweaks - Action-required auto-expand, TTS queue empty state, Config reload button. See details below.
>
> **✅ SESSION 59 COMPLETE**: Deep Research Agent Voice-First CLI Testing + Notification Identity Implementation. See details below.
>
> **✅ SESSION 58 COMPLETE**: Gist Button UX, Recording Toggle Bug, Session Title Generation + Stop Token Sentinel Pattern. See details below.
>
> **✅ SESSION 57 COMPLETE**: Job Queue Progressive Disclosure UI - Full 6-phase implementation. See details below.
>
> **✅ COMPLETED**: Conversation Identity Architecture Phases 1-3 (Session 56) - parallel Claude Code sessions now distinguishable in notification UI. New sender_id format: `claude.code@{project}.deepily.ai#{session_id}`.

## Navigation

### Archive Links
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
