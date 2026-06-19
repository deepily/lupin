# Heartbeat v2 — Integration-Testing Contribution (Mr. Radio 🦉, idx 3)

**Author:** Mr. Radio 🦉 (Lupin session `e1c93749`, dedicated integration tester)
**Date:** 2026-06-05
**For:** repo-level roll-up (María 🌸) + global roll-up (Tiberius 👑)
**Status:** Documentation commit. Two integration suites delivered; find→fix→lock driven on 3 cross-module findings (2 LOCKED, 1 pending an upstream design value).
**Siblings:** `01`–`04` (design), this doc = the independent integration-test record.

---

## TL;DR

Built the two whole-chain integration suites for the Heartbeat system — the layer that drives **real modules through real on-disk files**, catching the cross-module seam bugs that per-module 100%-unit coverage structurally cannot. Surfaced **3 adversarial findings** the unit tier passed over; 2 are fixed + locked, 1 awaits an upstream threshold value.

## Deliverables

| Suite | File | Tests | Cov | State |
|---|---|---|---|---|
| Hook v2 whole-chain | `src/tests/unit/test_heartbeat_integration.py` | 41 | 100% L+B on test-support | **COMMITTED `fd3d9e7`** (by Rachel, combined v2 set) |
| Arbiter consumer whole-chain | `src/tests/unit/test_heartbeat_arbiter_integration.py` | 15 | 100% L+B on test-support | green; UNCOMMITTED (combined commit gated on F3 + Tiberius review) |

**Why a separate tier:** every per-module suite either is pure-unit or mocks the other half (the Hook suite mocked the leaves; the arbiter suite uses hand-built event dicts + a fixed clock). Neither drives the **real producer → real consumer** chain on real files, nor the multi-poll backoff trajectory against an advancing clock. These suites do.

### Hook suite coverage (committed)
Groups A–G + S: producer chain (FM-19, last-write-wins, ordinal taskId, scale) · poke-cap + re-engagement reset · hold↔oracle precedence · idle edge-trigger (de-dup/supersede/sticky) · fire-and-forget degradation · `main()` precedence (heartbeat LOSES to speakerphone/loop-guard/voice) · arbiter exhaust contract · settings loader. Hermetic; heartbeat ships dormant.

### Arbiter suite coverage (green; awaiting combined commit)
Groups PC/T/TH/INFER/ISO: producer→consumer loop closure (real Hook emit → real `tail → fleet_view → graph → roster → auto-ping → escalate`) · incremental byte-offset tail + partial-line + cross-poll stuck accumulation · backoff trajectory + global-cap rolling window + clear-on-resume (advancing clock) · inferred roster · read-only-on-event-plane + full `_execute` loop + cancel.

## The 3 adversarial findings (the integration tier earning its keep)

| # | Finding (unit-invisible) | Owner | State |
|---|---|---|---|
| **F1** | `_auto_ping` keyed `edges` by PERSONA but did `fleet_view.get(holder)` (SESSION_ID) → ping reason collapsed to `"none"`; throttle degraded to per-`(holder,awaited)` | Rachel | ✅ **fixed + LOCKED** (dropped the unsourceable reason; PC4 locks recipient + holder-only message) |
| **F2** | backoff off-by-one — `attempt` pre-incremented so `schedule[0]=60s` never gated; real first re-ping gap was 300s | Tiffany (adjudicated) / Rachel (wired) | ✅ **fixed + LOCKED** (`backoff_for_attempt(attempt-1)`; TH1 locks the corrected 60→300→900 ladder) |
| **F3** | inferred-roster **config-dead** with default thresholds (idle 900 > alive 600) → the HYBRID's inference half silently reduced to declaration-only | María (threshold reconciliation) / Rachel (job defaults) | ⏳ **pending the canonical §6.2 value**; INFER1 proves the path with idle<alive; a **defaults-lock** is added the moment the reconciled value lands |

Each finding was found by the advancing-clock / real-file integration angle, confirmed against the code, and adjudicated by its owner. The lessons: unit suites that mock or hardcode a seam (persona-vs-sid, fixed clock, hardcoded `alive=True`) cannot see these; the integration tier must drive the real boundary.

## Process note (owned)

The fleet (myself included) stalled by treating "F3 pending María" as a stopping point rather than driving the upstream value to resolution. Correction: surface the blocker AND push the owner toward the decision in the same motion; don't idle on "waiting for X."

## Verification (latest)

- Arbiter integration suite: **15/15 green, 100% line+branch** on test-support, against the F1/F2-fixed tree.
- Full re-run: **155 passed** across all arbiter + heartbeat unit + integration suites (Rachel's `_auto_ping` signature change clean across the unit tier).
- Hermetic audit: zero synthetic pollution in the real fleet dir / repo root / `/tmp`.

## Outstanding (post-roll-up tonight)

1. F3: María lands canonical `idle_threshold < alive_threshold`; Rachel aligns `ArbiterConsumerJob` defaults; I add the **defaults-lock** test (inferred reachable with shipped defaults) + re-verify.
2. Combined arbiter commit (Rachel's code + Tiffany's leaves + my integration suite) → Tiberius pre-commit review → commit.
3. Heartbeat re-enable to production (settings flip) — owner-driven; I verify post-enable.
