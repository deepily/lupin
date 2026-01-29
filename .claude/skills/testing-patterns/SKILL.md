---
name: testing-patterns
description: Testing patterns for Lupin project. Use when writing tests, running pytest, debugging test failures, choosing between smoke/unit/integration tests, checking test coverage, or fixing failing tests.
metadata:
  author: lupin-team
  version: "1.0"
  last-updated: "2026-01-28"
---

# Testing Patterns

Lupin uses a **three-tier testing strategy** for comprehensive validation.

## Test Tiers Overview

| Tier | Location | Speed | Purpose | Run Command |
|------|----------|-------|---------|-------------|
| Unit | `src/tests/unit/` | 1-10ms | Isolated functions | `pytest src/tests/unit/` |
| Smoke | inline `quick_smoke_test()` | 10-100ms | Module sanity | `python -m cosa.rest.jwt_service` |
| Integration | `src/tests/integration/` | 100-1000ms | End-to-end flows | `./src/tests/run-integration-tests.sh -v` |
| WebSocket | `src/tests/websocket_smoke/` | varies | WS functionality | `src/scripts/run-websocket-smoke-tests.sh` |

## Quick Commands

```bash
# Integration tests (RECOMMENDED - handles server automatically)
./src/tests/run-integration-tests.sh -v              # All integration
./src/tests/run-integration-tests.sh -v -s           # Very verbose
./src/tests/run-integration-tests.sh test_auth*.py   # Specific pattern

# Unit tests
pytest src/tests/unit/                               # All unit tests
pytest -v src/tests/unit/                            # Verbose

# All pytest tests (requires manual server setup)
pytest src/tests/

# With coverage
pytest --cov=cosa.rest --cov-report=html src/tests/

# WebSocket tests
src/scripts/run-websocket-smoke-tests.sh
```

## Which Test Type to Use?

| Scenario | Use |
|----------|-----|
| Testing a single function | Unit test |
| Checking module loads | Smoke test |
| Testing API endpoint flow | Integration test |
| Testing WebSocket events | WebSocket test |
| Testing with database | Integration test |
| Testing auth flow | Integration test |

## Critical Rules

1. **Integration tests require running server** - Use the script, it handles this
2. **Unit tests mock dependencies** - Don't hit real database/APIs
3. **Smoke tests are quick sanity checks** - Not comprehensive
4. **WebSocket tests have separate runner** - Don't mix with pytest

## Test Coverage

| Area | Coverage | Tests |
|------|----------|-------|
| Auth System | 85-90% | 14+ unit, 43 integration |
| WebSocket | 92% pass | 50 tests |
| Total | ~122 tests | unit + smoke + integration + WS |

## Documentation

- **Full Guide**: `src/tests/README.md`
- **Integration**: `src/tests/integration/README.md`
- **Unit Tests**: Inline documentation in test files

## Anti-Patterns

- **Don't** run integration tests without the wrapper script
- **Don't** test external APIs in unit tests (use mocks)
- **Don't** skip smoke tests - they catch major breakage fast
- **Don't** mix WebSocket tests with regular pytest runs
