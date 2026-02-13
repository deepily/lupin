# DataFrame CRUD Implementation Tracker

**Last Updated**: 2026-02-09

## Cross-Phase Progress

| Phase | Layer | Status | Key Milestone |
|-------|-------|--------|---------------|
| 1 | Layer 1: Storage | COMPLETE | 91 unit tests, 16 smoke tests, all passing |
| 2 | Layer 2: Intent | COMPLETE | 73 unit tests, 5 new source files + 1 modified + 1 test file |
| 3 | Layer 3: Queue Integration | COMPLETE | 26 unit tests, feature-flag routing swap + cache skip + voice confirmation |
| E2E | Testing Protocol Part 1 | COMPLETE | 17 mock pipeline tests (routing, pipeline, cache, confirmation, prompt construction) |
| E2E | Bug Fix: CRUD Completion | COMPLETE | emit_job_state_transition + answer guard + done queue (3 unit tests, 532/532 pass) |
| E2E | Testing Protocol Part 3 | IN PROGRESS | Curl Test 2 verified card transition running→done. TTS blocked by pre-existing stuck focus mode (separate issue). Manual re-run pending. |
| E2E | Testing Protocol Part 2 | PENDING | Manual UI tests (Q&A, confirmation cards, feature flag toggle) |
| 4 | Layer 3: Polish | NOT STARTED | End-to-end voice workflows |

> **Recommended execution order**: Part 1 (mock) → Part 3 (curl) → Part 2 (UI). Curl validates server routing before UI tests the full notification card flow.

## E2E Testing Protocol Part 1 — Mock Pipeline (2026-02-07)

| Step | Component | Status |
|------|-----------|--------|
| 1 | TestRoutingSwapPipeline (3 tests) | Done |
| 2 | TestFullPipelineMocked (3 tests) | Done |
| 3 | TestCacheBypassPipeline (2 tests) | Done |
| 4 | TestConfirmationFlowPipeline (4 tests) | Done |
| 5 | TestPromptConstruction (5 tests) | Done |

### Part 1 Verification Results (2026-02-07)

- Part 1 mock pipeline tests: 17/17 passed (1.95s)
- Full unit suite: 487/487 passed (9.82s, zero regressions)
- Test file: `src/tests/unit/test_crud_mock_pipeline.py`
- Note: Placed in `unit/` instead of `integration/` because integration conftest requires live server; these tests are fully mocked

### Part 1 Test Coverage

| Test Class | Count | What It Tests |
|------------|-------|---------------|
| TestRoutingSwapPipeline | 3 | Feature flag true/false, todo/calendar routing |
| TestFullPipelineMocked | 3 | Full add/query/delete pipeline: run_prompt → run_code → run_formatter |
| TestCacheBypassPipeline | 2 | CRUD agents skip cache, non-CRUD agents don't |
| TestConfirmationFlowPipeline | 4 | Delete yes/no/timeout, add skips confirmation |
| TestPromptConstruction | 5 | Real template + PromptTemplateProcessor: marker, XML, sentinel, placeholders, format() |

### Testing Protocol Discrepancy Found

- `query` operation returns `status: "ok"` not `"queried"` (protocol had wrong assertion)

---

## E2E Bug Fix: CRUD Agent Completion (2026-02-09)

Three bugs found during Part 3 curl testing prevented CRUD agent jobs from completing properly:

| Fix | File | Issue | Resolution |
|-----|------|-------|------------|
| Fix 1 | `running_fifo_queue.py:474-481` | `emit_job_state_transition()` only fired for serializing agents | Fire for ALL agents unconditionally |
| Fix 2 | `running_fifo_queue.py:489-493` | CRUD agent answer overwritten with canned `"Hmm, I'm having trouble..."` string | Guard: only overwrite if `agent.answer` is empty |
| Fix 3 | `running_fifo_queue.py:545-557` | CRUD agents not pushed to done queue | Push ALL agents to done queue, not just serializing ones |

### Verification
- 3 new unit tests in `TestCrudQueueCompletion` class (`test_crud_queue_integration.py`)
- Full regression: 532/532 unit tests pass
- Curl Test 2: Card correctly transitions "running" → "done"

### Additional Fix
- Debug print truncation in `agent.py:131`: Removed `[:200]` preview — full XML response now visible in debug output

### Known Issue: TTS Focus Mode Stuck
- TTS blocked by pre-existing stuck `notifications_tts_queue` in localStorage (36 items)
- Not caused by CRUD changes — pre-existing issue
- Fix: `localStorage.removeItem('notifications_tts_queue'); location.reload();`
- TODO logged: Add 60s safety timeout to TTS focus mode

---

## E2E Testing Protocol Part 3 — Curl Smoke Tests (2026-02-09)

| Test | Status | Notes |
|------|--------|-------|
| Test 1: Health check | PENDING (manual) | User will run |
| Test 2: Submit todo | PARTIAL | Card transition verified (running→done). TTS blocked by stuck focus mode. Re-run after localStorage clear. |
| Test 3: Feature flag toggle | PENDING (manual) | User will run |
| Test 4: Destructive operation | PENDING (manual) | User will run |

---

## Phase 3 Detailed Progress

| Step | Component | Status |
|------|-----------|--------|
| 1 | Feature flag config + splainer | Done |
| 2 | Producer-side routing swap (todo_fifo_queue.py) | Done |
| 3 | Consumer-side cache skip + serialization exclusion (running_fifo_queue.py) | Done |
| 4 | Voice confirmation for destructive operations (agent.py) | Done |
| 5 | Unit tests (26 tests across 3 test classes) | Done |
| 6 | Documentation update (layer-3.md, implementation-tracker.md) | Done |
| 7 | Regression testing (full unit suite + WebSocket smoke) | Done |

## Phase 3 Test Coverage

| Test Class | Count | What It Tests |
|------------|-------|---------------|
| TestCrudQueueRouting | 8 | Feature flag true/false/default/whitespace, inheritance, constructor args |
| TestCrudCacheBehavior | 5 | isinstance checks for CRUD/Todo/Calendar agents, serialization exclusion pattern |
| TestCrudConfirmationFlow | 13 | needs_confirmation per operation, yes/no/timeout/error paths, cancelled formatting |

## Phase 3 Verification Results (2026-02-06)

- Phase 3 unit tests: 26/26 passed (1.83s)
- Phase 2 regression: 73/73 passed (2.03s)
- Phase 1 regression: 91/91 passed (0.55s)
- Full unit suite: 449/449 passed (9.59s, zero regressions)
- WebSocket smoke: 50/50 passed (25 core + 22 integration + 2 perf + 1 load)

## Phase 2 Detailed Progress

| Step | Component | Status |
|------|-----------|--------|
| 1 | dispatcher.py (dispatch, format_result_for_voice, extract_intent_xml) | Done |
| 2 | intent_extractor.py (Claude Code headless fallback) | Done |
| 3 | intent-extraction.txt (prompt template with {intent_example}, {available_lists}) | Done |
| 4 | agent.py (CrudForDataFramesAgent base class) | Done |
| 5 | todo_crud_agent.py + calendar_crud_agent.py (thin subclasses) | Done |
| 6 | __init__.py (Phase 2 exports) | Done |
| 7 | Unit tests (73 tests across 8 test classes) | Done |
| 8 | Phase 1 regression + full suite verification | Done |

## Phase 2 Verification Results (2026-02-06)

- Phase 2 unit tests: 73/73 passed (2.0s)
- Phase 1 regression: 91/91 passed (0.56s)
- Full unit suite: 423/423 passed (9.58s, zero regressions)

## Phase 2 Test Coverage

| Test Class | Count | What It Tests |
|------------|-------|---------------|
| TestExtractIntentXml | 9 | XML extraction from raw LLM responses (clean, fenced, preamble, errors) |
| TestDispatch | 14 | All 9 CRUD operations via dispatch(), error cases |
| TestFormatResultForVoice | 17 | TTS formatting for all result types and statuses |
| TestBuildClaudePrompt | 5 | Claude Code fallback prompt building |
| TestExtractIntentViaClaudeCode | 6 | Mocked subprocess: success, timeout, errors |
| TestCrudForDataFramesAgentMocked | 9 | Mocked agent: run_prompt, run_code, fallback, formatter |
| TestSubclasses | 4 | TodoCrudAgent/CalendarCrudAgent schema types + inheritance |
| TestCRUDIntentXmlParsing | 7 | from_xml() edge cases: minimal, empty, malformed |
| TestDispatchIntegration | 2 | Full CRUD lifecycle: add→query→delete, mark_done→verify |

## Phase 1 Detailed Progress

| Step | Component | Status |
|------|-----------|--------|
| 1 | Documentation directory | Done |
| 2 | schemas.py | Done |
| 3 | xml_models.py | Done |
| 4 | storage.py | Done |
| 5 | crud_operations.py | Done |
| 6 | __init__.py | Done |
| 7 | Config additions | Done |
| 8 | Prompt template stub | Done |
| 9 | Unit tests (91 tests) | Done |
| 10 | Smoke tests (16 tests) + verify | Done |

## Phase 1 Verification Results (2026-02-06)

- Import check: PASSED
- Unit tests: 91/91 passed (0.63s)
- Smoke tests: 16/16 passed
- Module smoke tests: schemas, xml_models both passed
- Full unit suite regression: 335/335 passed (no regressions)
- Config: 4 keys in lupin-app.ini, 4 in lupin-app-splainer.ini

## Key Issues Found & Fixed

### Phase 1
1. **Pydantic ClassVar**: `VALID_OPERATIONS` and `DESTRUCTIVE_OPERATIONS` needed `ClassVar` annotation
2. **XML None coercion**: xmltodict returns `None` for empty tags; added `field_validator` to coerce to `""`
3. **Timestamp precision**: `allow_truncated_timestamps=True` needed for ns→ms coercion in parquet write

### Phase 2
1. **Mock wiring**: LlmClientFactory mock needed to be patched at the module level (`cosa.crud_for_dataframes.agent.LlmClientFactory`) not in the helper

## Design References

- Architecture: `src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`
- Implementation plan: `src/rnd/2026.02.05-crud-for-dataframes-implementation.md`
- Layer docs: `src/rnd/headless-cc-for-dataframe-crud/layer-{1,2,3}.md`
- Testing protocol: `src/rnd/headless-cc-for-dataframe-crud/testing-protocol.md`
