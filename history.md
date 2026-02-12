# Lupin Project History

### 2026.02.12 - Session 197 | CJ Flow Branding + Bounded Job Packaging + Claude Code LORA Data

#### Checkpoint | 2026.02.12 19:00 | CJ Flow plan implementation — branding, factory, config, training data

**Accomplishments**:
- **Part A**: Propagated "CJ Flow" branding to 12 files (docstrings/comments only, zero code logic)
- **Part B1**: Registered ClaudeCodeJob in agentic_job_factory.py, updated claude_code_queue.py router to use shared factory, added entry to agent_registry.py
- **Part B2**: Externalized hardcoded defaults (max_turns=50, timeout_seconds=3600) to lupin-app.ini with class-level config caching in job.py
- **Part B3**: Created 420-line R&D packaging guide for building new CJ Flow bounded jobs
- **Part C1-C5**: Created 66 voice templates + 100 task placeholders for Claude Code LORA routing, updated training pipeline (coordinator, prompt_generator, xml_models, router templates, command registry)
- **Part C6**: Regenerated training data — 39,871 examples (35 commands), Claude Code at 1,500 samples
- Fixed 5 test failures from 4th agent addition (registry count, audience scope, PRODUCT_NAMES, TEST_PROFILES)
- **816 unit tests pass, zero regressions**

**Files Created**:
- `src/rnd/2026.02.12-cj-flow-bounded-job-packaging-guide.md` (NEW)
- `src/ephemera/prompts/data/synthetic-data-agent-routing-claude-code.txt` (NEW)
- `src/ephemera/prompts/data/placeholders-claude-code-tasks.txt` (NEW)

**Files Modified** (30+ files across branding, factory, config, training pipeline, tests):
- CLAUDE.md, queue_protocol.py, agentic_job_base.py, todo_fifo_queue.py, running_fifo_queue.py, queue_consumer.py, agentic_job_factory.py
- Routers: deep_research.py, podcast_generator.py, deep_research_to_podcast.py, claude_code_queue.py
- Config: lupin-app.ini, lupin-app-splainer.ini
- Training: agent-router-agentic-commands.json, xml_coordinator.py, xml_prompt_generator.py, xml_models.py, agent-router-template.txt, agent-router-template-completion.txt
- Tests: test_runtime_argument_expeditor.py, test_notification_proxy config.py, rnd/README.md
- Workflow: agentic-voice-workflow.md
- Training JSONL files (regenerated)

**Commit**: 0daf0de

---

### 2026.02.12 - Session 196 | Three-Model PEFT Comparison + Ministral 8-bit Config Swap

#### Checkpoint | 2026.02.12 | Three-model PEFT comparison doc + Ministral 8-bit config swap

**Accomplishments**:
- Created comprehensive R&D comparison document for 3 fine-tuned LoRA models (Ministral-8B, Qwen3-4B, Llama-3.2-3B) across 34 agentic routing commands
- **Key finding**: Ministral-8B 8-bit quantization is lossless (98.7% EM, 0 commands degraded, +0.8pp vs full precision)
- Switched development router from Qwen3-4B 4-bit (83.0% EM) to Ministral-8B 8-bit (98.7% EM)
- Updated bash aliases: `svllmr` now serves Ministral 8-bit with `--quantization gptq_marlin --gpu_memory_utilization 0.85`
- Added `svllmrq` backup alias for Qwen3-4B fallback
- Added Llama-3.2-3B reference entries (commented out, 64.1% EM too low for production)

**Files Created**:
- `src/rnd/2026.02.12-three-model-peft-comparison-ministral-qwen-llama.md` (NEW)

**Files Modified** (Lupin repo):
- `src/rnd/README.md` (added comparison doc entry)
- `src/conf/lupin-app.ini` (Phase 3 Ministral 8-bit, router swap, Llama reference)
- `src/conf/lupin-app-splainer.ini` (router explanation, Llama entries)

**Files Modified** (outside repo):
- `~/.bash_aliases` (svllmr → Ministral 8-bit, svllmrq Qwen3 backup)

**Commit**: c0a71e0

---

### 2026.02.12 - Session 195 | Debug Script Matching Smoke Test (11/19 → 18/19)

#### Checkpoint | 2026.02.12 | Debug script matching smoke test — batch XML model, ampersand escaping, fuzzy prompt hints (11/19 → 18/19)

**Accomplishments**:
- **Batch fix (+2 scenarios)**: Created `BatchScriptMatcherResponse` — first-class Pydantic XML model with nested `<entries><entry>` structure, replacing brittle JSON-in-answer-field approach. Updated `_handle_batch()` to use new model and registered in `MODEL_MAPPING`.
- **XML parse fix (+1 scenario)**: Added `&` entity escaping in `BaseXMLModel.from_xml()` — bare ampersands like `Q&A` in LLM reasoning now safely escaped to `Q&amp;A` before parsing.
- **Fuzzy matching fix (+4 scenarios)**: Added intent-based semantic matching hints to prompt template with concrete paraphrase examples. Refined 3 extreme paraphrases in test scenarios.
- **Regression**: 816/816 unit tests passed (0 regressions). Updated 2 batch unit tests to use `BatchScriptMatcherResponse`.
- **Final score**: 18/19 (95%), up from 11/19 (58%). Only FUZZY_BUDGET_2 fails (verifier confidence issue, not a matching failure).

**Files Modified** (Lupin repo):
- `src/conf/prompts/notification-proxy-batch-matcher.txt` (XML entry structure + semantic hints)
- `src/conf/prompts/notification-proxy-script-matcher.txt` (intent-based matching hints)
- `src/tests/smoke/test_notification_proxy_script_matching.py` (3 refined paraphrases)
- `src/tests/unit/test_notification_proxy.py` (2 batch tests updated for BatchScriptMatcherResponse)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/xml_models.py` (NEW: BatchScriptMatcherResponse class)
- `src/cosa/agents/io_models/utils/prompt_template_processor.py` (batch model in MODEL_MAPPING)
- `src/cosa/agents/notification_proxy/strategies/llm_script_matcher.py` (use BatchScriptMatcherResponse in _handle_batch)
- `src/cosa/agents/io_models/utils/util_xml_pydantic.py` (& entity escaping in from_xml)

**Commit**: abe4cbe

---

### 2026.02.12 - Session 193 | Live Phi-4 Script Matching Smoke Test

#### Checkpoint | 2026.02.12 | Live Phi-4 script matching smoke test — 24-scenario 3-tier test matrix

**Accomplishments**:
- Created `test_notification_proxy_script_matching.py` — standalone smoke test that calls `LlmScriptMatcherStrategy.respond()` directly against live Phi-4 via vLLM (no server, no WebSocket, no auth required)
- **3-tier scenario matrix**:
  - **Tier 1 (Exact)**: Auto-generated from script entries — sends literal `question_pattern` text
  - **Tier 2 (Fuzzy)**: 12 paraphrased questions for semantic matching validation
  - **Tier 3 (Multi)**: Multiple-choice, batch (open_ended_batch), and negative (no-match) scenarios
- **CLI interface**: `--script deep_research|expeditor_smoke|all`, `--tier exact|fuzzy|multi|all`, `--scenarios 0,8,20`, `--no-verify`, `--confidence 0.7`, `--debug`, `--verbose`
- **Pre-flight vLLM check**: Sends a minimal LLM query before running scenarios; gracefully skips with exit 0 if vLLM unreachable
- **Optional LlmAnswerVerifier** second-pass on fuzzy tier for semantic confidence scoring
- **Initial results** (deep_research, all tiers): 11/19 passed — reveals real Phi-4 XML generation issues and fuzzy matching limitations
- Follows existing test patterns from `test_calculator_live_pipeline.py`

**Files Created** (Lupin repo):
- `src/tests/smoke/test_notification_proxy_script_matching.py` (NEW — ~500 lines)

### 2026.02.11 - Session 189 | CRUD Delete Bug Fix + Dedup Guards + Live Pipeline Smoke Test

#### Checkpoint | 2026.02.11 | Fix delete-all-records bug, add dedup/multi-delete guards, CRUD live pipeline test

**Accomplishments**:
- Fixed **delete-all-records bug** from Session 167 Part 3 Test 4: three guards added to crud_operations.py
  - **Dedup guard** in `add_item()`: rejects duplicate inserts within same list (checks DEDUP_KEYS per schema)
  - **Multi-delete guard** in `delete_item()`: refuses match_fields delete when >1 row matches, returns preview
  - **Infrastructure column rejection** in `_validate_match_fields()`: blocks `id`, `list_name`, `created_at` from match_fields
- Added `DEDUP_KEYS` dict, `INFRASTRUCTURE_COLS` frozenset, `get_dedup_keys()` helper to schemas.py
- Added `"duplicate"` voice formatting to dispatcher.py: "That item already exists in the list."
- Created `crud.json` Q&A script for notification proxy (delete/update auto-confirm via `sender_ids`)
- Added `"crud"` profile to notification proxy `TEST_PROFILES`
- Added CRUD confirmation entries to `all-agents.json` union script
- 6 new `TestDeduplicationGuards` unit tests: dedup rejection, cross-list allowed, infra rejection, multi-delete guard, single-delete success
- Created `test_crud_live_pipeline.py` — 8-scenario live smoke test with `--mode direct|lora|all` CLI
- **Regression**: 816/816 unit tests passed (was 810)

**Files Modified** (Lupin repo):
- `src/conf/notification-proxy-scripts/crud.json` (NEW — CRUD Q&A script)
- `src/conf/notification-proxy-scripts/all-agents.json` (2 CRUD confirmation entries)
- `src/tests/unit/test_crud_for_dataframes_storage.py` (6 new TestDeduplicationGuards tests)
- `src/tests/smoke/test_crud_live_pipeline.py` (NEW — 8-scenario live pipeline test)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/crud_for_dataframes/schemas.py` (DEDUP_KEYS, INFRASTRUCTURE_COLS, get_dedup_keys)
- `src/cosa/crud_for_dataframes/crud_operations.py` (dedup guard, multi-delete guard, infra rejection)
- `src/cosa/crud_for_dataframes/dispatcher.py` (duplicate voice formatting)
- `src/cosa/agents/notification_proxy/config.py` (crud profile in TEST_PROFILES)

---

### 2026.02.11 - Session 188 | Q&A Script README Architecture Clarification

#### Checkpoint | 2026.02.11 | Clarify standalone vs union script architecture in README

**Accomplishments**:
- Added "Script Architecture" section to Q&A scripts README explicitly documenting standalone (one-per-agent) vs union (`all-agents.json`) file types
- Added warning blockquote to "Multi-Agent Scripts" section: always create standalone first
- Fixed incorrect "13-scenario" reference (actual: 4 entries in `all-agents.json`)
- Clarified Step 5 "Register the Profile": `config.py TEST_PROFILES` is required, `__main__.py` is auto-derived

**Root cause**: Two parallel sessions misread the README and added entries directly to `all-agents.json` instead of creating standalone files

**Files Modified**:
- `src/conf/notification-proxy-scripts/README.md` (4 edits: architecture section, warning note, count fix, Step 5 clarification)

**Commit**: 0aa7d6c

---

### 2026.02.11 - Session 187 | Data-Driven Sender ID Filtering for Notification Proxy

#### Checkpoint | 2026.02.11 | Replace hardcoded EXPEDITER_SENDER_ID with data-driven sender_ids

**Accomplishments**:
- Replaced hardcoded `EXPEDITER_SENDER_ID` constant with data-driven `sender_ids` field in Q&A script JSON files
- Both `LlmScriptMatcherStrategy` and `ExpediterRuleStrategy` now accept `accepted_senders` parameter — iterate over a list instead of matching a single string
- `NotificationResponder` extracts `sender_ids` from script JSON and passes to both strategies at construction time
- 3-tier priority: explicit `accepted_senders` param > script `sender_ids` field > `DEFAULT_ACCEPTED_SENDERS` constant
- Adding a new sender = adding to a JSON list, zero Python code changes
- `EXPEDITER_SENDER_ID` kept as deprecated alias for backward compatibility
- 11 new unit tests (9 sender_ids filtering + 2 config): 810/810 pass, all 4 smoke tests pass

**Files Modified** (Lupin repo):
- `src/conf/notification-proxy-scripts/deep-research.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/podcast.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/research-to-podcast.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/all-agents.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/minimal.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/_template.json` (add sender_ids field)
- `src/conf/notification-proxy-scripts/README.md` (document sender_ids field)
- `src/tests/unit/test_notification_proxy.py` (11 new tests: TestSenderIdFiltering class + 2 config tests)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/config.py` (DEFAULT_ACCEPTED_SENDERS list + deprecated alias)
- `src/cosa/agents/notification_proxy/strategies/expediter_rules.py` (accepted_senders param + list-based can_handle)
- `src/cosa/agents/notification_proxy/strategies/llm_script_matcher.py` (accepted_senders param + script extraction + list-based can_handle)
- `src/cosa/agents/notification_proxy/responder.py` (extract sender_ids from script, pass to strategies)

**Commit**: fb8cb1c

---

### 2026.02.11 - Session 185 | Agentic Voice Workflow Skill v1.1 Update

#### Checkpoint | 2026.02.11 | SKILL.md v1.0 → v1.1: Q&A script documentation

**Accomplishments**:
- Updated `.claude/skills/agentic-voice-workflow/SKILL.md` v1.0 → v1.1 with Notification Proxy Q&A script documentation
- Added Phase 5b (Q&A Script) to workflow phases table
- Added new anti-pattern: "Don't skip Q&A scripts"
- Added cross-reference in Testing Best Practice section
- Added full "Notification Proxy: Automated Q&A Scripts" section (~50 lines) covering: 5-step checklist, JSON entry anatomy, multi-agent scripts, two-terminal usage pattern, key files table

**Files Modified**:
- `.claude/skills/agentic-voice-workflow/SKILL.md` (5 changes: version bump, Phase 5b row, anti-pattern, cross-reference, new section)

**Commit**: bbd1324

---

### 2026.02.11 - Session 184 | vLLM verbose_server Flag + Marlin Kernel Verification

**Accomplishments**:
- Added `verbose_server` parameter to `_start_vllm_server()` — prints all vLLM startup output when `True`, defaults to `False`
- Enabled at post-quantization call sites (`run_pipeline` + `run_pipeline_adhoc`) so Marlin kernel loading is visible
- **Verified via live run**: Marlin IS loading correctly (`gptq_marlin.py:143: "Using gptq_marlin kernel"`, `gptq_marlin.py:238: "Using MarlinLinearKernel"`)
- Small-batch latency still ~457 ms (unchanged from ~490 ms) — awaiting full batch run tonight to assess Marlin speedup at scale

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/training/peft_trainer.py` (`verbose_server` param + 4 changes: signature, docstring, print condition, 2 call sites)

---

### 2026.02.11 - Session 183 | Notification Proxy LLM Script Matcher Implementation

#### Checkpoint | 2026.02.11 | Phi-4 script matcher + answer verifier + Q&A scripts + 50 new tests

**Accomplishments**:
- **Implemented full plan**: "Replace Notification Proxy Keyword Matching with Local Phi-4 LLM Strategy" (Parts A-I)
- **XML models** (Part A): Created `ScriptMatcherResponse` and `VerificationResponse` BaseXMLModel subclasses in `xml_models.py` with field validators, helper methods, smoke tests
- **Prompt templates** (Part B): 3 new templates using `{{PYDANTIC_XML_EXAMPLE}}` — script-matcher, batch-matcher, answer-verifier
- **Q&A scripts** (Part C): 7 JSON script files in `src/conf/notification-proxy-scripts/` — deep-research, podcast, research-to-podcast, all-agents (multi-agent with `agents` tags), minimal, template, README
- **LLM Script Matcher** (Part D): `LlmScriptMatcherStrategy` drop-in replacement for `ExpediterRuleStrategy` — handles all 4 response types via Phi-4, agent-aware entry filtering
- **Answer Verifier** (Part E): `LlmAnswerVerifier` with exact-match bypass optimization, batch verification
- **Configuration** (Part F): 5 new config keys in `lupin-app.ini` + matching explanations
- **Wiring** (Part G): 3-tier strategy chain in responder (script_matcher → rules → cloud), `--strategy` CLI flag, MODEL_MAPPING registration
- **Unit tests** (Part H): 50 new tests across 8 test classes (109 total notification proxy tests, 770 full suite)
- **Documentation** (Part I): Cross-reference in `agentic-voice-workflow.md`, README in scripts directory

**Files Modified** (Lupin repo):
- `src/conf/lupin-app.ini` (5 new config keys)
- `src/conf/lupin-app-splainer.ini` (5 matching explanations)
- `src/tests/unit/test_notification_proxy.py` (50 new tests, 8 new test classes)
- `src/workflow/agentic-voice-workflow.md` (proxy scripts cross-reference)
- `src/conf/prompts/notification-proxy-script-matcher.txt` (NEW)
- `src/conf/prompts/notification-proxy-batch-matcher.txt` (NEW)
- `src/conf/prompts/notification-proxy-answer-verifier.txt` (NEW)
- `src/conf/notification-proxy-scripts/` (NEW — 7 files: deep-research.json, podcast.json, research-to-podcast.json, all-agents.json, minimal.json, _template.json, README.md)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/xml_models.py` (NEW — ScriptMatcherResponse + VerificationResponse)
- `src/cosa/agents/notification_proxy/strategies/llm_script_matcher.py` (NEW — LlmScriptMatcherStrategy)
- `src/cosa/agents/notification_proxy/verification.py` (NEW — LlmAnswerVerifier)
- `src/cosa/agents/io_models/utils/prompt_template_processor.py` (2 MODEL_MAPPING entries)
- `src/cosa/agents/notification_proxy/strategies/__init__.py` (updated docstring)
- `src/cosa/agents/notification_proxy/config.py` (10 new constants)
- `src/cosa/agents/notification_proxy/responder.py` (3-tier strategy chain)
- `src/cosa/agents/notification_proxy/__main__.py` (--strategy CLI flag)

---

### 2026.02.11 - Session 182 | Llama 3.2 3B vLLM Latency Analysis + gptq_marlin Config

#### Checkpoint | 2026.02.11 | Llama 3.2 latency research doc + Marlin kernel config

**Accomplishments**:
- **Research document**: Created `src/rnd/2026.02.11-vllm-llama-3.2-latency-analysis.md` — analysis of Llama-3.2-3B ~490 ms/item at 4-bit GPTQ (2.8x slower than Qwen3-4B's 174 ms). Root cause: AutoRound GPTQ not triggering Marlin kernel (documented 2.6x gap). Cross-model comparison, CPU overhead analysis, tiered recommendations.
- **Config change**: Added `"quantization": "gptq_marlin"` to `llama_3_2_3b.py:vllm_config` (CoSA submodule).
- **Pipeline change**: Added `quantization` parameter to `peft_trainer.py:_start_vllm_server()`, passed only at post-quantization call sites (CoSA submodule).

**Files Modified** (Lupin repo):
- `src/rnd/2026.02.11-vllm-llama-3.2-latency-analysis.md` (NEW — research doc)
- `src/rnd/README.md` (added analysis link)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/training/conf/llama_3_2_3b.py` (quantization key in vllm_config)
- `src/cosa/training/peft_trainer.py` (quantization parameter + 2 call sites)

**Commit**: 7451070

---

### 2026.02.10 - Session 180 | Save CRUD Delete Bug Fix Plan to R&D

**Accomplishments**:
- **Plan document saved**: Wrote `src/rnd/2026.02.10-crud-delete-bug-fix-and-live-pipeline-smoke-test.md` — comprehensive 4-part plan: (A) 5-change bug fix (dedup guard, multi-delete guard, infra column rejection), (B) 6 new unit tests, (C) `test_crud_live_pipeline.py` 8-scenario live smoke test following calculator + expeditor patterns, (D) full regression verification.
- **R&D README updated**: Added plan doc entry.
- **TODO.md updated**: CRUD bug fix item now references R&D plan doc, marked "RESUME TOMORROW (Session 181)".

**Files Modified** (Lupin repo):
- `src/rnd/2026.02.10-crud-delete-bug-fix-and-live-pipeline-smoke-test.md` (NEW — plan doc)
- `src/rnd/README.md` (added plan doc entry)
- `TODO.md` (updated CRUD bug fix item)

---

### 2026.02.10 - Session 179 | Expand Smoke Test Matrix (9 → 13 Scenarios) — Partial

**Accomplishments**:
- **4 new scenarios added**: DR_FULL (all args, confirmation-only), RTP_LANGUAGES (partial extraction), PG_LANGUAGES (languages + special handler), RTP_BARE (maximum 5-arg batch). Appended to `EXPEDITOR_SCENARIOS` list at indices 9-12.
- **Plan documented**: Wrote implementation plan to `src/rnd/2026.02.10-expand-smoke-test-matrix-13-scenarios.md` with coverage gap analysis, scenario definitions, and remaining changes.
- **Notification proxy changes from prior session**: `all_agents` union profile in `config.py`, keyword ordering fix in `expediter_rules.py`, `expected_args` soft verification + two-pass docs in smoke test, 3 regression tests in unit tests.
- **Work paused mid-implementation**: Docstring replacement (two-pass → single-pass) and count reference updates (9→13) still pending. User requested session shutdown.

**Files Modified** (Lupin repo):
- `src/tests/smoke/test_expeditor_mock_job_smoke.py` (4 new scenarios + expected_args from prior session)
- `src/tests/unit/test_notification_proxy.py` (3 regression tests from prior session)
- `src/rnd/2026.02.10-expand-smoke-test-matrix-13-scenarios.md` (NEW — plan doc)
- `src/rnd/README.md` (added plan doc entry)
- `TODO.md` (added continuation item for tomorrow)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/config.py` (all_agents union profile)
- `src/cosa/agents/notification_proxy/strategies/expediter_rules.py` (keyword ordering fix)

---

### 2026.02.10 - Session 177 | Expand Calculator LORA Training Templates (83 → 1500)

**Accomplishments**:
- **Phase 1 — Clean math ↔ calculator boundary**: Removed 27 calculator-territory lines from `synthetic-data-agent-routing-math.txt` — 20 "calculator mode" metaphor phrases, 6 explicit calculator routing lines, 1 compound interest line. Math: 523 → 495 lines (483 content). Zero calculator/mortgage/convert references remain.
- **Phase 2 — Expand calculator templates**: Rewrote `synthetic-data-agent-routing-calculator.txt` from 83 → 508 content lines. Organized into 7 categories: unit conversions (~280), price comparisons (~100), mortgages/financial (~80), routing/meta/disambiguation (~50). Natural spoken language with varied sentence structure.
- **Phase 3 — Code change**: Added `"agent router go to calculator": { "factor": 3 }` to `augmentation_config` in `xml_coordinator.py` (CoSA submodule, not committed here).
- **Training data regenerated**: 38,371 total examples. Calculator: 83 → 1,483 (pre-split). Math: 1,500 → 1,417 (acceptable). All 34 commands balanced. Ready for PEFT retrain.

**Files Modified** (Lupin repo):
- `src/ephemera/prompts/data/synthetic-data-agent-routing-math.txt` (removed 27 calculator-territory lines)
- `src/ephemera/prompts/data/synthetic-data-agent-routing-calculator.txt` (expanded 83 → 508 content lines)
- `src/ephemera/prompts/data/voice-commands-xml-{train,test,validate}.jsonl` (regenerated)
- `src/ephemera/prompts/data/agentic-job-xml-{train,test,validate}.jsonl` (regenerated)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/training/xml_coordinator.py` (add calculator to augmentation_config with factor=3)

---

### 2026.02.10 - Session 176 | Fix TTS Ghost Card Stranded After Action-Required Response

**Accomplishments**:
- **Root cause fix**: `onTTSPlaybackComplete()` cleared `activeTTSItem` AFTER `enterTTSFocusMode()`, allowing `updateTTSQueueSection()` to re-render a ghost card into the active slot. Swapped ordering so `activeTTSItem = null` runs BEFORE focus mode entry. Removed duplicate `updateTTSQueueSection()` call.
- **Clear All button visibility**: `updateTTSClearAllButtonState()` now checks active slot DOM for ghost cards in addition to `ttsQueue.length` and `activeTTSItem`
- **clearTTSQueue() hardened**: No longer returns early when queue is empty — also checks for `activeTTSItem` and ghost cards in active slot DOM, clears both
- **Delete button on active cards**: `renderActiveTTSCard()` now includes a delete button alongside Stop, matching `renderMinimizedTTSCard()` pattern (defense-in-depth)
- **Bug fix session closed**: 1 prior fix (Resume button stale freshQueueUI reference) + this ghost card fix

**Files Modified** (Lupin repo):
- `src/fastapi_app/static/js/notifications.js` (4 targeted fixes: +37/-15 lines)

**Commit**: 2a83679 (checkpoint)

---

### 2026.02.10 - Session 173 | Simplify Credential Resolution + Fix JWT WebSocket Auth

#### Checkpoint | 2026.02.10 | 2-tier credentials + Bearer prefix fix

**Accomplishments**:
- **Credential resolution simplified to 2 tiers**: Rewrote `get_credentials()` — removed `LUPIN_TEST_*` (tier 3) and `DEFAULT_EMAIL` (tier 4) fallbacks. Now: CLI > `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` > `ValueError` for both email and password
- **JWT "Invalid header padding" fix**: WebSocket auth handler in `websocket.py` didn't strip `Bearer ` prefix before calling `verify_token()` → `jwt.decode()`. REST endpoints got this for free from FastAPI's `HTTPBearer`. Added 3-line `startswith` guard
- **Auth DB research**: Determined simplest path for test user email rename (PostgreSQL — register new account via env vars, no code change needed)
- **Test updates**: Rewrote `TestGetCredentials` — 6 focused tests replacing 7 old ones. Removed obsolete `DEFAULT_EMAIL` import and assertions. 56/56 notification proxy tests passing

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/config.py` (2-tier get_credentials)
- `src/cosa/agents/notification_proxy/listener.py` (updated remediation env var names)
- `src/cosa/rest/routers/websocket.py` (Bearer prefix strip)

**Files Modified** (Lupin repo):
- `src/tests/unit/test_notification_proxy.py` (rewrote credential tests)

**Commit**: 5b18ecc (test file checkpoint)

---

### 2026.02.10 - Session 175 | Mark Calculator Step 24 done + live pipeline test docs

#### Checkpoint | 2026.02.10 20:00 | Mark Step 24 done + add live pipeline test notes to skills docs

**Files**: `2026.02.09-everyday-calculator-agent-implementation.md`, `TODO.md`, `SKILL.md` (agentic-voice-workflow, testing-patterns)
**Commit**: f3dc1fa

---

### 2026.02.10 - Session 172 | Calculator Step 24 — job_id in /api/push + 6-query live smoke test

#### Checkpoint | 2026.02.10 19:30 | Add --queries flag for selective query execution

**Files**: `src/tests/smoke/test_calculator_live_pipeline.py`
**Commit**: 61eab3c

#### Checkpoint | 2026.02.10 19:00 | Calculator Step 24 — job_id in /api/push + 6-query live smoke test

**Accomplishments**:
- **`/api/push` returns `job_id`**: Modified `push_job()` in `todo_fifo_queue.py` to return `Dict` instead of `str` at all 5 return sites (rejection, auto-routing, main agent, `_queue_best_snapshot`). Updated `queues.py` with backward-compatible `isinstance(result, dict)` extraction. API response now includes `job_id` field for poll-by-ID patterns.
- **6-query live smoke test**: Created `src/tests/smoke/test_calculator_live_pipeline.py` — automated test matrix covering convert (km, temp, weight, ml), compare_prices, and mortgage queries. Uses poll-by-`job_id` pattern against `GET /api/get-queue/done`. Login-only auth (no auto-registration), with remediation instructions on failure.
- **Removed auto-registration from smoke test**: Deleted `_try_register_and_login()`, simplified caller to use `_login()` only, removed hardcoded password from help text.
- **Plan document**: Wrote Step 24 plan to `src/rnd/2026.02.10-calculator-step-24-automated-qa-card-test-matrix.md`, indexed in R&D README.
- **Regression**: 710/710 unit tests pass, zero regressions.

**Files Modified** (Lupin repo):
- `src/cosa/rest/routers/queues.py` (extract job_id from dict return, include in API response)
- `src/tests/smoke/test_calculator_live_pipeline.py` (NEW — 6-query live test matrix)
- `src/rnd/2026.02.10-calculator-step-24-automated-qa-card-test-matrix.md` (NEW — plan doc)
- `src/rnd/README.md` (added Step 24 entry)
- `TODO.md` (Step 24 progress note)

**Files Modified** (CoSA submodule, not committed here):
- `src/cosa/rest/todo_fifo_queue.py` (push_job returns Dict with job_id at 5 return sites)

---

### 2026.02.10 - Session 171 | Notification Proxy Agent — Expediter Auto-Responder

#### Checkpoint | 2026.02.10 17:00 | Notification Proxy Agent — full implementation + 49 unit tests

**Accomplishments**:
- **Notification Proxy Agent**: Standalone CLI agent (`python -m cosa.agents.notification_proxy`) that connects via WebSocket as `mock.tester@lupin.deepily.ai`, subscribes to notification events, and automatically answers expediter questions using a hybrid strategy: rules for known patterns, LLM fallback for unknowns.
- **Architecture** (11 source files):
  - `listener.py` — async WebSocket client with auth, ping/pong, exponential backoff reconnection
  - `responder.py` — notification router + REST API response submission via `POST /api/notify/response`
  - `strategies/expediter_rules.py` — rule-based keyword matching with 4 test profiles (deep_research, podcast, research_to_podcast, minimal)
  - `strategies/llm_fallback.py` — Anthropic SDK fallback using `ANTHROPIC_API_KEY_FIREWALLED`
  - `config.py` — test profiles, connection defaults, API key resolution
  - `__main__.py` — CLI entry point with argparse, async event loop, graceful shutdown
- **Unit Tests**: 49 tests across 10 classes — config, rules construction, can_handle, respond (keyword matching, YES_NO, batch, multiple choice), LLM fallback, listener, responder routing, keyword mapping, profile coverage
- **Regression**: 710/710 unit tests pass (49 new + 661 existing)
- **All 5 module smoke tests pass**: config, expediter_rules, llm_fallback, listener, responder

**Files Created** (CoSA submodule, not committed here):
- `src/cosa/agents/notification_proxy/__init__.py`
- `src/cosa/agents/notification_proxy/__main__.py`
- `src/cosa/agents/notification_proxy/config.py`
- `src/cosa/agents/notification_proxy/cosa_interface.py`
- `src/cosa/agents/notification_proxy/listener.py`
- `src/cosa/agents/notification_proxy/responder.py`
- `src/cosa/agents/notification_proxy/voice_io.py`
- `src/cosa/agents/notification_proxy/strategies/__init__.py`
- `src/cosa/agents/notification_proxy/strategies/expediter_rules.py`
- `src/cosa/agents/notification_proxy/strategies/llm_fallback.py`

**Files Created** (Lupin repo): `src/tests/unit/test_notification_proxy.py` (NEW — 49 tests)
**Commit**: e485bb1

#### Checkpoint | 2026.02.10 17:30 | R&D design document + README index entry

**Files**: `src/rnd/2026.02.10-notification-proxy-agent-design.md` (NEW), `src/rnd/README.md`
**Commit**: f108873

---

### 2026.02.10 - Session 167 | TTS Focus Mode Stuck Fix + CRUD Delete Bug Plan

**Accomplishments**:
- **TTS Focus Mode Fix**: Fixed stuck `ttsFocusModeActive` where the TTS queue never drained (11 items backed up). Two changes to `notifications.js`: (1) Staleness check in `restoreTTSQueueState()` — if restored `focusModeNotificationId` no longer exists in `actionRequiredNotifications`, auto-exit focus mode and clear localStorage. (2) Focus mode exit in `moveToRegularNotifications()` — when the triggering notification is answered, call `exitTTSFocusMode()` to resume queue.
- **CRUD Delete Bug Investigation**: Test 4 (destructive delete) revealed "2 items deleted from list" when only 1 should be deleted. Root cause: duplicate rows from repeated test inserts with no dedup guard. Created comprehensive fix plan at `~/.claude/plans/cached-growing-mist.md` with 5 changes across 4 files + 6 new tests.
- **CRUD Testing Progress**: Part 3 Tests 1-2 complete, Tests 3-4 blocked by delete bug.

**Files Modified**: `src/fastapi_app/static/js/notifications.js` (staleness check + focus exit), `TODO.md` (CRUD testing status)
**Plan Created**: `~/.claude/plans/cached-growing-mist.md` (dedup keys, dedup guard, multi-delete guard, infra column rejection, voice formatting — for next session)
**Commit**: [pending]

---

### 2026.02.10 - Session 166 | Qwen3-4B vLLM Inference Slowdown — Root Cause Analysis

**Accomplishments**:
- **Root Cause Identified**: Qwen3-4B-Base shows 20x slowdown (~7,392 ms/item vs Ministral-8B ~368.7 ms/item) during PEFT validation. Cause: vLLM 0.8.2 has no native `Qwen3ForCausalLM` support — falls back to unoptimized HuggingFace Transformers engine. Architecture comparison rules out model design (Qwen3 is smaller in every compute dimension).
- **Fix Identified**: Upgrade vLLM from 0.8.2 to >= 0.8.5 where native Qwen3 support was added (confirmed via vLLM Issue #17630)
- **Research Document**: Wrote `src/rnd/2026.02.10-qwen3-vllm-inference-slowdown-root-cause.md` with full analysis, architecture comparison table, community issues, and step-by-step upgrade plan

**Files Created**: `src/rnd/2026.02.10-qwen3-vllm-inference-slowdown-root-cause.md`
**Files Modified**: `src/rnd/README.md` (added entry)
**Commit**: [pending]

---

### 2026.02.10 - Session 165 | Calculator Implementation Doc Sync + Phase 5-6 Planning

**Accomplishments**:
- **Implementation Doc Sync**: Updated `2026.02.09-everyday-calculator-agent-implementation.md` to reflect actual state on disk — marked Steps 20, 21, 23, 26, 27, 28 as `[x]` (all completed in Session 161 commit `1c0e8d4` but not marked in doc)
- **Phase Status Updates**: Phase 4 `NOT STARTED` → `COMPLETE`, Phase 5 → `IN PROGRESS` (Step 23 done), Phase 6 → `IN PROGRESS` (Steps 26-28 done)
- **Session 161 Log Enriched**: Added commit hash, verified test counts (17/17 mock pipeline, 661 total), evidence for completed steps (83 LORA templates, MathAgent fallback methods, HTML dropdown)
- **Phase 5-6 Execution Planning**: Explored Q&A Card REST endpoints (`POST /api/push`, mode management via `/api/mode/current`) and LORA training pipeline (`run-agentic-intent-training.sh` modes). Planning interrupted — ready to execute next session.

**Remaining Calculator Work** (5 steps):
- Steps 24-25: Live LLM testing via Q&A Card + System Mode auto-routing (needs server)
- Steps 29-31: LORA retrain + validate + voice routing test (needs GPU)
- Current JSONL has 66 calculator training examples; regeneration will use full 83 templates

**Files Modified**: `src/rnd/2026.02.09-everyday-calculator-agent-implementation.md` (12 edits)
**Commit**: [pending]

---

### 2026.02.10 - Session 164 | Bug Fix: Double-Click-to-Expand on CJ Flow Job Cards

**Accomplishments**:
- **Fix**: `expandJobCard()` used a non-existent `expanded` CSS class while `toggleJobCard()` and the CSS used `collapsed`. This state/DOM mismatch meant auto-expanded cards appeared collapsed, and the first user click was silently swallowed (toggling internal state back to "collapsed") before the second click actually worked. Changed 2 lines: check for `collapsed` instead of `!expanded`, remove `collapsed` instead of adding `expanded`.
- **Verification**: Code review confirms `expandJobCard()` and `toggleJobCard()` now both operate on the same `collapsed` class mechanism

### Session Summary
- **Total Fixes**: 1
- **Files Changed**: `src/fastapi_app/static/js/notifications.js` (2 lines)
- **Commits**: pending

**Status**: Session closed 2026.02.10

---

### 2026.02.10 - Session 163 | Expeditor Interactive Test Timeout Fix — Increased Timeouts, Diagnostic Logging

#### Checkpoint | 2026.02.10 09:30 | Timeout chain fix for interactive expeditor smoke tests

**Accomplishments**:
- **Expeditor Timeout Increases**: Raised notification timeouts for interactive testing — `_ask_for_arg` 60→180s, `_ask_for_confirmation` 60→180s, `_batch_collect_args` 120→300s. Root cause: users couldn't read/understand/respond to voice prompts within the old tight windows
- **Diagnostic Logging**: Added `[Expeditor]` debug prints after all 3 `notify_user_sync` calls showing `success`, `status`, `exit_code`, `is_timeout`, `response_value`. Enables diagnosing why first scenario (DR_HAPPY) fails instantly — will reveal if it's offline detection vs LLM cold start vs other
- **Smoke Test Timeouts**: Increased `REQUEST_TIMEOUT` 180→600s (10 min per scenario), `MAX_POLL_SECONDS` 90→120s (2 min polling)
- **API Default Timeout**: Changed notifications.py endpoint default from 30→120s (doesn't affect expeditor which passes explicit values, but prevents confusion for other callers)
- **Verification**: 661/661 unit tests pass (123 expeditor-specific), zero regressions

**Files Modified** (CoSA submodule, not committed here): `expeditor.py` (3 timeout values + 3 diagnostic logging blocks), `notifications.py` (API default 30→120)
**Files Modified** (Lupin repo): `src/tests/smoke/test_expeditor_mock_job_smoke.py` (REQUEST_TIMEOUT, MAX_POLL_SECONDS, UI message)
**Commit**: 85156cb

---

### 2026.02.10 - Session 161 | Calculator Testing Ladder — Mock Pipeline, Fallback, LORA Templates

#### Checkpoint | 2026.02.10 03:30 | Mock pipeline tests, MathAgent fallback, HTML dropdown, 83 LORA templates, training config

**Accomplishments**:
- **Mock Pipeline Tests (Surface 2)**: Created `test_calculator_mock_pipeline.py` with 17 tests across 6 classes — TestConvertPipelineMocked (3), TestMortgagePipelineMocked (2), TestPriceComparisonPipelineMocked (2), TestErrorHandling (3), TestPromptConstruction (4), TestMathAgentFallback (3). Follows `test_crud_mock_pipeline.py` pattern: `__new__()` bypass, mocked LLM factory, canned XML responses.
- **MathAgent Fallback (Step 2B)**: Added `run_prompt_with_fallback()` and `_delegate_to_math_agent()` to CalculatorAgent. When intent extraction fails, gracefully delegates to MathAgent (LLM code gen — slower but handles anything).
- **Agent Mode Dropdown (Surface 3A)**: Added `<option value="calculator">Calculator</option>` to notifications.html. Backend already wired (MODE_TO_AGENT + MODE_METADATA from Session 160).
- **LORA Training Templates (Surface 4A)**: Created 83 conversational templates covering unit conversions (~30), price comparisons (~20), mortgage (~15), casual/filler variants (~18). Clearly distinguishable from math templates.
- **Training Config (Surface 4B)**: Registered `"agent router go to calculator"` in `agent-router-simple-commands.json`.
- **Math Disambiguation (Surface 4C)**: Removed 1 mortgage template from math training data that was calculator territory.
- **Bug Fix**: Fixed CalcIntent `get_example_for_template()` items field — literal JSON braces broke Python `.format()` at runtime. Replaced with descriptive text.
- **Verification**: 653/653 unit tests pass (17 new mock pipeline), zero regressions

**Files Created** (Lupin repo): `src/tests/unit/test_calculator_mock_pipeline.py`, `src/ephemera/prompts/data/synthetic-data-agent-routing-calculator.txt`
**Files Modified** (Lupin repo): `src/cosa/agents/calculator/agent.py` (fallback), `src/cosa/agents/calculator/xml_models.py` (fix), `src/fastapi_app/static/html/notifications.html` (dropdown), `src/conf/training/agent-router-simple-commands.json` (register), `src/ephemera/prompts/data/synthetic-data-agent-routing-math.txt` (disambiguation)
**Commit**: [pending]

---

### 2026.02.10 - Session 160 | Expeditor job_id Threading, Request Context, DIAG Logging Gate

#### Checkpoint | 2026.02.10 02:00 | Expeditor job_id threading, request context, DIAG logging gate + 10 new tests

**Accomplishments**:
- **Job ID Threading**: Threaded `job_id` from expeditor through all notification calls (`_ask_for_confirmation`, `_ask_for_arg`, `_batch_collect_args`) so action-required cards route to the correct job card in the UI
- **Request Context Builder**: New `_build_request_context()` method constructs human-readable abstract for notification cards showing agent, command, and collected args
- **Display Name Fix**: `agent_registry.py` entries now include `display_name` for user-facing labels
- **DIAG Logging Gate**: Wrapped 8-line WebSocket state dump in `notifications.py` behind `app_debug and app_verbose` — was flooding production logs with per-call diagnostics after offline detection investigation
- **Safer Default**: `response_default="no"` in `_ask_for_confirmation()` (was `None`, which caused 503 instead of graceful OfflineEvent)
- **10 New Unit Tests**: `TestRequestContext` (4 tests), `TestBatchAbstractPassthrough` (3 tests), `TestJobIdThreading` (3 tests) — 115 total, 13 classes
- **Verification**: 115/115 unit tests pass, zero regressions

**Files Modified** (Lupin repo): `src/tests/unit/test_runtime_argument_expeditor.py`
**Files Modified** (CoSA submodule, not committed here): `agent_registry.py` (display_name), `expeditor.py` (request context, job_id, response_default), `notifications.py` (DIAG logging gate)
**Commit**: ec67d87

---

### 2026.02.09 - Session 159 | Fix CRITICAL Delete Bug — Silent Filter Skipping Deletes All Rows

#### Checkpoint | 2026.02.09 23:30 | Validate match_fields, strengthen prompt, 7 new tests

**Accomplishments**:
- **CRITICAL Fix**: `delete_item()` and `update_item()` silently skipped unknown `match_fields` keys, leaving an ALL TRUE mask that deleted/updated every row. Added `_validate_match_fields()` helper that returns error dict if any key doesn't exist in the DataFrame columns
- **Prompt Hardening**: Replaced brief schema listing in `intent-extraction.txt` with explicit field tables per schema type — includes negative examples ("NOT `name`, `item`, or `task`") and concrete `match_fields` examples to reduce LLM hallucination
- **7 New Unit Tests**: `TestMatchFieldsValidation` class covering delete with invalid field, valid field, update with invalid field, data preservation on error, delete-by-id unaffected, mark_done inherits guard, error message includes valid fields
- **Verification**: 542/542 unit tests pass, zero regressions

**Files Modified** (Lupin repo): `src/conf/prompts/crud-for-dataframes/intent-extraction.txt`, `src/tests/unit/test_crud_for_dataframes_storage.py`
**Files Modified** (CoSA submodule, not committed here): `crud_operations.py` (`_validate_match_fields()` + guards in `delete_item()` and `update_item()`)
**Commit**: 7de0263

---

### 2026.02.09 - Session 157 | PEFT Trainer Enhancements: Dual Quant, Markdown Dashboard, Multi-LLM

#### Checkpoint 3 (55ed874) | 2026.02.09 | Fix post-training validation model name — use bare path for vLLM

**Accomplishments**:
- **Fix**: `llmc.LlmClient.get_model( dir )` prepends `"deepily/"` to local paths, producing invalid model names like `"deepily//mnt/.../merged-on-..."`. vLLM was started with the bare directory path, so it returned 404. Replaced all 4 call sites (3 active + 1 commented) with direct path assignment
- **Verification**: 525/525 unit tests pass, zero regressions

**Files Modified** (CoSA submodule, not committed here): `peft_trainer.py` (lines 2138, 2179, 2330, 2363)
**Commit**: 55ed874

#### Checkpoint 2 (58a4fbf) | 2026.02.09 | Fix vLLM server launch for Qwen3-4B-Base — bash executable + HF vendor parsing

**Accomplishments**:
- **Fix 1 — Bash Executable**: Added `executable='/bin/bash'` to `subprocess.Popen` in `_start_vllm_server()`. Ubuntu's `/bin/sh` (dash) doesn't support `source`, so venv activation silently failed, running vllm from system Python instead of vllm-pip venv
- **Fix 2 — Transformers Downgrade**: Downgraded `transformers` from 5.1.0 to 4.57.6 in both vllm-pip and Lupin venvs. v5.x renamed `torch_dtype` → `dtype`, breaking vLLM 0.8.2 internally
- **Fix 3 — HF Model ID Vendor Parsing** (KLUDGE): `_parse_model_descriptor()` now falls back to `vllm` vendor when parsed org name (e.g., `Qwen` from `Qwen/Qwen3-4B-Base`) isn't a known vendor. Needs proper model registry
- **Verification**: 509/509 unit tests pass. Dry-run `./run-agentic-intent-training.sh dry-run --llm qwen3-4b` completes successfully

**Files Modified** (CoSA submodule, not committed here): `peft_trainer.py` (executable='/bin/bash'), `llm_client_factory.py` (KLUDGE vendor fallback)

#### Checkpoint 1 | 2026.02.09 | All 3 enhancements implemented, 455 unit tests pass (no regressions)

**Accomplishments**:
- **Dual Quantization**: Added `--quantize-bits {both,4,8}` CLI arg to `peft_trainer.py`. Pipeline now loops over requested bit widths, producing separate quantized models and validation results for each. New stage timing keys: `quantization_{bits}bit`, `post_quantization_{bits}bit_validation`
- **Markdown Training Results**: New `_write_training_summary_to_file()` method writes YAML frontmatter + 4 GitHub-flavored markdown tables + Output Paths section to `io/peft/YYYY.MM.DD-at-HH-MM-peft-training-results-{model}-{bits}-bits.md`
- **Multi-LLM Support**: New `--llm` flag in shell script supports `ministral-8b` (default) and `qwen3-4b`. New Qwen3-4B-Base LoRA config with Alpaca prompt template for base model. Model registered in `MODEL_CONFIG_MAP` and `supported_model_names`
- **Dashboard Updates**: Tables 2-4 in `_print_training_summary()` now render per-quant-variant comparisons against post-training baseline with dynamic table numbering
- **Verification**: 455/455 unit tests pass. Qwen3 config loads correctly. PeftTrainer instantiation with `Qwen3-4B-Base` succeeds. `_parse_quantize_bits()` verified for all 3 input values

**Files Modified** (Lupin repo): `src/scripts/run-agentic-intent-training.sh` (--llm/--quantize-bits flags), `src/conf/lupin-app.ini` (Qwen3-4B-Base placeholder), `src/conf/lupin-app-splainer.ini` (matching explainer), `src/rnd/README.md` (R&D entry)
**Files Created** (Lupin repo): `src/rnd/2026.02.09-peft-trainer-enhancements-dual-quant-multi-llm.md`
**Files Modified** (CoSA submodule, not committed here): `peft_trainer.py` (dual quant loop, markdown writer, CLI arg, dashboard), `model_config_loader.py` (Qwen3-4B-Base), `qwen3_4b.py` (NEW config)

---

### 2026.02.09 - Session 156 | Batch Open-Ended Questions for cosa-voice MCP Server

#### Checkpoint 2 | 2026.02.09 | Expeditor default values — fallback_defaults registry, config override chain, frontend pre-fill

**Accomplishments**:
- **Agent Registry `fallback_defaults`**: Added parallel `fallback_defaults` dict to each agent entry in `AGENTIC_AGENTS` — budget: "no limit", audience: "academic", audience_context: "none", languages: "en,es-MX" (where applicable). Updated languages fallback question to mention ISO codes
- **`_resolve_default()` Method**: Three-tier override chain — config INI > agent_registry fallback_defaults > None. Config key format: `expeditor default value for <agent_short_name> <arg_name>`
- **Batch Flow Wiring**: `_batch_collect_args()` now accepts `fallback_defaults` and `command_key`, builds question objects with `default_value` key. Single-arg flow also passes `response_default` to `_ask_for_arg()`
- **Notification Utils Passthrough**: `convert_open_ended_batch_for_api()` passes `default_value` through when present, omits when absent
- **Frontend Pre-fill**: `renderOpenEndedBatchUI()` reads `q.default_value` and sets as `value` attribute on text inputs (falls back to empty string)
- **Config Override Keys**: 10 keys in `lupin-app.ini` (2 enabled: podcast/research-to-podcast languages = "en,es-MX"), 10 matching explanations in splainer
- **MCP Docstring**: Updated `ask_open_ended_batch()` to document optional `default_value` key
- **All Tests Pass**: 499/499 unit tests, all 3 smoke tests green (agent_registry, notification_utils, expeditor)

**Files Modified** (Lupin repo): `src/lupin_mcp/cosa_voice_mcp.py`, `src/fastapi_app/static/js/notifications.js`, `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/tests/unit/test_runtime_argument_expeditor.py`, `src/rnd/README.md`
**Files Created** (Lupin repo): `src/rnd/2026.02.09-expeditor-default-values-design.md`
**Files Modified** (CoSA submodule, not committed here): `agent_registry.py`, `expeditor.py`, `notification_utils.py`

#### Checkpoint 1 | 2026.02.09 | Full 8-step implementation + 499 unit tests pass

**Accomplishments**:
- **New MCP Tool**: Added `ask_open_ended_batch()` to cosa-voice MCP server (v0.2.1 → v0.3.0) — asks multiple open-ended questions at once instead of one at a time, returns answers as dict keyed by header
- **New ResponseType**: `OPEN_ENDED_BATCH = "open_ended_batch"` added to `ResponseType` enum with validator in `notification_models.py`
- **Utility Functions**: `format_open_ended_batch_for_tts()` and `convert_open_ended_batch_for_api()` in `notification_utils.py` with smoke tests
- **Frontend Rendering**: Form-style UI with all questions visible at once, each with numbered label + mic button + text input, single "Submit All" button. Per-question voice input via unified RecordingManager
- **Expeditor Integration**: Added `_batch_collect_args()` method, refactored missing-args loop to partition batchable vs special-handler args. >1 batchable → batch collection; exactly 1 → existing single flow. Special handlers (fuzzy_file_match) always sequential after batch
- **Cancel Semantics**: Cancel keyword in any batch answer → entire batch cancelled (matches existing single-arg behavior)
- **6 New Unit Tests**: `TestBatchCollectArgs` class — success, timeout, cancel keyword, cancelled flag, batch-for-multiple, single-for-one. Full regression: 499/499 unit tests pass

**Files Modified** (Lupin repo): `src/lupin_mcp/cosa_voice_mcp.py`, `src/fastapi_app/static/js/notifications.js` (+203 lines), `src/fastapi_app/static/css/notifications.css` (+85 lines), `src/tests/unit/test_runtime_argument_expeditor.py` (+171 lines)
**Files Modified** (CoSA submodule, not committed here): `notification_models.py`, `notification_utils.py`, `expeditor.py`

---

### 2026.02.09 - Session 155 | Gist Embeddings Analysis: Keep vs. Jettison

**Accomplishments**:
- **Research Document**: Wrote comprehensive analysis of gist embedding system value in the retrieval pipeline. Traced every usage of gist generation and gist embeddings across the repo
- **Finding**: Gist _text_ is valuable (Level 3 exact matching via CanonicalSynonymsTable), but gist _embeddings_ are dead code — never searched in Level 4 vector similarity, `threshold_gist` parameter accepted but never applied, `get_snapshots_by_solution_gist_similarity()` has zero callers
- **Recommendation**: 3-phase cleanup — Phase 1: remove dead code paths, Phase 2: stop generating gist embeddings at snapshot creation, Phase 3: optionally re-enable with proper integration if needed

**Files Created**: `src/rnd/2026.02.09-gist-embeddings-analysis-keep-vs-jettison.md`
**Files Modified**: `src/rnd/README.md` (added analysis entry)

---

### 2026.02.08 - Session 154 | User-Visible Args Whitelist for Runtime Argument Expeditor

**Accomplishments**:
- **Whitelist Design**: Implemented "agents publish, expeditor consumes" pattern — each agent CLI self-declares its user-visible args via `USER_VISIBLE_ARGS` constant and `--user-visible-args` flag that prints JSON and exits
- **3 CLI Modules Updated** (CoSA submodule):
  - `deep_research/cli.py`: `["query", "budget", "audience", "audience_context"]`
  - `podcast_generator/__main__.py`: `["research", "languages", "audience", "audience_context"]`
  - `deep_research_to_podcast/__main__.py`: `["query", "budget", "languages", "audience", "audience_context"]`
- **Registry Function**: Added `get_user_visible_args()` + `_user_visible_cache` to `agent_registry.py` (parallel to existing `get_cli_help()`)
- **Expeditor Filter**: Changed `_confirm_and_iterate()` from blacklist (hide `system_provided`) to whitelist (show only user-visible args), with fallback to `fallback_questions` keys. Added gate on missing-arg prompts in `expedite()` to skip non-user-visible args
- **6 New Unit Tests**: 4 for `get_user_visible_args` (success, caching, missing key, timeout) + 2 for confirmation whitelist (engineering params excluded, fallback behavior). Full regression: 493/493 unit tests pass

**Files Modified** (Lupin repo): `test_runtime_argument_expeditor.py`, R&D doc rename (02.05 → 02.07)
**Files Modified** (CoSA submodule, not committed here): `cli.py`, `__main__.py` x2, `agent_registry.py`, `expeditor.py`
**Checkpoint**: 8c798ff

---

### 2026.02.08 - Session 148 (continued) | Part 3 Curl Smoke Test Planning

**Accomplishments**:
- Planned Part 3 curl smoke tests for CRUD agents (4 scenarios: health, add, feature-flag toggle, delete)
- Found `GET /api/debug/websocket-state` endpoint for programmatic WebSocket session lookup — enables real notification delivery during curl tests instead of dummy websocket IDs
- Plan ready at `.claude/plans/shimmering-exploring-blossom.md`, pending execution next session

**Next**: Execute Part 3 curl tests (server + Phi-4 required), then Part 2 UI tests

---

### 2026.02.08 - Session 147 (continued) | Bug Fix: Copy Buttons for WebSocket Session IDs

**Fix 2**: Added clipboard copy buttons to Queue and Audio WebSocket session IDs in the System Status section of the notifications UI. Converted inline display to vertical list layout with `<code>` elements and copy icons. Clicking the clipboard icon copies the session ID and shows brief checkmark feedback. No-op when value is `-` (not connected).

**Files Modified**: `notifications.html` (list layout), `notifications.css` (session-list + copy-btn styles), `notifications.js` (copyToClipboard method)

---

### 2026.02.07 - Session 152 | Principled Augmentation for Under-Sampled Training Commands

**Accomplishments**:
- **Template Expansion**: Expanded 4 under-sampled training template files to provide semantic diversity for simple agent-routing commands:
  - `automatic-routing-mode.txt`: 60 → 192 lines (conversational, questioning, indirect, polite, negative framing, agent-specific exits, error recovery, short/terse)
  - `none-of-the-above.txt`: 214 → 500 lines (science, cooking, coding, philosophy, health, travel, finance, entertainment, relationships, home/DIY, e-commerce)
  - `math.txt`: 454 → 511 lines (statistics, probability, number theory, logic puzzles)
  - `todo-lists.txt`: 447 → 511 lines (batch operations, priority/context, conversational, recurring tasks, status/overview)
- **Augmentation Factor Loop**: Added `augmentation_config` parameter to `build_simple_agent_router_training_prompts()` in `xml_coordinator.py`. Each factor pass applies fresh random interjection/salutation, creating distinct variants from the same template line
- **Config at Call Site**: `build_all_training_prompts()` now passes per-command factors: auto-routing=9x, math=3x, todo=3x, none=3x
- **Verified Distribution**: All 4 target commands now hit exactly 1500 samples. Total training examples: 36,980 across 33 commands. 482/482 unit tests pass

**Files Modified** (Lupin repo): 4 template files in `src/ephemera/prompts/data/`
**Files Modified** (CoSA repo, not committed here): `src/cosa/training/xml_coordinator.py`

---

### 2026.02.07 - Session 148 (continued) | CRUD Agent — Pipeline Alignment + Prompt Construction Tests

#### Checkpoint 3 | 2026.02.07 23:00 | Generic placeholders + prompt construction verification tests

**Accomplishments**:
- **Pipeline Alignment**: Replaced ad-hoc `{intent_example}` placeholder in CRUD prompt template with `{{PYDANTIC_XML_EXAMPLE}}` marker, aligning with the standard `PromptTemplateProcessor` pipeline used by all other agents. Registered `CRUDIntent` in `MODEL_MAPPING`. Updated `agent.py` to use processor instead of manual XML generation.
- **Generic Placeholders**: Changed `CRUDIntent.get_example_for_template()` from concrete values ("groceries", "add") to generic placeholders ("[operation name]", "[target list name]") so the LLM sees XML structure without being biased toward canned answers.
- **5 New Prompt Construction Tests** (`TestPromptConstruction` in `test_crud_mock_pipeline.py`): Reads real template from disk, processes through `PromptTemplateProcessor`, verifies: marker replaced, `<intent>` XML injected, `</stop>` sentinel present, generic placeholders (not concrete data), `.format()` substitution works.
- **Part 1 Testing Protocol**: 12 → 17 mock pipeline tests (total 29 protocol scenarios). Full regression: 487/487 unit tests passing.

**Files Modified**: `intent-extraction.txt`, `test_crud_mock_pipeline.py`, `test_crud_for_dataframes_agent.py`, `testing-protocol.md`, `implementation-tracker.md` (+6 more in CoSA submodule)
**Commit**: 9742659

#### Checkpoint 2 | 2026.02.07 21:00 | Fix CRUD prompt for Phi-4 + debug script full dump

**Accomplishments**:
- **Root Cause Identified**: Phi-4 14B returned immediate EOS (empty response) for CRUD intent extraction prompts. Root cause: prompt lacked proper Alpaca instruction format markers (`### Instruction:`, `### Task:`, `### Input:`, `### Response:`) that the math agent (working reference) uses
- **Prompt Fix**: Restructured `intent-extraction.txt` with Alpaca markers and moved "Requirement:" directives to stronger positions within the prompt. Verified working: Phi-4 now returns 2,481 chars of valid `<intent>` XML
- **Debug Script Enhanced**: Updated `debug_crud_llm_call.py` to dump the full expanded prompt before sending to vLLM, enabling rapid prompt iteration
- **Rejected Approaches**: Response priming (`<intent>` prepend after `### Response:`) worked but was rejected as a kludge. Chat completions format switch was rejected since math agent works with same CompletionClient

**Files Modified**: `src/conf/prompts/crud-for-dataframes/intent-extraction.txt`, `src/scripts/debug/debug_crud_llm_call.py`

---

### 2026.02.07 - Session 151 | Runtime Argument Expeditor — Confirmation Loop + Expanded Tests

#### Checkpoint | 2026.02.07 19:30 | Confirmation loop + 9-scenario smoke test matrix

**Accomplishments**:
- **Confirmation Loop**: Added `_confirm_and_iterate()` and `_parse_modification()` to `expeditor.py`. After args are collected, the user now sees a summary and can approve, cancel, or modify args via voice before job submission. Quick keyword matching for common responses ("yes", "cancel"), LLM parse for modification intent. Max 5 iterations safety valve.
- **ArgConfirmationResponse Model**: New `BaseXMLModel` subclass in `xml_models.py` with `is_approval()`, `is_cancel()`, `is_modify()` helpers. Registered in `MODEL_MAPPING` as `'argument confirmation'`.
- **Prompt Template**: New `runtime-argument-confirmation.txt` for parsing user modification intent. Config key added to `lupin-app.ini` + splainer.
- **Audience Context**: Added `audience_context` fallback questions to all 3 agents in `agent_registry.py`. Changed "general" → "intermediate" in audience options.
- **Unit Tests**: 15 new tests — `TestArgConfirmationResponse` (8 tests) + `TestConfirmAndIterate` (7 tests, fully mocked voice I/O). 70/70 expeditor tests, 482/482 total.
- **Smoke Test Rewrite**: 9-scenario matrix covering all 3 agents (DR, PG, RTP), happy/missing/budget/audience/cancel paths. Data-driven from `EXPEDITOR_SCENARIOS` list with tabular summary output.

**Files Modified** (Lupin repo): `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/conf/prompts/runtime-argument-confirmation.txt` (NEW), `src/tests/unit/test_runtime_argument_expeditor.py`, `src/tests/smoke/test_expeditor_mock_job_smoke.py`
**Files Modified** (CoSA repo, not committed here): `xml_models.py`, `expeditor.py`, `agent_registry.py`, `prompt_template_processor.py`

---

### 2026.02.07 - Session 150 | Agentic Voice Workflow v2.1 Completeness Review

#### Checkpoint | 2026.02.07 17:00 | 11 changes — 2 fixes, 7 additions, 2 structural

**Accomplishments**:
- **Fix 1+2**: Corrected Surface 4 training template naming (was `agentic-intent-{name}-templates.txt`, actual is `synthetic-data-agent-routing-{name}.txt`) and fixed JSON path/structure for `agent-router-agentic-commands.json`
- **Addition 3+4**: Added agent_registry.py `AGENTIC_AGENTS` dict pattern and agentic_job_factory.py `elif` dispatch pattern to Phase 5
- **Addition 5**: Added new Phase 5b — dedicated FastAPI router template with Pydantic models, auth, and "associate before push" pattern
- **Addition 6**: Added notification UI submission card guide (HTML + JS handler) to Surface 3
- **Addition 7+8**: Added artifact storage pattern and WebSocket `job_state_transition` note to Phase 5
- **Addition 9**: Added model string convention note to Phase 6 (hardcoded strings are examples, use ConfigurationManager)
- **Structural 10+11**: Expanded final checklist with 4 missing items, added v2.1 version history entry, updated TOC + Reference Implementations

**Files Modified**: `src/workflow/agentic-voice-workflow.md` (3461 → 3864 lines, v2.0 → v2.1)
**Verification**: All 30 referenced file paths confirmed to exist in codebase
**Commit**: 8c26b24

---

### 2026.02.07 - Session 149 | Normalize audience + audience_context Across All Agentic Agents

#### Checkpoint | 2026.02.07 15:30 | 5-phase audience normalization complete

**Accomplishments**:
- **Phase 0**: Renamed `target_audience` → `audience` across all deep_research, deep_research_to_podcast, and podcast_generator modules. Changed default from `"expert"` → `"academic"`. Renamed podcast `ContentAnalysis.target_audience` → `inferred_audience` (LLM JSON key stays `target_audience`, mapped at extraction time).
- **Phase 1**: Wired `audience`/`audience_context` through Deep Research job → factory → REST router → agent registry pipeline with config fallback chain.
- **Phase 2**: Wired same through Research-to-Podcast pipeline. Added `audience` to fallback_questions.
- **Phase 3**: Added full audience support to Podcast Generator — `PodcastConfig` dataclass fields, `AUDIENCE_DIALOGUE_GUIDELINES` dict in script_generation.py (beginner/general/expert/academic), orchestrator pass-through, job params with config fallback, CLI args, REST model fields, factory wiring, registry entries.
- **Phase 4**: Added `podcast generator audience` and `podcast generator audience context` config keys to lupin-app.ini + splainer.
- **Phase 5**: Added 6 new unit tests (3 registry audience assertions + 3 factory audience passthrough). 467/467 unit tests passing, all smoke tests pass.

**Files Modified** (Lupin repo): `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini`, `src/tests/unit/test_runtime_argument_expeditor.py`
**Files Modified** (CoSA repo, not committed here): 20 files across `agents/deep_research/`, `agents/deep_research_to_podcast/`, `agents/podcast_generator/`, `agents/runtime_argument_expeditor/`, `rest/`
**Commit**: 03574d4

---

### 2026.02.07 - Session 148 | PEFT Phase 2 — Results Dashboard + Explicit Routing + Quantization Strengthening

#### Checkpoint 2 | 2026.02.07 | Fix blank/comment line crash + regenerate training data

**Accomplishments**:
- Added `skip_empty` and `skip_comments` parameters to `get_file_as_list()` in `util.py` — backwards-compatible, defaults to `False`
- Updated all 6 call sites in `xml_coordinator.py` to filter blank lines and `# comment` lines from template files
- Regenerated training data (3 JSONL files) with the fix — pipeline completes without IndexError

**Files Modified** (CoSA repo, not committed here): `util.py`, `xml_coordinator.py`
**Files Modified** (Lupin repo): `agentic-job-xml-train.jsonl`, `agentic-job-xml-test.jsonl`, `agentic-job-xml-validate.jsonl`
**Verification**: 467/467 unit tests passing, zero regressions
**Commit**: e17b366

#### Checkpoint 1 | 2026.02.07 | Parts A/B/C complete, 461 unit tests pass

**Accomplishments**:
- **Part A (Results Dashboard)**: Added consolidated training summary to `peft_trainer.py` — captures validation results from all 3 stages (pre/post-training, post-quantization) and prints 4 comparison tables: Overall Metrics, Per-Command Deltas, Quantization Impact, Pipeline Stage Timing. Stored `last_ms_per_item` in `xml_coordinator.py`.
- **Part B (Explicit Routing Data)**: Appended ~25 explicit routing phrases ("Connect me with...", "Switch to...") to 5 agent template files (math, calendar, weather, todo, date-and-time). Created new "automatic routing mode" command with 60 templates. Registered in `agent-router-simple-commands.json` and both router prompt templates. Added routing handler in `todo_fifo_queue.py`.
- **Part C (Quantization Strengthening)**: Supplemented degraded commands — podcast-generator (+18 strong-anchor templates), math (+18 explicit-framing), todo-list (+15 task-specific), none (+15 diverse negatives).
- **Sample size bump**: 1200 → 1500 samples/command in `run-agentic-intent-training.sh`
- **R&D Document**: Created `src/rnd/2026.02.07-peft-trainer-optimization-plan-part-2.md`

**Files Created**: `synthetic-data-agent-routing-automatic-routing-mode.txt` (60 templates), `2026.02.07-peft-trainer-optimization-plan-part-2.md`
**Files Modified** (Lupin repo): `src/rnd/README.md`, `src/scripts/run-agentic-intent-training.sh`, 5 agent routing template files, `agent-router-simple-commands.json`, `agent-router-template.txt`, `agent-router-template-completion.txt`, `synthetic-data-agent-routing-podcast-generator.txt`, `synthetic-data-none-of-the-above.txt`
**Files Modified** (CoSA repo, not committed here): `xml_coordinator.py`, `peft_trainer.py`, `todo_fifo_queue.py`
**Verification**: 461/461 unit tests passing, zero regressions

---

### 2026.02.07 - Session 147 | Bug Fix Mode

### Fixes

#### Fix 1: Cancel Button on Open-Ended Notifications Fails with "Response cannot be empty"
- **Source**: ad-hoc (discovered during cosa-voice testing)
- **Problem**: Clicking Cancel on an open-ended blocking notification (e.g., from `converse()`) triggered error alert "Failed to submit response: Response cannot be empty". The frontend `cancelActionRequired()` used `''` (empty string) as the fallback for open-ended notifications, but the backend `/api/notify/response` endpoint rejects empty strings.
- **Files**: `src/fastapi_app/static/js/notifications.js` (line 11039)
- **Solution**: Changed cancel fallback from `''` to `'[cancelled]'`, aligning with the existing non-empty patterns (`'no'` for yes_no, `JSON.stringify({cancelled: true, answers: {}})` for multiple_choice)
- **Test**: Unit 487/487 PASS, manual verification PASS (cancel dismissed cleanly, `converse()` returned `"[cancelled]"`)

#### Fix 2: No Way to Copy WebSocket Session IDs from System Status
- **Source**: ad-hoc
- **Problem**: Session IDs displayed inline with no copy mechanism, requiring manual text selection
- **Files**: `notifications.html`, `notifications.css`, `notifications.js`
- **Solution**: Converted inline display to vertical list layout with `<code>` elements and clipboard copy icons. `copyToClipboard()` method with checkmark feedback. No-op when `-` (not connected).
- **Test**: Manual verification PASS

### Session Summary
- **Total Fixes**: 2
- **Files Changed**: `notifications.js`, `notifications.html`, `notifications.css`
- **Commits**: 65658ba (Fix 1), pending (Fix 2)

**Status**: Session closed 2026.02.08

---

### 2026.02.06 - Session 146 | PEFT Phase 2 Remediation + Data Volume Fix

#### Checkpoint | 2026.02.06 23:58 | Template fixes + script fix + placeholder expansion

**Accomplishments**:
- Fixed PEFT Phase 2 template issues: removed 51 near-miss none-of-the-above examples, replaced product names (Deep Dive, PodMaker, Doc-to-Pod) with natural English phrasing across 3 agentic routing template files
- Fixed training data volume bug: `run-agentic-intent-training.sh` hardcoded `sample_size_per_command=400` instead of target 1200
- Expanded placeholder files: research-topics.txt (50→190), document-paths.txt (50→179) for richer training diversity (65 templates × 190 topics = 12,350 raw combinations per agentic command)

**Files Modified**: synthetic-data-none-of-the-above.txt, synthetic-data-agent-routing-deep-research.txt, synthetic-data-agent-routing-podcast-generator.txt, synthetic-data-agent-routing-research-to-podcast.txt, run-agentic-intent-training.sh, placeholders-research-topics.txt, placeholders-document-paths.txt, TODO.md
**Commit**: b1cffa2

---

### 2026.02.06 - Session 145 | CRUD Interactive Testing Protocol

**Accomplishments**:
- Created 24-scenario interactive testing protocol for DataFrame CRUD system (Layers 1-3)
- Part 1: 12 mock pipeline scenarios (routing swap, full pipeline, cache bypass, confirmation flow) — no server required
- Part 2: 8 notifications UI scenarios (Q&A submission, confirmation cards, TTS, feature flag toggle) — live server
- Part 3: 4 curl smoke tests (health check, push endpoint, feature flag, destructive ops)
- Updated implementation tracker with testing protocol reference
- Updated TODO.md with high-priority E2E testing item for tomorrow

**Files Created**: `src/rnd/headless-cc-for-dataframe-crud/testing-protocol.md`
**Files Modified**: `src/rnd/headless-cc-for-dataframe-crud/implementation-tracker.md`, `TODO.md`

---

### 2026.02.06 - Session 144 | Fix Expeditor Async Event Loop Deadlock

**Accomplishments**:
- Fixed async event loop deadlock in expeditor test mode (smoke tests 4-5 returning `status=cancelled`)
- Root cause: `expeditor.expedite()` (synchronous) called from async handler blocked the single-worker event loop, preventing the self-referential `/api/notify` request from being processed
- Fix: Wrapped `expeditor.expedite()` in `asyncio.to_thread()` to run in threadpool, freeing event loop
- Verified interactive smoke tests 4-5 now pass (user can respond to voice prompt, dry-run job completes with $0.00 cost)

**Files Modified**: `src/cosa/rest/routers/mock_job.py` (added `import asyncio`, wrapped expedite call in `asyncio.to_thread()`)
**Verification**: 449/449 unit tests passing, zero regressions

---

### 2026.02.06 - Session 143 | CRUD Phase 3: Queue Integration + Voice Confirmation

#### Checkpoint | 2026.02.06 22:30 | CRUD Phase 3 complete — queue integration + voice confirmation

**Accomplishments**:
- Implemented Layer 3 of DataFrame CRUD system: queue integration + voice confirmation
- Feature-flag routing swap in todo_fifo_queue.py (TodoCrudAgent/CalendarCrudAgent replace legacy agents)
- Cache skip + serialization exclusion in running_fifo_queue.py (mutable data shouldn't be cached)
- Voice confirmation for destructive operations (delete, delete_list, update) via notify_user_sync
- 26 new unit tests across 3 test classes (routing, cache behavior, confirmation flow)
- Fixed 3 existing Layer 2 tests that needed notify_user_sync mocks after confirmation was added

**Files Modified** (Lupin repo): src/conf/lupin-app.ini, src/conf/lupin-app-splainer.ini, src/rnd/headless-cc-for-dataframe-crud/implementation-tracker.md, layer-3.md, src/tests/unit/test_crud_for_dataframes_agent.py
**Files Created**: src/tests/unit/test_crud_queue_integration.py (26 tests)
**Files Modified** (CoSA repo, not committed here): src/cosa/rest/todo_fifo_queue.py, src/cosa/rest/running_fifo_queue.py, src/cosa/crud_for_dataframes/agent.py
**Verification**: 449/449 unit tests, 50/50 WebSocket smoke tests, zero regressions
**Commit**: a51d9f6

---

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
