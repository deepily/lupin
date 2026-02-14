# Testing & Validation — SWE Team Agent

## Test Inventory

| Test File | Phase | Tests | Status |
|-----------|-------|-------|--------|
| `test_swe_team_config.py` | 1 | 64 tests: config, safety, state, definitions, sender IDs, mock, orchestrator, COSA interface | PASS |
| `test_swe_team_delegation.py` | 2 | Decomposition, mock SDK delegation | PENDING |
| `test_swe_team_verification.py` | 3 | Loop termination, failure escalation | PENDING |
| `test_trust_tracker.py` | 4 | Graduation, rollback, per-category isolation | PENDING |
| `test_circuit_breaker.py` | 4 | Demotion triggers | PENDING |
| `test_engineering_decisions.py` | 4 | Classification, trust gating, shadow mode | PENDING |
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

## Regression Tracking

| Phase | Pre-Phase Unit Tests | Post-Phase Unit Tests | Regressions | Date |
|-------|---------------------|----------------------|-------------|------|
| 1 | 817 | 881 (+64 new) | 0 | 2026-02-13 |
| 2 | — | — | — | — |
| 3 | — | — | — | — |
| 4 | — | — | — | — |
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
- [ ] Simple task E2E -> coder produces code, lead verifies
- [ ] All existing unit tests pass

### Phase 3 Gate
- [ ] Task requiring tests -> coder+tester loop terminates correctly
- [ ] All existing unit tests pass

### Phase 4 Gate
- [ ] Proxy in L1 shadow mode -> predictions logged, no autonomous action
- [ ] Morning ratification endpoint functional
- [ ] All existing unit tests pass

### Phase 5 Gate
- [ ] `POST /api/swe-team/submit` -> job queued -> runs -> done
- [ ] Voice routing: "start an swe team task" -> correct classification
- [ ] All 5 testing surfaces pass
- [ ] WebSocket smoke tests pass
