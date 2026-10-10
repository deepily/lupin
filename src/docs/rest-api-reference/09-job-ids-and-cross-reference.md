> Part 9 of 9 of the [Lupin REST API Quick Reference](../rest-api-reference.md): job id prefixes and cross-reference.

## Job ID Prefixes

| Prefix | Job Type | Submit Endpoint |
|--------|----------|-----------------|
| `dr-` | Deep Research | `/api/v2/submit` with `"agent router go to deep research"` (`/api/deep-research/submit` is now 410) |
| `pg-` | Podcast Generator | `/api/v2/ask` with `"agent router go to podcast generator"` (`/api/podcast-generator/submit` is now 410) |
| `rp-` | Research-to-Podcast | `/api/v2/submit` with `"agent router go to research to podcast"` (`/api/deep-research-to-podcast/submit` is now 410) |
| `cc-` | Claude Code | `/api/v2/submit` with `"agent router go to claude code"` (both `/api/claude-code/*` doors are now 410) |
| `swe-` | SWE Team | `/api/v2/submit` with `"agent router go to swe team"` (`/api/swe-team/submit` is now 410) |
| `ts-` | Test Suite | `/api/v2/submit` with `"agent router go to test suite"` (`/api/test-suite/submit` is now 410) |
| `bfe-` | Bug Fix Expediter | `/api/v2/ask` with `"agent router go to bug fix expediter"` (`/api/push` is now 410) |
| `tfe-` | Test Fix Expediter | `/api/v2/ask` with `"agent router go to test fix expediter"` (`/api/push` is now 410) |
| `mock-` | Mock Job | `/api/v2/submit` with `"agent router go to mock job"` (`/api/mock-job/submit` is now 410) |

---

## Cross-Reference: Deep-Dive Documentation

| Topic | Document |
|-------|----------|
| Notification system | [`notification-api.md`](../notification-api.md) |
| Decision proxy | [`proxy-admin-guide.md`](../proxy-admin-guide.md) |
| WebSocket architecture | [`websocket-architecture.md`](../websocket-architecture.md) |
| WebSocket events | [`websocket-events.md`](../websocket-events.md) |
| CC transcript console | [`websocket-events.md`](../websocket-events.md) § CC Transcript Console Events |
| WebSocket troubleshooting | [`websocket-troubleshooting.md`](../websocket-troubleshooting.md) |
| Interactive testing | [`automated-interactive-testing.md`](../automated-interactive-testing.md) |
| Frontend architecture | [`lupin-mpa-frontend-architecture.md`](../lupin-mpa-frontend-architecture.md) |
