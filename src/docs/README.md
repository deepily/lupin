# Lupin Documentation

## API Reference

- **Interactive**: [`/docs`](http://localhost:7999/docs) (Swagger UI) or [`/redoc`](http://localhost:7999/redoc) (ReDoc) — always current, auto-generated from router metadata
- **Quick Reference**: [rest-api-reference.md](rest-api-reference.md) — endpoint summary tables

## Architecture & Concepts

| Document | Topic | Source of Truth |
|----------|-------|-----------------|
| [websocket-architecture.md](websocket-architecture.md) | WebSocket system design, WebSocketManager API | `websocket_manager.py` |
| [websocket-events.md](websocket-events.md) | Event catalog with payload schemas | `lupin-app.ini`, `routers/websocket.py` |
| [websocket-configuration.md](websocket-configuration.md) | WebSocket config keys and tuning | `lupin-app.ini`, `lupin-app-splainer.ini` |
| [websocket-troubleshooting.md](websocket-troubleshooting.md) | WebSocket diagnostic procedures | — |
| [notification-api.md](notification-api.md) | Notification system architecture, lifecycle, proxy | `routers/notifications.py` |
| [notification-types.md](notification-types.md) | Catalogue of `type` values + custom state-update types (incl. `commons_broadcast_ack`) | `routers/notifications.py` `valid_types` |
| [proxy-admin-guide.md](proxy-admin-guide.md) | Trust Dashboard and ratification guide | `routers/decision_proxy.py` |
| [lupin-mpa-frontend-architecture.md](lupin-mpa-frontend-architecture.md) | Multi-page app frontend design | `src/lib/clients/` |
| [cost-model-bounded-cc-vs-firewalled-sdk.md](cost-model-bounded-cc-vs-firewalled-sdk.md) | LLM-cost decision framework: bounded ClaudeCodeJob (Max-covered) vs direct Anthropic SDK (firewalled, metered); migration playbook + off-peak scheduling rule | `CLAUDE.md` § "COST MODEL"; `src/rnd/v0.1.7/2026.05.12-bounded-cc-billing-empirical-confirmation.md` |

## Agentic Jobs & Recovery

Documentation for automated job recovery (BFE, TFE) and test-suite scheduling.
These three features share a common foundation in `src/cosa/agents/shared/`.

| Document | Topic | Source of Truth |
|----------|-------|-----------------|
| [agents/README.md](agents/README.md) | Subsystem index and "when to read which" decision table | — |
| [agents/bug-fix-expediter-guide.md](agents/bug-fix-expediter-guide.md) | Dead-job auto-recovery agent (BFE) — 6 phases, INI keys, trust-to-git mapping | `src/cosa/agents/bug_fix_expediter/` |
| [agents/test-fix-expediter-guide.md](agents/test-fix-expediter-guide.md) | Test-failure auto-recovery agent (TFE) — Phase 0 clustering, `TestSuiteCompletionWatchdog`, 16 INI keys | `src/cosa/agents/test_fix_expediter/` |
| [agents/test-suite-scheduling-guide.md](agents/test-suite-scheduling-guide.md) | `TestSuiteJob` + `/schedule-tests` skill — suite types, monopolize mode, remediation snapshot schema v1.0 | `src/cosa/agents/test_suite/` |
| [agents/shared-fix-primitives-reference.md](agents/shared-fix-primitives-reference.md) | `PlanWriter`, `GitStrategist`, `FixExecutor`, `FIX_PROMPT_BUILDERS` — how to add a new expediter agent | `src/cosa/agents/shared/` |

## Operations & Configuration

| Document | Topic |
|----------|-------|
| [deployment-runtime-config-examples.md](deployment-runtime-config-examples.md) | Runtime config patterns and examples |
| [database-migrations.md](database-migrations.md) | Database migration procedures |
| [automated-interactive-testing.md](automated-interactive-testing.md) | Proxy auto-answer testing guide |

## Auth Subsystem

Deep-dive documentation for the JWT authentication system (relocated from `docs/auth/`):

| Document | Topic |
|----------|-------|
| [auth/api-reference.md](auth/api-reference.md) | Detailed auth endpoint specs |
| [auth/architecture-overview.md](auth/architecture-overview.md) | Auth service components, DB schema, sequence diagrams |
| [auth/security-guide.md](auth/security-guide.md) | Production hardening, TLS, key rotation, compliance |
| [auth/operations-guide.md](auth/operations-guide.md) | Deployment, backups, disaster recovery |
| [auth/integration-guide.md](auth/integration-guide.md) | Frontend auth integration patterns |
| [auth/migration-guide.md](auth/migration-guide.md) | Mock-to-JWT migration (historical) |
| [auth/troubleshooting.md](auth/troubleshooting.md) | Auth-specific debugging procedures |

## Last Verified

| Document | Verified Against | Date |
|----------|-----------------|------|
| websocket-architecture.md | `websocket_manager.py` (24 methods) | 2026-03-20 |
| websocket-events.md | `lupin-app.ini` (18 events) | 2026-03-20 |
| websocket-configuration.md | `lupin-app.ini` (7 keys) | 2026-03-20 |
| websocket-troubleshooting.md | Current auth flow + events | 2026-03-20 |
| rest-api-reference.md | All 19 routers + BFE/TFE/test-suite | 2026-04-10 |
| notification-api.md | `routers/notifications.py` | 2026-03-20 |
| agents/README.md | BFE/TFE/TestSuite/shared subsystem index | 2026-04-10 |
| agents/bug-fix-expediter-guide.md | `src/cosa/agents/bug_fix_expediter/` (Phase 6 complete, 58 tests) | 2026-04-10 |
| agents/test-fix-expediter-guide.md | `src/cosa/agents/test_fix_expediter/` (197 tests) | 2026-04-10 |
| agents/test-suite-scheduling-guide.md | `src/cosa/agents/test_suite/job.py` + `/schedule-tests` skill | 2026-04-10 |
| agents/shared-fix-primitives-reference.md | `src/cosa/agents/shared/` (3 modules, extracted Session 1cfcdf73) | 2026-04-10 |
