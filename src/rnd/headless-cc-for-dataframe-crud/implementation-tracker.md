# DataFrame CRUD Implementation Tracker

**Last Updated**: 2026-02-06

## Cross-Phase Progress

| Phase | Layer | Status | Key Milestone |
|-------|-------|--------|---------------|
| 1 | Layer 1: Storage | COMPLETE | 91 unit tests, 16 smoke tests, all passing |
| 2 | Layer 2: Intent | COMPLETE | 73 unit tests, 5 new source files + 1 modified + 1 test file |
| 3 | Layer 3: Dispatch | NOT STARTED | Queue routing swap + cache + voice I/O |
| 4 | Layer 3: Polish | NOT STARTED | End-to-end voice workflows |

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
