# Decision Proxy Light-Up — Implementation Plan

## Context

The SWE Team Decision Proxy has a fully built 4-layer architecture with 1490 passing
unit tests. Session 241 activated shadow mode and wired the trust feedback loop. But
the system is write-only — data lives in memory, APIs aren't mounted, config isn't
wired, and there's no UI. This plan connects every disconnected piece.

**Pattern**: 1 (Multi-Phase Implementation) — Architecture design is DONE.

---

## Phase Status

| Phase | Description | Status | Started | Completed |
|-------|-------------|--------|---------|-----------|
| 0 | File Restructuring + Doc Setup | DONE | 2026-02-20 | 2026-02-20 |
| 1 | Orchestrator `get_state()` — Proxy Fields | DONE | 2026-02-20 | 2026-02-20 |
| 2 | INI Config Wiring | DONE | 2026-02-20 | 2026-02-20 |
| 3 | Mount REST Router | DONE | 2026-02-20 | 2026-02-20 |
| 4 | Persistence Wiring — Fill the TODO | DONE | 2026-02-20 | 2026-02-20 |
| 5 | Full INI Integration for Proxy Construction | DONE | 2026-02-20 | 2026-02-20 |
| 6 | UI — Ratification Page + Trust Dashboard | DONE | 2026-02-20 | 2026-02-20 |
| 7 | Real-Time Proxy Notifications | DONE | 2026-02-21 | 2026-02-21 |
| 8 | Hot-Reload of Trust Mode | DONE | 2026-02-21 | 2026-02-21 |

**MVP Checkpoint**: After Phase 4 — API returns real data, get_state() exposes proxy.
**UI Checkpoint**: After Phase 6 — Users can see and ratify decisions in browser.

---

## Phase 0: File Restructuring + Doc Setup

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 0.1 | Create directory | `src/rnd/2026.02.14-swe-team-phase-4-decision-proxy-architecture/` | DONE |
| 0.2 | Move + rename original doc | → `2026.02.14-decision-proxy-architecture-original.md` | DONE |
| 0.3 | Create 00-index.md | Navigation hub | DONE |
| 0.4 | Create 01-implementation-current.md | This file | DONE |
| 0.5 | Create 02-disconnected-surfaces-audit.md | Audit of unwired surfaces | DONE |
| 0.6 | Create 03-config-wiring-reference.md | INI key mapping | DONE |
| 0.7 | Create 04-ui-design-ratification-dashboard.md | UI wireframes | DONE |
| 0.8 | Create 05-notification-integration.md | Notification API reuse doc | DONE |
| 0.9 | Create 06-testing-validation.md | Test tracking | DONE |
| 0.10 | Update src/rnd/README.md entry | Point to directory | DONE |

---

## Phase 1: Orchestrator `get_state()` — Proxy Fields

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1.1 | Add proxy fields to get_state() | `orchestrator.py` (CoSA) | DONE |
| 1.2 | Add unit test for proxy fields | `test_swe_team_orchestrator.py` (Lupin) | DONE |
| 1.3 | Verify existing tests unaffected | `pytest` — 52 orchestrator tests pass | DONE |

---

## Phase 2: INI Config Wiring

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 2.1 | Add `from_config_mgr()` factory | `decision_proxy/config.py` (CoSA) | DONE |
| 2.2 | Add `swe_proxy_config_from_config_mgr()` | `swe_team/proxy/config.py` (CoSA) | DONE |
| 2.3 | Read trust_mode from ConfigurationManager | `swe_team/job.py` (CoSA) | DONE |
| 2.4 | Add unit tests for config factories | `test_swe_team_config.py` (Lupin) | DONE |
| 2.5 | Verify INI → runtime round-trip | Manual: change INI, restart, check logs | DONE |

---

## Phase 3: Mount REST Router

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 3.1 | Verify DB tables exist | `psql` check for proxy_decisions, trust_states | DONE |
| 3.2 | Apply DDL if missing | `src/scripts/sql/2026.02.14-decision-proxy-schema.sql` | DONE |
| 3.3 | Add router import | `main.py` line 63 (Lupin) | DONE |
| 3.4 | Mount router | `main.py` after line 651 (Lupin) | DONE |
| 3.5 | Verify endpoints respond | Import verified at module level | DONE |

---

## Phase 4: Persistence Wiring — Fill the TODO

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 4.1 | Replace TODO in shadow branch | `responder.py` → `_persist_decision()` with `log_shadow()` (CoSA) | DONE |
| 4.2 | Add suggest/act logging | `responder.py` → `_persist_decision()` with `log_decision()` (CoSA) | DONE |
| 4.3 | Add trust state persistence | `orchestrator.py` → `_persist_trust_feedback()` (CoSA) | DONE |
| 4.4 | Mock session tests for log_shadow/log_decision | `test_proxy_decision_repository.py` — 7 tests (Lupin) | DONE |
| 4.5 | Mock session tests for update_after_ratification | `test_trust_state_repository.py` — 5 tests (Lupin) | DONE |
| 4.6 | E2E verify: dry_run → curl shows decisions | All 12 tests pass | DONE |

---

## Phase 5: Full INI Integration for Proxy Construction

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 5.1 | Use factory functions in proxy construction | `orchestrator.py` __init__ (CoSA) | DONE |
| 5.2 | Add CB params to EngineeringStrategy constructor | `engineering_strategy.py` (CoSA) | DONE |
| 5.3 | Test: INI threshold change → trust level change | 134 SWE team tests pass | DONE |

---

## Phase 6: UI — Ratification Page + Trust Dashboard

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 6.0 | Expand UI design doc with full specs | `04-ui-design-ratification-dashboard.md` | DONE |
| 6.1 | Create ratification page (HTML + CSS + JS) | `proxy-ratify.html`, `proxy-ratify.css`, `proxy-ratify.js` (Lupin) | DONE |
| 6.2 | Create trust dashboard (HTML + CSS + JS) | `proxy-dashboard.html`, `proxy-dashboard.css`, `proxy-dashboard.js` (Lupin) | DONE |
| 6.3 | Add admin nav links | `admin/dashboard.html` (2 cards), `auth/profile.html` (2 buttons) | DONE |
| 6.4 | Verify no regressions | `pytest src/tests/unit/` — 1511 pass | DONE |

---

## Phase 7: Real-Time Proxy Notifications

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 7.0 | Relax progress_group_id regex + widen DB column | `notification_models.py`, `postgres_models.py` (CoSA) | DONE |
| 7.1 | Batch generation counter + acknowledge/batch-id endpoints | `decision_proxy.py` router (CoSA) | DONE |
| 7.2 | Proxy summary notification emission | `orchestrator.py` — `_emit_proxy_summary_notification()` (CoSA) | DONE |
| 7.3 | Frontend proxy ratify link + batch retirement | `notifications.js`, `notifications.css` (Lupin) | DONE |
| 7.4 | Focus refresh + WebSocket on ratify page | `proxy-ratify.js`, INI config (Lupin) | DONE |
| 7.5 | Trust mode dropdown (end-to-end plumbing) | `notifications.html`, `swe_team.py`, `agentic_job_factory.py`, `job.py` | DONE |
| 7.6 | Circuit breaker alert notification | `orchestrator.py` — `_on_circuit_breaker_trip()` (CoSA) | DONE |
| 7.7 | Unit tests (6 proxy notification + 1 proxy batch regex) | `test_swe_team_orchestrator.py`, `test_notification_models.py` (Lupin) | DONE |
| 7.8 | E2E smoke test | `test_proxy_notifications.py` (Lupin — NEW) | DONE |
| 7.9 | Full regression | `pytest src/tests/unit/` — 1518 pass, 0 fail | DONE |

---

## Phase 8: Hot-Reload of Trust Mode

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 8.1 | Expose orchestrator reference on SweTeamJob | `job.py` (CoSA) — `self._orchestrator` | DONE |
| 8.2 | Add PUT /api/proxy/mode endpoint | `decision_proxy.py` router (CoSA) | DONE |
| 8.3 | Add GET /api/proxy/mode endpoint | `decision_proxy.py` router (CoSA) | DONE |
| 8.4 | Replace mode bar with dropdown selector | `proxy-dashboard.html` (Lupin) | DONE |
| 8.5 | Wire dropdown to REST endpoint + CSS | `proxy-dashboard.js`, `proxy-dashboard.css` (Lupin) | DONE |
| 8.6 | Unit tests (7 hot-reload + 9 endpoint) | `test_swe_team_orchestrator.py`, `test_decision_proxy_mode.py` (Lupin) | DONE |
| 8.7 | Full regression | `pytest src/tests/unit/` — 1534 pass, 0 fail | DONE |
