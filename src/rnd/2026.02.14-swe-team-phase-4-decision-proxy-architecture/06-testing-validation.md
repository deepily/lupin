# Decision Proxy Light-Up — Testing & Validation

## Baseline (Post Phase 5)

| Metric | Pre-Implementation | Post Phase 5 | Post Phase 7 | Post Phase 8 | Date |
|--------|-------------------|--------------|--------------|--------------|------|
| Total unit tests | 1490 | 1511 | 1518 | 1534 | 2026-02-21 |
| SWE team tests | 111 | 134 | 140 | 147 | 2026-02-21 |
| Orchestrator tests | 49 | 52 | 58 | 65 | 2026-02-21 |
| Trust feedback tests | 7 | 7 | 7 | 7 | 2026-02-20 |
| Proxy decision repo tests | 0 | 7 | 7 | 7 | 2026-02-20 |
| Trust state repo tests | 0 | 5 | 5 | 5 | 2026-02-20 |
| Config factory tests | 0 | 6 | 6 | 6 | 2026-02-20 |
| Notification model tests | — | — | 1 | 1 | 2026-02-21 |
| Mode endpoint tests | — | — | — | 9 | 2026-02-21 |

## Per-Phase Test Additions

| Phase | New Tests | Target Files | Status |
|-------|-----------|--------------|--------|
| 1 | +3 | `test_swe_team_orchestrator.py` | DONE |
| 2 | +6 | `test_swe_team_config.py` | DONE |
| 3 | 0 | 2-line router mount, import verified | DONE |
| 4 | +12 | `test_proxy_decision_repository.py` (7), `test_trust_state_repository.py` (5) | DONE |
| 5 | 0 | INI wiring, existing tests cover behavior | DONE |
| 6 | +44 offline, +15 live | `test_proxy_ui_offline_smoke.py` (44), `test_proxy_ui_content.py` (15) | DONE |
| 7 | +7 | `test_swe_team_orchestrator.py` (6), `test_notification_models.py` (1) | DONE |
| 8 | +16 | `test_swe_team_orchestrator.py` (7), `test_decision_proxy_mode.py` (9) | DONE |

**Total new backend tests (Phases 1-8)**: +44
**Total new UI tests (Phase 6 backfill)**: +59 (44 offline + 15 live)
**Final total**: 1534 unit + 59 UI = 1593

## UI Test Coverage (Phase 6 Backfill — Session 251)

| Tier | File | Tests | Server? |
|------|------|-------|---------|
| A: HTML Structure | `src/tests/smoke/test_proxy_ui_offline_smoke.py` | 24 | No |
| B: JS Analysis | `src/tests/smoke/test_proxy_ui_offline_smoke.py` | 13 | No |
| C: CSS Verification | `src/tests/smoke/test_proxy_ui_offline_smoke.py` | 7 | No |
| D: Live Content | `src/tests/integration/test_proxy_ui_content.py` | 15 | Yes (7999) |
| **Total** | | **59** | |

## Regression Results Log

| Date | Phase | Tests Run | Passed | Failed | Notes |
|------|-------|-----------|--------|--------|-------|
| 2026-02-20 | Baseline | 1490 | 1490 | 0 | Session 241 shadow activation |
| 2026-02-20 | Phase 1 | 1493 | 1493 | 0 | +3 get_state() proxy field tests |
| 2026-02-20 | Phase 2 | 1499 | 1499 | 0 | +6 config factory tests |
| 2026-02-20 | Phase 4 | 1511 | 1511 | 0 | +12 repository tests (7 decision + 5 trust) |
| 2026-02-20 | Phase 5 | 1511 | 1511 | 0 | Full regression after INI integration |
| 2026-02-20 | Phase 6 | 1511 | 1511 | 0 | UI files only — no Python changes |
| 2026-02-21 | Phase 7 | 1518 | 1518 | 0 | +7 tests (6 proxy notification + 1 regex), +1 E2E smoke |
| 2026-02-21 | Phase 8 | 1534 | 1534 | 0 | +16 tests (7 hot-reload + 9 mode endpoint) |
| 2026-02-23 | Phase 6 UI | 44 | 44 | 0 | +44 offline UI smoke tests (HTML/JS/CSS), +15 live tests (server not running) |
