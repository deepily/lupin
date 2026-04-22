---
name: testing-patterns
description: Testing patterns for Lupin project. Use when writing tests, running pytest, debugging test failures, choosing between smoke/unit/integration tests, checking test coverage, or fixing failing tests.
metadata:
  author: lupin-team
  version: "1.2"
  last-updated: "2026-03-14"
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
| Live Pipeline | `src/tests/smoke/test_*_live_pipeline.py` | 10-120s | Full LLM pipeline | `python src/tests/smoke/test_calculator_live_pipeline.py` |
| UI E2E | `src/tests/e2e_ui/` | 1-5s | Browser-level visual + functional | `./src/scripts/run-e2e-ui-tests.sh --bg -v` |
| Container Preflight | `src/tests/smoke/test_container_preflight.py` | <5s | Catch docker-compose.yml mount drift before TFE/BFE Resume or live E2E | `src/scripts/preflight-test-container.sh` or `pytest src/tests/smoke/test_container_preflight.py -v` |

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

## Live Pipeline Tests (Server Required)

A fifth tier for **end-to-end live LLM validation** — submits real queries through the full pipeline and validates responses.

| Property | Value |
|----------|-------|
| Location | `src/tests/smoke/` (named `test_*_live_pipeline.py`) |
| Speed | 10-120s per query (LLM inference) |
| Requires | Running server + LLM backend |
| Credentials | `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL` / `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD` |

```bash
# Calculator 6-query live pipeline test
python src/tests/smoke/test_calculator_live_pipeline.py

# Run specific queries only
python src/tests/smoke/test_calculator_live_pipeline.py -q 0,2,4
```

**Why this exists**: Manual curl-based job submission is labor-intensive and error-prone. Automated pipeline tests are repeatable, self-validating, and produce summary tables. Always prefer automated scripts over manual curl for pipeline validation.

## Interactive Pipeline Tests (Proxy-Driven)

For agents with interactive questions (expediter prompts, CRUD confirmations), use `InteractiveSmokeTest` — extends `LivePipelineTestBase` with auto-launched notification proxy.

| Property | Value |
|----------|-------|
| Base class | `InteractiveSmokeTest` (from `src/tests/smoke/utilities/interactive_smoke_test.py`) |
| Proxy | Auto-launched with `--auto-proxy` flag |
| Q&A scripts | `src/conf/notification-proxy-scripts/{agent-name}.json` |
| Template | `src/conf/notification-proxy-scripts/_template.json` |
| Reference | `src/tests/smoke/test_proxy_integration.py` (12 scenarios, 3 agent groups) |
| Guide | `src/docs/automated-interactive-testing.md` |

```bash
# Run interactive test with proxy auto-launch
python src/tests/smoke/test_proxy_integration.py --group calculator --auto-proxy --no-confirm

# Run all groups
python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm
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
| Testing full agent pipeline with real LLM | Live pipeline test |
| Testing UI visual regression | E2E visual test |
| Testing browser-level UI flows | E2E UI test |

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
| E2E UI | 265 tests | 253 functional + 12 visual regression |
| Unit | 2,102 tests | Comprehensive module coverage |
| Integration | 137 tests | End-to-end flows |
| Total | ~2,554 tests | unit + smoke + integration + WS + E2E UI |

## Documentation

- **Full Guide**: `src/tests/README.md`
- **Integration**: `src/tests/integration/README.md`
- **Unit Tests**: Inline documentation in test files

## E2E UI Tests (Playwright)

Browser-level functional + visual regression tests using Playwright + Chromium headless.

| Property | Value |
|----------|-------|
| Location | `src/tests/e2e_ui/` |
| Runner | `./src/scripts/run-e2e-ui-tests.sh --bg -v` |
| Tests | 297 (285 functional + 12 visual regression) |
| Duration | ~17 minutes (full suite) |
| Baselines | `src/tests/e2e_ui/__snapshots__/` (12 PNG screenshots) |
| Failures | `src/tests/e2e_ui/snapshot_failures/` (auto-generated on diff) |

**CRITICAL: Always use `--bg` flag from Claude Code.** The full suite takes ~17 minutes,
which exceeds the Bash tool's 10-minute max timeout. Without `--bg`, the timeout kills
the run mid-suite and the trap handler restores production config, causing hot-swap
collisions if re-run (Session 372c: 23 spurious errors). The `--bg` flag runs via nohup
with PID-file overlap protection.

```bash
# All E2E UI tests (ALWAYS use --bg from Claude Code)
./src/scripts/run-e2e-ui-tests.sh --bg -v

# Monitor progress
tail -20 /tmp/e2e-ui-latest.log

# Check if still running
kill -0 $(cat /tmp/e2e-ui-tests.pid) 2>/dev/null && echo running || echo done

# Check final results
grep -E '(passed|failed|error)' /tmp/e2e-ui-latest.log

# Visual regression only (~37s, --bg optional)
./src/scripts/run-e2e-ui-tests.sh --bg -v -k visual

# Update baselines after intentional UI changes
./src/scripts/run-e2e-ui-tests.sh --bg --update-snapshots -k visual

# From user terminal (foreground OK — no timeout concern)
./src/scripts/run-e2e-ui-tests.sh -v
```

**Coverage**: All 12 pages — auth flows, page smoke, admin flows, notifications, WebSocket lifecycle, visual regression.

## Anti-Patterns

- **NEVER** use `curl` for pipeline or integration testing — use automated test scripts
- **NEVER** manually POST to `/api/push` + poll `/api/get-queue/done` — use `LivePipelineTestBase`
- **Don't** run integration tests without the wrapper script
- **Don't** test external APIs in unit tests (use mocks)
- **Don't** skip smoke tests - they catch major breakage fast
- **Don't** mix WebSocket tests with regular pytest runs
