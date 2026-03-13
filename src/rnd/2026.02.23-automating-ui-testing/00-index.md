# Playwright E2E Testing — Planning Documents

**Created**: 2026-02-23
**Status**: Planning Complete — Implementation deferred to v0.1.6
**Pattern**: Pattern 1 (Multi-Phase Implementation) — 8 phases, ~5 weeks

---

## Document Index

| # | Document | Purpose |
|---|----------|---------|
| 00 | **This file** (`00-index.md`) | Navigation hub |
| 01 | [Implementation Plan](01-implementation-plan.md) | 8-phase tracking with ~78 tasks, dependencies, risks |
| 02 | [Architecture Decisions](02-architecture-decisions.md) | 9 ADRs: infrastructure, conventions, test patterns |
| 03 | [data-testid Inventory](03-data-testid-inventory.md) | 180+ elements across 12 pages + nav component |
| 04 | [Test Journey Specs](04-test-journey-specs.md) | Detailed specs for all E2E test journeys |
| — | [Research Foundation](2026.02.23-automating-ui-testing-research.md) | Tool evaluation, community consensus, recommendations |

---

## Context

Lupin has a robust 5-tier testing strategy (1534+ unit, 50 smoke, 85+ integration, 50 WebSocket, 12 interactive proxy tests) but **zero browser-based E2E testing**. Research completed on 2026-02-23 recommends **Playwright Python + pytest-playwright** as the clear choice for the FastAPI + vanilla HTML/JS stack.

### Why Playwright?

- **Python-native** — pytest-playwright integrates directly with existing pytest infrastructure
- **Auto-wait** — No manual sleep/retry needed for dynamic content
- **data-testid support** — First-class `page.get_by_test_id()` locators
- **Trace viewer** — Built-in debugging for failed tests
- **Chromium-only** — Sufficient for Lupin's internal-use UI

### What This Adds to the Test Pyramid

```
┌─────────────────────────────────┐
│     Visual Regression (Tier 6)  │  ← Phase 8
├─────────────────────────────────┤
│     E2E Browser Tests (Tier 5)  │  ← Phases 3-7 (NEW)
├─────────────────────────────────┤
│     Interactive Proxy (Tier 4)  │  12 scenarios
├─────────────────────────────────┤
│     WebSocket Smoke (Tier 3)    │  50 tests
├─────────────────────────────────┤
│     Integration Tests (Tier 2)  │  85+ tests
├─────────────────────────────────┤
│     Unit + Smoke Tests (Tier 1) │  1534+ tests
└─────────────────────────────────┘
```

### Round 2: AI Augmentation (Post v0.1.6)

After the traditional Playwright foundation is stable, Round 2 layers Claude Code + Playwright MCP for intelligent test generation, self-healing selectors, and visual regression triage. See [Implementation Plan](01-implementation-plan.md) § Round 2.

---

## Quick Start (at v0.1.6)

```bash
# 1. Install dependencies
pip install pytest-playwright pytest-playwright-visual-snapshot
playwright install chromium --with-deps

# 2. Run E2E tests
./src/scripts/run-e2e-tests.sh

# 3. Run specific phase
pytest src/tests/e2e/test_login.py -v
```

---

## Serialized Plan

The full plan file is also available at:
[`src/rnd/2026.02.23-playwright-e2e-testing-plan.md`](../2026.02.23-playwright-e2e-testing-plan.md)
