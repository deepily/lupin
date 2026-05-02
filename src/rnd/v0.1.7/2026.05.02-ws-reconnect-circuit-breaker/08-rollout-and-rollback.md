# Rollout and Rollback — WS Reconnect Circuit-Breaker

## Landing Strategy

Single-PR landing into the active branch
`wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`. Phases
1–5 land as separate commits but ship as one merge to `main`.

The PR title and body summarize the user-observable behavior change
(banner appears instead of unrecoverable tab) and link to this doc set.
Per project CLAUDE.md §PR MERGE REQUIREMENTS, the merge is gated on:

| Gate | Status before merge |
|------|---------------------|
| Layer 1 unit tests | ALL PASS |
| Layer 2 Python WS smoke tests | ALL PASS |
| Layer 3 Browser integration tests | ALL PASS |
| Layer 4 Browser real-server tests | ALL PASS (scheduled on `:8000`) |
| Layer 5 Live reproducer | PASS (scheduled on `:8000`) |
| Existing `pytest src/tests/unit/` regression | UNCHANGED |
| Existing `run-websocket-smoke-tests.sh` regression | UNCHANGED |
| Existing `run-e2e-ui-tests.sh --bg -v` (full sweep) | UNCHANGED |
| Existing `run-integration-tests.sh --bg -v` (final gate) | UNCHANGED |

## Rollback Plan

Single-commit revert: `git revert <merge-commit-sha>`. The change is
isolated to:

- `src/fastapi_app/static/js/notifications.js` (modified)
- `src/fastapi_app/static/js/ws-channel.js` (added — revert deletes)
- `src/fastapi_app/templates/notifications.html` (modified — banner markup)
- `src/fastapi_app/static/css/notifications.css` (modified — banner CSS)
- `src/cosa/rest/routers/websocket.py` (modified — close codes)
- `src/docs/websocket-events.md`, `src/docs/websocket-architecture.md` (modified — docs)

No database migrations, no INI changes, no API contract breaks for
external clients (close codes are advisory; old clients ignore them
and behave as before).

## No Feature Flag

Per Q12 (`01-design-review.md` §3): no INI gate, no localStorage flag,
no env var. Rejected because:

1. The change is a strict superset of correct behavior. The worst-case
   regression is "circuit opens too early during legitimate flap" which
   is observable in the user's own session and tunable via constant-edit.
2. Per memory `feedback_feature_flag_preserves_old_path`, a runtime fork
   means BOTH branches stay first-class and maintained forever. We don't
   want to maintain the buggy code path indefinitely.
3. Rollback via `git revert` is single-command and restores prior
   behavior in seconds.

## Behavior Changes for User

After landing, the user will observe these differences from current:

| Today | After this fix |
|-------|----------------|
| Reconnect attempts climb past 100, 200, 461 with no UI feedback beyond the WS-status pill | After ~20 failed attempts (~6–10 min wall-clock under jittered backoff), a red banner appears at the top of the notifications UI |
| Recovery requires killing the tab | Recovery requires clicking "Retry now" in the banner |
| Reconnect attempts continue at 3 AM during overnight server restarts (logged but harmless) | Same — but bounded by the 20-attempt budget |
| Auth failure produces a generic 1006 close + retry loop | Auth failure produces an immediate banner via close code 4001/4002/4003 |
| `wsDiag` log shows `Scheduling reconnect attempt #N for ${target}` with shared counter | `wsDiag` log shows `[queue] backoff Xms attempt N reason=...` with per-channel counter |
| Tab opening from background may produce a burst of reconnect attempts | Tab opening from background fires a single targeted reconnect via `visibilitychange` handler |

## Soak Window

Recommend a one-week soak on the working branch (with the AI driving
all five test layers green at every checkpoint) before merging to main.
Soak surface:

- The user's own daily Lupin session usage exercises Layers 4 + 5
  organically (legitimate disconnects + reconnects throughout long
  sessions).
- AI runs Layer 4 + 5 on `:8000` once per soak day at a user-confirmed
  slot.

If the soak surfaces:
- A circuit opening during a legitimate flap → adjust Q5 (raise MAX) or
  Q6 (raise rapid-fail count). One-line constant edit; not a re-design.
- A circuit failing to open during a real outage → debug the watchdog
  vs. the `onclose` path. Re-run plan-review §Pass 2 on the affected
  Phase doc.
- An unrelated regression (E2E UI snapshot drift, integration test
  failure) → triage independently. Not a soak failure for THIS milestone.

After clean soak: cherry-pick (or merge) into `main` per the existing
project branch-and-PR workflow.

## Success Criteria (Post-Merge)

1. Zero reports of the "unrecoverable tab + Insufficient resources" symptom.
2. Banner appears as expected during the next legitimate outage event
   (server restart, network blip, tunnel hiccup).
3. Retry-now button recovers the session in one click.
4. No regression in any other test layer on subsequent PRs against main.

## Open Follow-ups (Deferred)

- v2: Multiplex `/ws/queue` and `/ws/audio` over a single transport.
- v2: `WebSocketStream` for the audio channel (Chrome-only).
- v2: Telemetry beacon for circuit-open events (tuning data for Q5/Q6).
- v2: uvicorn `--ws-ping-interval` if dead-client detection becomes a
  measured problem.
- v2: SSE fallback for proxied/firewalled environments.
- v2: Make MAX_ATTEMPTS_PER_CHANNEL, BACKOFF_BASE_MS, etc. into INI keys
  if per-environment overrides become useful.
