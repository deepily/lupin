# 19 — Tiberius 👑 Evening Rehydration Memento (post-messaging-plane → CoSA grind)

> **For:** a fresh-context Tiberius (manager) + María 🌸 (steward), re-spawned after Rick's MCP/server restart, before the CoSA coverage grind.
> **Written:** 2026-06-02 evening (session `1333e106`), by Tiberius.
> **TL;DR:** the messaging-coordination plane is DONE + committed; once the restart + server bounces land it's LIVE, so the grind fleet finally has a reliable coordination plane (FM-7 addressed). Resume the grind from the cold-start runbook (§15).

---

## 1. What just shipped (this session) — all committed, HELD (not pushed)

- **Messaging-coordination plane — ALL 5 LEVERS COMPLETE** (`722e624` = A/D, `4eb435c` = B/C/E):
  - **A** durable notify outbox + drain-first ordering (`src/lupin_mcp/notify_outbox.py` + `cosa_voice_mcp.py`).
  - **D** pull-able AFK inbox (`GET /api/notifications/undelivered` + `undelivered_count` on WS auth_success + `#missed-status` UI). :8000 integration 2/2.
  - **B** event-loop de-block (notify DB-persist + commons broadcast → `asyncio.to_thread`).
  - **C** express lane (priority queue serves high/urgent ahead; regression-locked).
  - **E** per-session backpressure (`src/cosa/rest/notify_rate_limiter.py`, 429 + Retry-After, INI-tunable).
  - **Verification:** 990 unit tests green + :8000 integration. Design + ratified decisions: `src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md`.
- **Earlier in the session:** CoSA-campaign post-game (`18-postgame-coordinated-for-rick.md`), TTS spoken-brevity cap (caller-side, INI-tunable, default 500 chars), `dismiss_sessions` reap verified live, guided-decision-walkthrough skill (`/plan-decide`) installed.

## 2. Goes LIVE on the restart + bounces (deploy checklist)

The fixes are committed but **not live** until:
1. **MCP restart** (Rick) — activates the MCP-side: TTS cap, durable outbox, outbox config reads.
2. **`:7999` (dev) bounce** — `docker restart lupin-rest-dev` — activates the server-side: B de-block, D endpoint, E backpressure. (Tiberius may do this; standing permission.)
3. **`:8000` (test) bounce** — `docker restart lupin-rest-test` — for the grind's scheduled test runs. (Already bounced once this session for the lever-D integration.)

After all three: the grind fleet's notify/commons plane is hardened — **no more black-holes (FM-7)**, interactive voice prioritized, runaways throttled, nothing silently lost.

## 3. Resume the CoSA grind here

- **Goal:** CoSA 100%-coverage grandfathering ramp — deadline **2026-06-05** (TODO.md top entry).
- **▶ START:** the cold-start runbook **§15 cold-start checklist** → `src/rnd/v0.1.8/2026.05.30-cosa-coverage-campaign/02-cold-start-runbook.md`. Campaign plan (decisions D1–D8): `00-campaign-plan.md`.
- **Sequence (per runbook):** live-verify the heartbeat-poker → land the Tier-0 `[tool.coverage]` config → spawn 3 FRESH authors + 1 reviewer (cold-briefed, disjoint Tier-1 module-groups) → grind (per-batch reviewer-gate + green-gate, **test-only** commits).
- **Gate-zero (do FIRST, per post-game F-2):** verify the canonical interpreter — the **cosa `.venv` (py3.11 / pytest 9)**, NOT the lupin `.venv` (py3.13/pytest8 silently masks reds). Run via `src/scripts/run-sdk-cov.sh` for SDK/scipy packages.

## 4. Operating doctrine (post-game lessons — apply from turn 1)

- **Harvest-on-unproductive (Rick ×3):** reap stalled/degraded/finished workers immediately; `extra-N` (🪨) appearing = pool-exhaustion ALARM. `dismiss_sessions(session_names=[...])` works now (typed-wrapper fix live post-restart); never tmux-kill (orphans listeners).
- **Defense-in-depth gate:** author measure → manager disk re-measure (cosa venv) → independent reviewer re-measure. Trust ZERO remembered numbers.
- **Spawn-health probe:** double-read a known file at spawn; reject on disagreement.
- **Honest-stop:** a degrading worker stops at a clean green line + writes a handoff; spawn fresh.
- **Difficulty ≠ defer (FM-19):** mandated in-scope 100% work is NEVER user-gated; gate only on irreversible/prod-behavior/true-ambiguity/scope-expansion.
- **TTS cap is LIVE:** spoken `notify`/`ask` ≤ ~500 chars — headline + one takeaway; ALL detail in `abstract`. Use `override_size_limitation=True` only to knowingly exceed.

## 5. Division + coordination

- **Tiberius** = infra + manager (fleet, gate, runbook). **María** 🌸 = steward (framework synthesis, completion-discipline, harvest doctrine). Canonical framework lives in planning-is-prompting.
- Coordinate over commons DM (`dm-tiberius` / `dm-maria`). The plane is hardened now — pushes are reliable post-restart.

## 6. Open / deferred (not blockers)

- Comprehensive loop-de-block sweep (Pending Decision in TODO.md) — surgical fix landed; revisit colder sync I/O later.
- Optional `:8000` load/storm test for the messaging plane (design-doc test plan).
- Everything HELD for Rick's session-end push (he owns the push).
