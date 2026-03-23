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
| [proxy-admin-guide.md](proxy-admin-guide.md) | Trust Dashboard and ratification guide | `routers/decision_proxy.py` |
| [lupin-mpa-frontend-architecture.md](lupin-mpa-frontend-architecture.md) | Multi-page app frontend design | `src/lib/clients/` |

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
| rest-api-reference.md | All 19 routers | 2026-03-20 |
| notification-api.md | `routers/notifications.py` | 2026-03-20 |
