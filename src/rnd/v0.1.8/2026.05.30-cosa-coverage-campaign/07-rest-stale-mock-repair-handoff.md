# 07 — REST Stale-Mock Repair Lane — Author Handoff (Cheech 🌿)

> **Purpose:** hand off the `src/cosa/tests/unit/rest/` stale-mock repair lane to a fresh
> author (or to a rehydrated Cheech) with all drift intel already mapped, so execution is fast.
> Authored 2026-06-01 by Cheech 🌿 (session b505cdfa) at a deliberate honest-stop point — see §Why-handoff.
> Lane formally assigned by Tiberius 👑 (session 3047b30f).

## TL;DR
`pytest src/cosa/tests/unit/rest/` = **37 failed / 75 passed** (disk-confirmed, cosa venv 3.11).
All red is stale-mock / contract-drift in the TEST files (prod has moved on). Repair doctrine:
**fix the stale TEST to the LIVE prod contract** — NEVER rewrite an assertion to ratify buggy
prod output. The **403 queues case is the one trap** (could be a real regression) — read the live
auth logic before deciding test-fix vs tripwire+flag.

Interpreter (non-negotiable): `PYTHONPATH=src src/cosa/.venv/bin/python -m pytest ... -p no:cacheprovider`.
No SDK/scipy in this pile → plain pytest (no run-sdk-cov.sh). You do NOT commit — report per-file
red→green + before/after to Tiberius → Mr. Radio 🦉 audits → Tiberius commits.

## Failure inventory (per file)
| File | Fails | Notes |
|---|---|---|
| test_notifications_router.py | 10 | DEEPEST — notify_user fully re-architected (see §A) |
| test_queues_router.py | 9 | datetime patch + **403 per-user-auth (INVESTIGATE)** |
| test_system_router.py | 7 | datetime patch-target / frozen-instant |
| test_websocket_admin_router.py | 7 | datetime patch-target |
| test_websocket_router.py | 3 | WebSocketManager identity + session-id validation |
| test_fifo_queue.py | 1 | single (TBD) |

## §A — notifications router (the big one, 10 fails) — LIVE CONTRACT MAPPED
Live `cosa/rest/routers/notifications.py`:
- `notify_user` signature (line 272): **first param is `authenticated_user_id: Annotated[str, Depends(require_api_key_or_jwt)]`** — there is **NO `api_key` param**. Auth moved to the FastAPI dependency. → every test call passing `api_key=self.test_api_key` raises `TypeError: notify_user() got an unexpected keyword argument 'api_key'`. FIX: drop `api_key=`, pass `authenticated_user_id="<svc-id>"` instead.
- Email→system-id resolution (line ~450-457): now `from cosa.rest.user_service import get_user_by_email` → `user_data = get_user_by_email(target_user)` → `target_system_id = user_data["id"]`. **`email_to_system_id` no longer exists** → tests patching `cosa.rest.routers.notifications.email_to_system_id` raise AttributeError. FIX: patch `cosa.rest.routers.notifications.get_user_by_email` to return `{"id": self.test_user_system_id}` (it's a local `from ... import` INSIDE the function, so patch the source `cosa.rest.user_service.get_user_by_email`, OR patch at module level if hoisted — verify). User-not-found now raises **HTTPException 404** (line 452).
- Validation message drift: empty message now → **"Please provide a message to send"** (was "Message cannot be empty"). `valid_types` is now a LONG list (task, progress, alert, custom, user_initiated_message, session_topic, voice_persona_assigned, voice_persona_released, speakerphone_changed, commons_broadcast_ack, commons_answer_received, commons_activity, commons_question_received) — error text "Valid types: <all of them>". Priority message OK (still contains "Invalid priority" + "low, medium, high, urgent").
- `test_notify_user_invalid_api_key` (expects in-function 401 "Invalid API key") — **OBSOLETE**: auth is now the `require_api_key_or_jwt` dependency, not in-function. Repurpose to test the dependency directly, or remove with a note (flag to Tiberius — don't silently delete).
- Response status values (verify exact shapes at lines 613/638/675/724): `delivered_via_listener`, `user_not_available`, `queued`, `offline` — the stale tests expect `delivered`/`delivery_failed`. Rewrite assertions to the live status strings + response keys (`target_system_id`, `connection_count`).
- `get_local_timestamp` tests (test_get_local_timestamp_success / _fallback_to_utc): patch `cosa.rest.routers.notifications.datetime` + `.zoneinfo`. Live module uses `from datetime import datetime, timedelta, timezone` (line 13) so `cosa.rest.routers.notifications.datetime` IS patchable — verify the live get_local_timestamp call sequence (`datetime.now(tz)` → `.isoformat()`) still matches; re-pin the frozen instant if drifted.

**notify_user is ~650 lines (272-923) with response-required SSE / listener-delivery branches.** The stale tests only cover the simple fire-and-forget path. Rewriting them faithfully needs reading the full delivered/queued/offline return blocks first — budget for it.

## §B — datetime patch-target class (system / websocket_admin / queues / websocket — ~15 fails)
ALL routers use `from datetime import datetime` → `patch('cosa.rest.routers.<X>.datetime')` IS the correct target (the class is in the router namespace). Failures are AttributeError at unittest/mock.py:1416 + frozen-instant mismatch (`2025-08-05T12:00:00` vs real time leaking). Likely cause: live router now calls `datetime.now(timezone.utc)` / different method than the mock configures, OR moved the timestamp into a helper. PER FILE: read the live timestamp call, set `mock_datetime.now.return_value` to a mock whose `.isoformat()`/arithmetic matches the live usage, re-pin expected instant. Confirm `mock_datetime.now.assert_called_once()` still reflects a real call site.

## §C — THE 403 QUEUES TRAP (test_queues_router, ~4 fails) — INVESTIGATE FIRST
`HTTPException 403: "Cannot access other users' jobs. Regular users can only view their own jobs."`
This is per-user authorization that may be a **correct NEW contract** (→ fix the test to expect 403 / pass a matching user) OR a **prod regression** (→ arm `@pytest.mark.xfail(strict=True)` asserting the correct contract + pin current behavior + FLAG Tiberius; he owns the prod fix). **READ `cosa/rest/routers/queues.py` auth logic + git-blame the 403 before deciding.** Do NOT assume test-fix.

## §D — websocket_router (3 fails)
WebSocketManager identity assertion (`!= 'mock_websocket_manager'`) = patch-target drift (the dependency now returns the real manager singleton, not the string) + session-id validation rule drift (`test_is_valid_session_id_invalid_cases`, subfail on `'special-chars'`). Read the live `is_valid_session_id` rules + the get_websocket_manager dependency.

## Why-handoff (honest-stop)
Cheech completed notification_proxy (173 tests, genuine 100%, gated) THEN took this lane and did the
full read-only diagnostic above. At that point the session was at deep context (multiple 600+ line
file reads). Per the campaign's honest-stop discipline (memento §Fleet-management: "authors stop at
clean green lines rather than push phantom-risk work at deep context, write a handoff memento, spawn
fresh"), Cheech stopped before rewriting against the 650-line notify_user to avoid phantom tests.
**Zero rest/ test edits were made — all 6 files are untouched.** A fresh author starts from this doc.

## Resume checklist
1. cosa venv; `pytest src/cosa/tests/unit/rest/ -q` → confirm 37 failed/75 passed baseline.
2. Start with the datetime class (§B) — mechanical, highest count, fastest green.
3. notifications (§A) next — read full notify_user return blocks before rewriting.
4. queues 403 (§C) — investigate-then-decide; flag Tiberius on any real regression.
5. Per-file report (red→green + before/after) → Tiberius disk-verify → Mr. Radio audit → commit.
