> Part 1 of 2 of the [Heartbeat-Arbiter Routing & Recipients Guide](../heartbeat-arbiter-routing-guide.md): sections 1 to 4, the loops, the routing table and the redline.

# Heartbeat-Arbiter Routing & Recipients Guide

**Whole-system context**: this guide covers the arbiter's *routing* (who it contacts). For the **top-to-bottom** picture, see [`../fleet-liveness-and-task-store-architecture.md`](../../fleet-liveness-and-task-store-architecture.md). It shows how the arbiter fits with the unified task-store, the Stop-hook self-poke, the UI card, and the manager/worker lifecycle.

**Audience**: Lupin operators reasoning about who the fleet arbiter contacts (and why), and developers maintaining or extending the arbiter's routing logic.

**Scope**: `src/cosa/agents/heartbeat_arbiter/` (routing table, consumer job, manager resolver) + `src/lupin_arbiter_app/` (the :8001 service that wires the two loops to their delivery sinks).

**Verified against**: `arbiter_routing.py`, `arbiter_job.py`, `manager_resolver.py`, `fleet_arbiter_loop.py`, `app.py`, `arbiter_live_notify.py`, `health_watcher.py`.

**See Also**:

- R&D origin: [Arbiter routing & recipients summary](../../../rnd/v0.1.8/2026.06.04-heartbeat-hook/2026.06.09-arbiter-routing-and-recipients-summary.md) — the one-page distillation this guide formalizes
- R&D design: [Arbiter consumption gap & operator loop](../../../rnd/v0.1.8/2026.06.04-heartbeat-hook/2026.06.08-arbiter-consumption-gap-and-operator-loop.md) **Part 6** — the ratified 12-case routing model (Rick's judgment calls)
- [Agentic Jobs & Recovery README](../README.md) — sibling agent guides (BFE, TFE)

---

## Table of Contents

1. [What This Guide Answers](#1-what-this-guide-answers)
2. [Two Loops, One Routing Model](#2-two-loops-one-routing-model)
3. [The 13-Case → 6-Tier Routing Table](#3-the-13-case--6-tier-routing-table)
4. [How `_route` Executes a Tier (the Non-Actuation Redline)](#4-how-_route-executes-a-tier-the-non-actuation-redline)
5. [Who Counts as an "Active Manager"? (Resolver + Phantom Guard)](02-resolver-delivery-health-and-operations.md#5-who-counts-as-an-active-manager-resolver--phantom-guard)
6. [The Two Delivery Mechanisms](02-resolver-delivery-health-and-operations.md#6-the-two-delivery-mechanisms)
7. [Does the Health-Check Loop Notify? — Yes (Loop A → Rick-Only)](02-resolver-delivery-health-and-operations.md#7-does-the-health-check-loop-notify--yes-loop-a--rick-only)
8. [End-to-End Flow Diagram](02-resolver-delivery-health-and-operations.md#8-end-to-end-flow-diagram)
9. [Operational Notes](02-resolver-delivery-health-and-operations.md#9-operational-notes)
10. [Code Map](02-resolver-delivery-health-and-operations.md#10-code-map)

---

## 1. What This Guide Answers

The heartbeat-arbiter is the fleet's out-of-band observer. It watches the local
Heartbeat Hook's event exhaust, the commons gateway, and Docker container health,
then **escalates** — it *senses and recommends*, it never *actuates*. This guide
answers three operator questions exactly:

1. **How does the arbiter determine who to contact?**

   It uses a pure, auditable
   table (`CASE_TIERS`) that maps every distinct arbiter output to exactly one of
   six recipient tiers.
2. **How is contact accomplished across all scenarios & recipients?** — via two
   non-destructive channels only: a Rick-bound `notify_fn` and a directed
   `commons.send_to` manager/blocker DM.
3. **Does the health-check loop also issue notifications?** — **Yes.** It routes
   container/self-health alerts to **Rick only**, through the **same** escalation
   sink (see [section 7](02-resolver-delivery-health-and-operations.md#7-does-the-health-check-loop-notify--yes-loop-a--rick-only)).

This guide covers the **routing & recipients** facet specifically. For the
broader arbiter design, see the R&D directory linked above. It covers event
tailing, fleet-view construction, dependency graph, idle roster and the v2.1
direct-state snapshot.

---

## 2. Two Loops, One Routing Model

The arbiter functionality runs as two independent loops inside the standalone
`lupin-arbiter-app` service on **:8001**, and both feed a single recipient-routing
model.

| Loop | Name | Layer | Source | Responsibility |
|------|------|-------|--------|----------------|
| **Loop A** | `health_watcher` | Layer 2 | `lupin_arbiter_app/health_watcher.py` | Per-container Docker health + self-watch ("am I blind?") |
| **Loop B** | `fleet_arbiter` | Layer 3 | `cosa/agents/heartbeat_arbiter/arbiter_job.py` (`ArbiterConsumerJob`) | The fleet operator loop — tail events → fleet view → dependency graph → blocked/stuck/deadlock/decision detection |

Both loops emit outputs that are **numbered cases**, and each case maps to exactly
**one recipient tier** in the pure table `arbiter_routing.CASE_TIERS`. The two
loops differ only in *which* cases they raise:

- **Loop A** raises cases **#1 / #2 / #3** — all hard-wired to **Rick-only**
  (infra is the human's domain; managers don't act on containers).
- **Loop B** raises cases **#4 … #13** — routed **per-case across all six tiers**.

The single shared idea: a case number is the contract; the tier is the answer to
"who?"; the executor (`_route`) is the answer to "how?".

---

## 3. The 13-Case → 6-Tier Routing Table

The contract lives as a **pure leaf** in `arbiter_routing.py` — no I/O, no seams —
so the routing is auditable and 100%-testable in isolation. `CASE_TIERS` is the
runtime dictionary. `tier_for(case)` is the lookup. It raises `KeyError` on an
unknown case: a new output **must** be routed explicitly, never silently
defaulted.

### The six recipient tiers

| Tier constant | Reaches | Channels used |
|---------------|---------|---------------|
| `TIER_RICK_ONLY` | Rick only, no managers | `notify_fn` |
| `TIER_RICK_AND_MANAGERS` | Rick + every active manager | `notify_fn` + `send_to` (each active manager) |
| `TIER_OWNING_MANAGER` | the resolved owning manager | `send_to` |
| `TIER_BLOCKER_AND_MANAGER` | the blocker + cc its owning manager | `send_to` (blocker) + `send_to` (manager) |
| `TIER_DROP` | nobody — pull-state via `/state` | (none) |
| `TIER_LOG_THEN_RICK` | log; escalate to Rick only if persistent | `notify_fn` (only past a streak threshold) |

### The full case → tier table (`CASE_TIERS`)

| # | Case | Loop | Tier | Why |
|---|------|------|------|-----|
| 1 | container enter-unhealthy | A | `RICK_ONLY` | infra; managers don't act on containers |
| 2 | container flapping | A | `RICK_ONLY` | ops alert |
| 3 | health-watch `BLIND` | A | `RICK_ONLY` | "the arbiter's eyes are out" (e.g. docker daemon down) |
| 4 | blocker holding up a worker | B | `BLOCKER_AND_MANAGER` | direct nudge to the blocker + manager looped in |
| 5 | deadlock cycle | B | `RICK_AND_MANAGERS` | a human/manager breaks it; resilient to owning-mgr-down |
| 6 | fleet roster (per-tick) | B | `DROP` | roster is pull-state, served by `/state` — broadcast cut |
| 7 | manager tap | B | `OWNING_MANAGER` | the core per-worker actionable nudge |
| 8 | unresolved-manager (orphan) worker | B | `RICK_AND_MANAGERS` | any manager could adopt it |
| 9 | manager-down + `HOLD` | B | `RICK_AND_MANAGERS` | leaderless crew; re-staff |
| 10 | decision-needed | B | `RICK_ONLY` (+ owning mgr cc if known) | decisions are the human's domain |
| 11 | whole-fleet-stall | B | `RICK_AND_MANAGERS` | calibrated; rare + severe |
| 12 | arbiter poll-error | B | `LOG_THEN_RICK` | demoted from a per-error ping; escalate only if persistent |
| 13 | auto-poke reap-**recommendation** | B | `RICK_AND_MANAGERS` | post-Part-6 (2b-3) addition; **recommendation only** |

**Cases #1–#12** are the ratified **Part-6** model (Rick's judgment calls). **Case #13** (`CASE_AUTO_POKE_REAP_REC`) is a post-Part-6 (2b-3)
addition routed through the same dispatcher. After a stuck **live** session
absorbs ≤N bounded non-destructive pokes with no recovery, the arbiter recommends
a reap/replace to Rick + all active managers. It **never executes it** (the
redline; see [section 4](#4-how-_route-executes-a-tier-the-non-actuation-redline)).

### Two important precision points

- **#10 (decision-needed)** routes to **Rick-only via the tier**. The owning
  manager is cc'd by a *separate* side-call (`_cc_decision_manager`), **outside**
  the tier dispatch, and only when the post's `sender_session_id` resolves to a
  DM-able manager. No resolution → Rick-only, no-op cc.
- **#12 (poll-error)** is **not** dispatched through `_route`. It is handled by
  `_on_poll_error`'s streak logic. A transient one-off hiccup is logged. Only
  `≥ poll_error_escalate_threshold` consecutive failures escalate (once) to Rick
  via `notify_fn` ("arbiter effectively down"). A clean poll resets the streak.

---

## 4. How `_route` Executes a Tier (the Non-Actuation Redline)

`ArbiterConsumerJob._route(case, message, …)` is the single dispatcher. It looks
up `tier_for(case)` and executes the tier using **only two seams**:

- `self._notify_fn(message)` → **Rick** (durable post + best-effort live push)
- `self._commons.send_to(recipient, message)` → **a directed manager/blocker DM**

```python
tier = tier_for( case )
if   tier == TIER_RICK_ONLY:           self._notify_fn( message )
elif tier == TIER_RICK_AND_MANAGERS:   self._notify_fn( message )
                                       # + send_to each active manager
elif tier == TIER_OWNING_MANAGER:      self._commons.send_to( owning_manager, message )
elif tier == TIER_BLOCKER_AND_MANAGER: self._commons.send_to( blocker, message )
                                       # + send_to( owning_manager, cc_message )
# TIER_DROP → intentional no-op (#6 roster broadcast is cut)
```

**The redline (standing invariant):** the arbiter **never actuates** — no reap,
kill, replace, spawn, or auto-assign. It calls only `{notify_fn, send_to}` (plus
read-only `who`/`read`). This is enforced **structurally** by an AST-scan test
(`test_arbiter_redline`), not merely by convention. Even the auto-poke (#13)
sends a *non-destructive wake-nudge* and then a *recommendation* — it takes no
destructive action.

**Degrade-safe absence of recipients:** missing optional recipients degrade
silently. `TIER_OWNING_MANAGER` with no resolved manager → no-op;
`TIER_RICK_AND_MANAGERS` with an empty active-manager set → Rick still gets the
escalation. No escalation is ever lost because a manager couldn't be resolved.

---

