# Lane B — Arbiter Staleness-Filter (`bc1bc373`, P2)

**Date**: 2026-06-23 · **Author**: Sam 🎙️ (worker cc-author-mr-radio-2, session f7f98772) · **Manager**: Mr. Radio 🦉
**Branch**: `wip-v0.1.9-2026.06.21-bug-fix-implementation` · **Design-of-record**: `01-build-plan.md §2`
**Review routing**: → María 🌸 (reproduce-not-trust) via `dm-mr-radio`

---

## 1. Problem (verbatim from task `bc1bc373` body)

The arbiter emitted phantom **"mr radio blocking Tiffany"** / **"DEADLOCK Tiffany→mr radio"** advisories
inferred from the DM-wait / bridge graph, **NOT** from any store `blocked_by` edge (Tiffany's store board
was empty: 0 in_progress / 0 blocked). Root cause: the bridge graph ingests the `holding_on: peer:X`
wait-edge **without** filtering out holds that are **stale / expired / `work_owed=false`** — so a **DEAD
hold can still feed an inferred edge**. Mr Radio's acute mitigation (hand-sweeping 2 dead Tiffany hold
files) is per-incident, not durable.

## 2. Root-cause seam

```
build_fleet_view(...)            # view["holding_on"] ← most-recent event "awaiting" field
  └─ build_graph(fleet_view)     # build_wait_edges → {holder: awaited}; find_deadlock_cycles → rings
        ├─ _escalate_deadlocks(cycles, store_edges)   # 436a366b: store-CORROBORATED (already gated)
        └─ _auto_ping(live_edges)                     # "X is blocking worker Y" advisory — NOT gated
```

The `holding_on: peer:X` edge is **self-reported** (event `awaiting`). When the declaring session's hold
goes **dead** (expired / `work_owed=false` / past `next_chase`), the lingering `awaiting` still produces a
peer edge that feeds `_auto_ping` (the phantom "blocking" advisory) and `_attention_workers` / taps. The
deadlock path is already store-corroborated (`436a366b`), so the *primary* phantom is the **non-corroborated
`_auto_ping` advisory**.

## 3. Fix — ADDITIVE staleness predicate, upstream of edge inference

**Guardrail (María)**: do **NOT** touch the deployed deadlock path (`4ed948c7`, cycles=0). **Additive
only** — filter the hold inputs **before any edge is built**. Achieved by neutralizing a dead-hold
holder's peer edge at `build_wait_edges` ingestion — so it contributes **zero** edges to **every**
consumer (blocked-edge, deadlock cycles, manager-blocking advisory) in one chokepoint.

### 3.1 Pure predicate — `dependency_graph.hold_is_stale( hold, now )`

A hold is **STALE** (dead for edge inference) on **ANY** of three axes:

| Axis | Rule | Source primitive (reused — no reinvention) |
|---|---|---|
| **EXPIRED** | `not is_fresh( hold, now )` (now − held_at ≥ ttl_seconds, or uncredible held_at/ttl) | `heartbeat_hold.is_fresh` |
| **NOT-WORK-OWED** | `declared_work_owed( hold ) is False` (explicit `False`; `None`/absent ≠ stale) | `heartbeat_hold.declared_work_owed` |
| **PAST-NEXT-CHASE** | `next_chase` present + parseable + `≤ now` | local `_parse_iso` |

- A **missing / non-dict** hold → **NOT stale** (`False`). Absence of a hold is not evidence of a dead
  hold — we never over-filter a session that simply has no hold file (its edge is governed by its event
  `awaiting`, unchanged). The filter can only **subtract** an edge for a session with a **readable DEAD hold**.
- `next_chase` is an **optional** field — holds don't emit it today (the live axes are EXPIRED +
  NOT-WORK-OWED), but the predicate honors all three axes the AC names and is forward-compatible.
- Bias: when a hold exists but can't prove freshness (unparseable `held_at` / bad `ttl`) → treated **STALE**
  (bias-to-suppress), matching the deadlock detector's own documented fail-SUPPRESS bias.

### 3.2 Pure edge filter — `build_wait_edges( fleet_view, stale_holders=None )` / `build_graph( ..., stale_holders=None )`

`stale_holders` is an OPTIONAL set of holder **personas** whose `holding_on` peer edge is dropped at
ingestion. `None`/empty → byte-identical to prior behavior (every existing test + the deployed deadlock
path unaffected). A dead holder removed from `edges` is also removed from `cycles` → it can never be
store-backed-escalated either, **without touching the deadlock LOGIC** (`cycle_is_store_backed` /
`build_store_wait_edges` / `_escalate_deadlocks` are byte-identical).

### 3.3 Arbiter IO seam — `ArbiterConsumerJob._stale_hold_holders( fleet_view, now )`

Computes `stale_holders` once per poll, **before** `build_graph`. For each view that carries a `peer:`
`holding_on` + persona + session_id, it reads the hold via the **already-wired** `_hold_reader_fn`
(`read_hold` on `:8001`) and adds the persona to the set iff `hold_is_stale`. Swallow-safe (a raising
reader degrades to "not stale" for that session); **inert when the reader is unwired** (`None` → empty set
→ today's behavior). Only peer-edge holders are read (minimizes IO). Then:

```python
stale_holders = self._stale_hold_holders( fleet_view, now )   # NEW — IO seam, inert when unwired
graph         = build_graph( fleet_view, stale_holders=stale_holders )
```

## 4. Acceptance criteria → test mapping

| AC | Assertion | Test |
|---|---|---|
| **B.1** | expired / `work_owed=false` / past-`next_chase` hold → **0** edges | `hold_is_stale` truth-table (3 axes × live/dead) + `build_wait_edges(stale_holders=...)` drops the edge + arbiter poll fires **0** pings |
| **B.2** | live + honored + work-owed hold → edge **kept** | `hold_is_stale` returns False for fresh/honored/owed; arbiter poll still pings the live blocker |
| **B.3** | deployed deadlock-on-store-`blocked_by` gate (`436a366b`) **unchanged** | store-corroboration suite passes verbatim; a store-backed ring still fires with the filter present |

100% lines/branches/functions on the two changed modules (`dependency_graph.py`, the new `arbiter_job`
method). Venue: `:7999`-eligible unit (fully mocked I/O, sub-second).

## 5. Files changed

- `src/cosa/agents/heartbeat_arbiter/dependency_graph.py` — `hold_is_stale`, `_parse_iso`, `stale_holders` param on `build_wait_edges` / `build_graph`.
- `src/cosa/agents/heartbeat_arbiter/arbiter_job.py` — `_stale_hold_holders` seam + one-line wire in `_poll_once`.
- `src/tests/unit/test_dependency_graph.py` — staleness-predicate + edge-filter truth-table.
- `src/tests/unit/test_heartbeat_arbiter_job.py` — arbiter integration (dead hold → 0 pings; live hold → ping; store-ring intact).
