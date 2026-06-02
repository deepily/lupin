# 09 — Failure-Mode Mitigations: Decision Menu for Rick

> **Author:** Tiberius 👑 (campaign manager, session `b8a9f332`).
> **Written:** 2026-06-01, in response to Rick's broadcast: *"resolve and incorporate measures to mitigate/prevent the failure modes Tiberius identified — specifically the honest shutdown and reaping of nonproductive contributors, plus the rest — and present them as a series of informed choices."*
> **Companion to:** [`08-tiberius-postgame-what-worked-didnt-unfinished.md`](08-tiberius-postgame-what-worked-didnt-unfinished.md) §Q2 (the failure-mode catalog F-1…F-6).
> **Destination:** María 🌸 folds these into the dependable-coverage-campaign framework (`planning-is-prompting/src/rnd/2026.06.01-dependable-coverage-campaign-framework.md`); we co-present the menu.
> **How to read:** each decision is a **menu**, not a directive. Every option carries pros + cons; each decision ends with **my recommendation + a flip-condition** (what would make me change it). Pick per row; mix freely.

---

## Centerpiece — Honest Shutdown & Reaping of Nonproductive Contributors

This is the cluster Rick called out by name. It addresses **F-1 (spawned-session degradation: fragmentation / transport-corruption / silent-stall)** + **F-3 (`dismiss_sessions` bug)** + the **auto-reap-on-completion** lesson Rick drove home 2026-05-31. Five decisions:

### D-A — Degradation detection: self-report vs structural enforcement
*Problem: a degrading session is sometimes the worst judge of its own degradation; the silent-stall (`6bd0a0a0`) never self-reported.*

| Option | Pros | Cons |
|---|---|---|
| **A1. Self-report only** (honest-stop; current) | Zero infra; worked 100% in Run-1 (every degraded worker stopped honorably + wrote a memento); low overhead | Trusts the degrading agent to self-assess; **cannot** catch a silent stall (a stalled session emits nothing to self-report) |
| **A2. Structural monitor** (external watcher detects degradation signals + forces relief) | Catches silent-stall + self-blind degradation; does not trust the degrading agent | Needs signal-detection logic; false positives could relieve a healthy-but-slow author |
| **A3. Hybrid** (self-report PRIMARY + lightweight structural backstop: zero-progress timer + spawn-probe) | Keeps the low-overhead thing that already worked; adds structure exactly where self-report is blind (stall + spawn) | Two mechanisms to maintain |

**My recommendation: A3 (hybrid).** Honest-stop caught every degradation that *could* self-report; don't throw out what worked. Add a structural backstop only for the one mode it can't see (silent stall) plus a spawn-time check (D-E). **Flip to A2** if honest-stop ever ships bad data downstream (it never has — the *gate* caught fabrications, but honest-stop kept them from even reaching the gate in most cases).

### D-B — Reaping cadence: when to reap a finished/idle author
*Problem: keeping 8 idle authors alive "in case" was the mistake Rick flagged 2026-05-31.*

| Option | Pros | Cons |
|---|---|---|
| **B1. Auto-reap on completion** (reap the instant a lane is done; never park idle) | No idle-session sprawl; frees persona slots immediately; fresh context outperforms a near-ceiling reused session on a NEW big lane | Loses warm context for a quick same-domain follow-up; re-spawn cost (~1–3s + persona alloc) |
| **B2. Keep-warm pool** (park finished authors for reuse) | Avoids re-spawn for quick follow-ups | Exactly the idle-sprawl Rick flagged; reusing a 300+-test session for a fresh 5000-LOC lane yields degraded/phantom tests |

**My recommendation: B1 (auto-reap on completion).** This is Rick's stated lesson, and the reasoning is sound: a session that's written 300+ tests is near its context ceiling — fresh genuinely outperforms on a new big lane. "Completion" = lane done AND no micro-follow-up already queued in the same context. **Flip toward a bounded B2** only if re-spawn latency ever becomes a measured bottleneck (it wasn't).

### D-C — Stall threshold: how long of zero-progress before relief
*Problem: `6bd0a0a0` sat stalled 55+ min before relief — far too long.*

| Option | Pros | Cons |
|---|---|---|
| **C1. 15-min ping → 30-min relieve** | Halves the wasted window vs what actually happened; still tolerant of a slow-but-working author | Risk of pinging during a legitimately long single op (an 11-min full-suite run) |
| **C2. 30-min ping → 55-min relieve** (≈ what happened) | Very tolerant | Burns ~1 hr of a dead session before acting — the exact failure observed |

**My recommendation: C1 (15/30), with known-long ops exempted from the timer.** Pair it with the heartbeat-poker liveness sweep (D-H) that already caught a 60-min idle author. **Flip looser** only if authors routinely run long single operations that the exemption list can't cover.

### D-D — `dismiss_sessions` bug: fix now vs document workaround
*Problem: the MCP tool stringifies the `session_names` list and iterates char-by-char → dismisses nothing; the tmux-kill workaround leaves stale dashboard entries and has a prefix-match hazard (`-1` matches `-10`).*

| Option | Pros | Cons |
|---|---|---|
| **D1. Fix the MCP tool now** (cosa-voice code change) | Reaping works cleanly via the intended path; no stale dashboard entries; removes the tmux prefix-match hazard; fixes a genuine correctness bug (tool silently no-ops) | A cosa-voice code change + redeploy (small effort); strictly it's MCP infra, adjacent to the campaign |
| **D2. Document the tmux-kill workaround** + defer the fix | Zero code change now | Every future campaign re-hits the hazard; stale "alive" dashboard entries keep confusing the operator |

**My recommendation: D1 (fix it).** Small, high-leverage: it's both an operational hazard *and* a silent correctness bug. Worth a standalone ticket regardless of the framework. **Flip to D2** only if cosa-voice is frozen for deploy reasons — in which case document the workaround loudly.

### D-E — Spawn-health read-reliability probe: hard gate vs soft warn
*Problem: Cheech's transport-corruption (phantom stdout lines, scrambled result blocks, misreported file existence) wasn't visible until mid-batch. This is María's DI-2 / spawn-probe.*

| Option | Pros | Cons |
|---|---|---|
| **E1. Hard gate** (fresh session double-reads a known file; on disagreement, reject + re-spawn; no work until it passes) | Catches transport-corruption **at spawn**, before any bad work; cheap (one double-read + checksum) | A transient flake could reject a healthy session (re-spawn cost); needs a canonical known-file |
| **E2. Soft warn** (probe + log, assign work anyway) | No false-reject | Lets corruption through — defeats the purpose |

**My recommendation: E1 (hard gate).** A re-spawn on a rare false-positive is far cheaper than a corrupted author's bad batch *plus* the gate cycles needed to catch it. Catching corruption before it produces work is strictly better than catching its output afterward. **Flip to E2** only if the false-reject rate proves high in practice.

---

## The rest of the failure modes (F-2, F-4, F-5, F-6)

### D-F — Canonical-interpreter trap (F-2): gate-zero preflight
*Problem: the lupin `.venv` (py3.13/pytest8.4) silently masked 166 reds; "5,471 collected, 0 errors" ≠ green.*

| Option | Pros | Cons |
|---|---|---|
| **F1. Hard scripted gate-zero** — verify (a) canonical interpreter (cosa `.venv` py3.11/pytest9), (b) GREEN baseline read *pass/fail* not just collection, (c) SDK/scipy tracer-warmup runner. No campaign starts until it passes. | Kills the single most dangerous illusion automatically; one script, run once per campaign | Small upfront scripting |
| **F2. Checklist-only** (manual preflight) | No code | Relies on a human remembering — the trap is precisely that it *looks* green |

**My recommendation: F1 (hard scripted gate-zero).** This trap cost us a false baseline; automate the illusion-killer. **Flip** never advisable — manual is how it bit us.

### D-G — Fleet-load server hang (F-4): coverage-run scoping
*Problem: commons broadcast flood + concurrent 11-min full-suite runs hung `:7999` twice; TTS was first casualty.*

| Option | Pros | Cons |
|---|---|---|
| **G1. Module/dir-scoped coverage only under fleet** (full-suite on explicit request) | Proven mitigation; keeps the shared dev server healthy | Authors must remember to scope (enforce in the runbook) |
| **G2. Cap concurrent authors at ~2** | Krishna is a single-reviewer bottleneck anyway; more authors just queue | Slightly slower fan-out |
| **G3. Unrestricted** (status quo) | Max parallelism | Hung `:7999` twice |

**My recommendation: G1 + G2 together** (both worked; they're complementary, not exclusive). **Flip off G2** if/when reviewer throughput stops being the bottleneck.

### D-H — Directed-push drops (F-5): delivery confirmation
*Problem: transient `register_network_error` silently dropped an author's assignment + sub-batch reports.*

| Option | Pros | Cons |
|---|---|---|
| **H1. Mandate verify `dm_dispatched:true` + re-send-if-missing + periodic `commons_who` liveness sweep** | Caught a 60-min idle author whose assignment never pushed; cheap | Manager must run the sweep on a cadence |
| **H2. Best-effort** (status quo) | Zero overhead | Silent drops → stalled authors look "assigned" |

**My recommendation: H1.** It already paid for itself once. Bake the sweep into the manager loop. **No sensible flip.**

### D-I — "Reds-cleared" ≠ "100%" conflation (F-6): two-bar state model
*Problem: treating "reds cleared (partial %)" as if it were "100% completion" over-credits progress.*

| Option | Pros | Cons |
|---|---|---|
| **I1. Framework models two distinct bars** — *repair bar* (reds cleared, partial % is the intended interim) vs *completion bar* (every reachable branch tested, pragma only on confirmed-unreachable + same-line reason) — never conflated | Accurate progress accounting; prevents a "looks done" that isn't | A slightly richer state model |
| **I2. Single bar** | Simpler | The conflation that misleads |

**My recommendation: I1.** It's a doctrine/labeling change, near-zero cost, high clarity. **No sensible flip.**

---

## Summary — the menu at a glance

| # | Decision | My pick | One-line why |
|---|---|---|---|
| D-A | Degradation detection | **A3 hybrid** | Keep honest-stop (worked); add backstop only where it's blind |
| D-B | Reaping cadence | **B1 auto-reap on completion** | Rick's lesson; fresh > near-ceiling reuse on big lanes |
| D-C | Stall threshold | **C1 15/30 + exempt long ops** | Halve the 55-min wasted window |
| D-D | `dismiss_sessions` bug | **D1 fix it** | Operational hazard + silent correctness bug |
| D-E | Spawn-health probe | **E1 hard gate** | Catch corruption at spawn, not mid-batch |
| D-F | Canonical-interpreter | **F1 scripted gate-zero** | Automate the illusion-killer (masked 166 reds) |
| D-G | Fleet-load hang | **G1 + G2** | Scoped runs + author cap; both proven |
| D-H | Push drops | **H1 confirm + sweep** | Already paid for itself |
| D-I | Two-bar model | **I1 distinct bars** | Near-zero cost, prevents false "done" |

**Two of these carry a code change:** D-D (fix `dismiss_sessions`) and D-E/D-F (a spawn-probe + gate-zero script). The rest are doctrine/runbook changes. None require GPU or external spend.

**Not for me to decide — flagged to Rick:** whether D-D's `dismiss_sessions` fix is in-scope for this framework effort or a separate cosa-voice ticket.
