# 20 — Session Checkpoint: Deploy Incidents + Gate-Zero Baseline Repair

> **Session:** Tiberius 👑 `1333e106`, 2026-06-02 evening → 2026-06-03 early AM.
> **Trigger:** Rick greenlit the CoSA coverage grind after the messaging-plane deploy; two production-surface incidents interrupted Gate-Zero, both root-caused + fixed.
> **Status at checkpoint:** messaging incident CLOSED + committed; poker flood KILLED at source; Gate-Zero baseline repaired (11 reds → 0, final verification in flight); fleet NOT yet spawned.
> **Cross-ref:** messaging postmortem (María, PIP) `planning-is-prompting/src/rnd/2026.06.02-sam-tts-storm-incident-postmortem.md` (FM-20). Resume runbook: `02-cold-start-runbook.md`.

---

## 1. TL;DR

Rick deployed the messaging-coordination plane (MCP restart + `:7999`/`:8000` bounces) and said "run the grind." Before the fleet could spawn, **two distinct production-surface incidents** surfaced, both presenting as a "Sam error TTS flood":

1. **Drain-storm (one-shot):** the `:7999` bounce made WS listeners reconnect; the brand-new durable outbox replayed an **8,691-row stale undelivered backlog** as a TTS storm. Fixed: backfill + a structural age cap.
2. **Poker flood (recurring):** every full-unit-baseline run launched **real** heartbeat pokers that POSTed live escalation alarms — a test-isolation defect. Fixed: default the test's notify seam to a no-op.

Plus **Gate-Zero** (green baseline prerequisite) surfaced 11 reds — 5 genuinely-stale (contract drift) + 6 from **two cross-file test-pollution classes**. All fixed.

---

## 2. Incident 1 — Messaging drain-storm (CLOSED + committed)

**Symptom:** "zillion times + Sam error TTS" right after Rick's `:7999` bounce.

**Root cause:** lever-A durable outbox / lever-D pull-able inbox drained the **entire** undelivered set on reconnect with **no age bound**; `get_undelivered_for_recipient` + `count_undelivered_for_recipient` filtered only on state. Months-old urgent + `heartbeat_poker` error rows (oldest Feb 10) replayed via the **Sam default-error persona**.

**NOT the cause:** no live poker at the time; no orphan listeners (all 3 — Mr. Radio, María, me — live; zero zombies). I stopped María from SIGKILLing Mr. Radio's *live* listener (misread as orphan).

**Fix (2 parts):**
- **Part 1 (data):** backfilled 8,691 pre-bounce undelivered rows → `delivered_at=now()` (reversible, no deletes; cutoff 00:20Z). Residual undelivered = 1 (fresh).
- **Part 2 (code):** query-level `created_at` age cap on both repo methods, wired through both callers (WS `_compute_undelivered_count`, REST `/api/notifications/undelivered`) via a patchable resolver. New INI key `notification undelivered max age hours = 24` (+ splainer). **Structural** — covers the live path, not just today's backlog.

**Verification:** 14 unit green; live dev-DB probe (uncapped count 139 → capped 39, stale excluded); `:8000` integration `test_age_cap_excludes_stale_undelivered` green (3 passed); `:8000` restart → reconnect = zero storm.

**Commits:** `8447eec` (age-cap fix), `72ff343` (integration-test count-delta correction — the first :8000 run caught a naive assertion in *my* test, not prod: the shared test user's 100+ row backlog + getter `limit=100` oldest-first; rewrote to unbounded count deltas).

**FM-20** (María): *unbounded durable-outbox drain replays stale backlog as storm on reconnect.*

---

## 3. Incident 2 — Heartbeat-poker flood (recurring → KILLED at source)

**Symptom:** "heartbeat poker error messages and pings, again and again" — recurred ~once per baseline run.

**Diagnosis:** poker bursts landed ONLY during my full-baseline runs (per-minute log counts clustered at the run windows, **zero between**). Notifies came from sender `presentation.gen@lupin.deepily.ai#cli`, POSTed from the host (`172.19.0.1`) — i.e. the cosa-venv pytest process itself.

**Root cause:** `src/cosa/tests/unit/agents/test_heartbeat_poker_job.py` builds jobs via `_make_job`, which mocked the commons gateway (`FakeCommonsGateway`) **but left `notify_fn` defaulting to None** → the job's dead-man escalation ("silent for 3 consecutive pokes") + hard-cap ("60s cap — stopping") alarms fell through to the **real** `AgenticJobBase.notify_progress()` → POSTed to live `/api/notify` at `priority=high` → TTS flood. `FakeClock` drove many ticks fast → burst per test.

**Fix:** `_make_job` now defaults `notify_fn` to a no-op so unit tests NEVER emit real notifications (the notify_fn seam exists for exactly this; the 2 tests that assert on notifications override it). **Verified: poker test file = 45 passed, 0 real pokes to `:7999` during the run.**

**Hygiene rule (carry forward):** any heartbeat-poker test/E2E that exercises a *real* notify path MUST target a test recipient / suppress TTS / run on `:8000` — NEVER poke real personas on live `:7999` at `priority=high`. (FM-21 candidate for the framework.)

---

## 4. Gate-Zero — baseline repair (11 reds → 0)

Baseline = full unit suite under the **cosa `.venv` (py3.11 / pytest 9)** (NOT lupin `.venv`). First run: **11 failed / 12,523 passed**.

| Cluster | Tests | Verdict | Fix |
|---|---|---|---|
| `test_tfe_propose` | 2 | **Stale** — helper `_extract_last_json_array` removed (replaced by `_parse_proposal_json`, covered via `_parse_proposal_result` tests) | Deleted the 2 dead tests |
| `rest/test_database` | 3 | **Stale** — set `LUPIN_ENV=production` expecting cloud behavior, but `d2118f0` decoupled it: cloud-backing now gated by `LUPIN_CLOUD_BACKED` via `is_cloud_backed()` | Updated to the new contract |
| bfe resubmit ×2, tfe phase6 ×1, (+ my 2 lever-d helper tests) | 5 | **Pollution class A** — 12 test files import the **real `fastapi_app.main`** at module load, leaving it in `sys.modules` AND as the `fastapi_app.main` parent-package attribute, which defeats `patch.dict(sys.modules, {"fastapi_app.main": fake})` (import resolves the parent attribute) → mocked `config_mgr`/`jobs_todo_queue` are the real None | **New `src/conftest.py`**: autouse fixture evicting `fastapi_app.main` from sys.modules + clearing the parent attribute after every test |
| `memory/test_embedding_provider::TestUrlAndKeyResolvers` | 3 | **Pollution class B** — `test_local_embedding_engine.py` does raw `EmbeddingProvider._http_api_key = staticmethod(lambda: "test-key")` + `_resolve_model_server_url = staticmethod(lambda: None)` (class-level, **never restored**) → leaks the lambdas class-wide | Capture real staticmethod descriptors at import + autouse fixture restoring them after each test in that module |

**Two reusable lessons:**
- `patch.dict(sys.modules, {"pkg.mod": fake})` is **defeated** once `pkg` is imported with `mod` as a parent-package attribute (`import pkg.mod as m` resolves the attribute, not sys.modules). Evict or patch the attribute too.
- Raw class-attribute monkeypatching (`Cls.method = ...`) **never self-restores** — always use `patch.object` / `monkeypatch` / an autouse restore fixture.

**Verification:** targeted repros green (47 passed across polluters+victims for class A; 64 passed for class B). Final full baseline (v4) verifying 0 reds — in flight at checkpoint.

---

## 5. Files touched this session

**Committed (messaging incident):** `8447eec`, `72ff343` — `notification_repository.py`, `routers/websocket.py`, `routers/notifications.py`, `lupin-app.ini`, `lupin-app-splainer.ini`, `tests/unit/test_lever_d_undelivered_inbox.py`, `tests/integration/test_undelivered_inbox_integration.py`.

**Pending commit (Gate-Zero test-only batch, runbook §11 authority, on green):**
- `src/conftest.py` (new — fastapi_app.main eviction fixture)
- `src/cosa/tests/unit/agents/test_heartbeat_poker_job.py` (notify_fn no-op default)
- `src/tests/unit/test_local_embedding_engine.py` (resolver restore fixture)
- `src/cosa/tests/unit/rest/test_database.py` (LUPIN_CLOUD_BACKED contract)
- `src/tests/unit/test_tfe_propose.py` (deleted stale tests)

---

## 6. State + next steps (resume here)

- ✅ Messaging incident closed + committed + `:8000`-verified.
- ✅ Poker flood killed at source + verified.
- ⏳ Gate-Zero: final baseline (v4) verifying 0 reds → then **commit the test-only batch**.
- ⬜ Heartbeat poker live-tap verify (§7.3) — **must respect the §3 hygiene rule** (no real pokes to live personas).
- ⬜ Spawn fleet (3 authors + 1 reviewer, disjoint Tier-1 partition) — HELD with María until Gate-Zero green + her sign-off.
- ⬜ Run the grind loop.

**Holds outstanding (María's division):** fleet-spawn gated on Gate-Zero green. Messaging holds (#1 :8000 probe) cleared.

**Everything committed is HELD for Rick's session-end push** — nothing pushed.
