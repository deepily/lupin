# Testing & Validation — SWE Team Agent

## Test Inventory

| Test File | Phase | Tests | Status |
|-----------|-------|-------|--------|
| `test_swe_team_config.py` | 1 | 64 tests: config, safety, state, definitions, sender IDs, mock, orchestrator, COSA interface | PASS |
| `test_swe_team_delegation.py` | 2 | 34 tests: hooks, state files, decomposition, delegation, live flow | PASS |
| `test_swe_team_verification.py` | 3 | 31 tests: verification result, test runner, parse output, verify result, redelegate, coder-tester loop, build agent options | PASS |
| `test_trust_tracker.py` | 4c | 28 tests: L3-L5 graduation, intermediate demotion, rolling window, decay precision, serialization, tracker deep edge cases | PASS |
| `test_circuit_breaker.py` | 4c | 27 tests: min-sample gate, confidence boundary, trip demotion, multi-category, reset, callback, cooldown, confidence window | PASS |
| `test_engineering_decisions.py` | 4e | 32 tests: keyword content, cap constants, sender hints, confidence formula, evaluate with trust, custom construction | PASS |
| `test_decision_proxy_config.py` | 4b+4c | 70 tests: config, smart router, strategy, classifier, XML, listener, responder, CategoryTrust, TrustTracker, CircuitBreaker | PASS |
| `test_swe_engineering_proxy.py` | 4e | 47 tests: categories, classifier, strategy, config, exports | PASS |
| `test_swe_team_job.py` | 5 | Job creation, mock do_all() | PENDING |

## Smoke Test Results (Phase 1)

| Module | Tests | Status |
|--------|-------|--------|
| `config.py` | 4 | PASS |
| `safety_limits.py` | 7 | PASS |
| `state.py` | 6 | PASS |
| `agent_definitions.py` | 7 | PASS |
| `cosa_interface.py` | 6 | PASS |
| `voice_io.py` | 6 | PASS |
| `mock_clients.py` | 5 | PASS |
| `orchestrator.py` | 5 | PASS |

## Smoke Test Results (Phase 2)

| Module | Tests | Status |
|--------|-------|--------|
| `hooks.py` | 6 | PASS |
| `state_files.py` | 4 | PASS |

## Smoke Test Results (Phase 3)

| Module | Tests | Status |
|--------|-------|--------|
| `test_runner.py` | 4 | PASS |
| `state.py` (updated) | 8 | PASS |
| `agent_definitions.py` (updated) | 7 | PASS |

## Regression Tracking

| Phase | Pre-Phase Unit Tests | Post-Phase Unit Tests | Regressions | Date |
|-------|---------------------|----------------------|-------------|------|
| 1 | 817 | 881 (+64 new) | 0 | 2026-02-13 |
| 2 | 881 | 915 (+34 new) | 0 | 2026-02-14 |
| 3 | 915 | 946 (+31 new) | 0 | 2026-02-14 |
| 4 | 1178 | 1265 (+87 new) | 0 | 2026-02-16 |
| 5 | — | — | — | — |

## 5-Surface Validation

| Surface | Description | Status |
|---------|-------------|--------|
| 1 | Unit Tests + Inline Smoke Tests | PASS (Phase 1) |
| 2 | Mock Job Endpoint | PENDING |
| 3 | Notification UI Submission Cards | PENDING |
| 4 | LORA Training Data Generation | PENDING |
| 5 | Voice Routing (ASR -> LORA -> Queue) | PENDING |

## Per-Phase Gate Results

### Phase 1 Gate
- [x] `python -m cosa.agents.swe_team "test" --dry-run` -> notifications fire, no errors
- [x] All existing unit tests pass (`pytest src/tests/unit/ -v`) — 881/881 pass

### Phase 2 Gate
- [x] Simple task E2E with mocked SDK -> coder produces DelegationResult, lead verifies
- [x] `pytest src/tests/unit/test_swe_team_delegation.py -v` — 34/34 pass
- [x] `pytest src/tests/unit/ -v` — full regression 915/915 pass, 0 regressions
- [x] Hooks correctly gate dangerous commands in mock test
- [x] State files round-trip correctly with tempdir isolation

### Phase 3 Gate
- [x] Task requiring tests -> coder+tester loop terminates correctly (6 loop tests)
- [x] `pytest src/tests/unit/test_swe_team_verification.py -v` — 31/31 pass
- [x] `pytest src/tests/unit/ -v` — full regression 946/946 pass, 0 regressions
- [x] `_verify_result()` sets TESTING state, sends notifications, tracks test files
- [x] `_redelegate_with_feedback()` includes prior output + tester feedback + iteration number
- [x] Loop caps at MAX_VERIFICATION_ITERATIONS=3, guard.record_failure() called
- [x] `require_test_pass=False` skips verification (backward compat)
- [x] `_build_agent_options("tester")` returns worker model + TESTER_SYSTEM_PROMPT + acceptEdits

### Phase 4 Gate
- [x] `pytest src/tests/unit/test_trust_tracker.py -v` — 28/28 pass
- [x] `pytest src/tests/unit/test_circuit_breaker.py -v` — 27/27 pass
- [x] `pytest src/tests/unit/test_engineering_decisions.py -v` — 32/32 pass
- [x] `pytest src/tests/unit/ -v` — full regression 1265/1265 pass, 0 regressions
- [ ] Proxy in L1 shadow mode -> predictions logged, no autonomous action
- [ ] Morning ratification endpoint functional

### Phase 5 Gate
- [ ] `POST /api/swe-team/submit` -> job queued -> runs -> done
- [ ] Voice routing: "start an swe team task" -> correct classification
- [ ] All 5 testing surfaces pass
- [ ] WebSocket smoke tests pass
