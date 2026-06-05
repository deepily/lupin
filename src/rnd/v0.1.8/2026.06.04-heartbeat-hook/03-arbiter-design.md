# Heartbeat Arbiter — v2 Design

**Status:** ✅ **MANAGER-APPROVED (Tiberius, 2026-06-04), UNCOMMITTED pending Rick's commit word.** All design decisions closed — §6.2 idle-detection RULED **Option C / HYBRID** (Rick, 2026-06-04). Four review nits (N1–N4) folded.
**Author:** María 🌸 (PIP session `4347c712`, design author + arbiter owner). Implementers-in-waiting: Tiffany 💍 + Rachel 🕊️. Manager: Tiberius 👑.
**Design authority:** canonical local-Hook design + emission schema + Q4 ruling — planning-is-prompting `src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md` §0 / §0.2 / §0.3.
**Siblings:** `01-spike-findings-and-stop-py-seam-analysis.md` · `02-stop-py-seam-factoring-proposal.md` · (Rachel) `04-v2-oracle-livefetch-plan.md`.
**Cross-ref (existing Poker family):** `lupin/src/rnd/v0.1.7/2026.05.20-generic-heartbeat-poker-abstraction-design.md` + the D1–D4 spec series.

---

## 1. Purpose & scope

The **Heartbeat Hook** (v1, shipped) is a *per-instance, local* `Stop`-hook that self-pokes on quiescence-with-work-owed and emits a fire-and-forget poke-outcome record. The **Heartbeat Arbiter** (v2, this doc) is the *managed-fleet* consumer of that exhaust: it reads every session's emitted records, builds a cross-fleet view, and drives three fleet behaviors — **auto-ping-the-blocker**, **idle-roster surfacing**, and **dependency-graph analysis** — while the **manager actuates** reassignment.

**Invariant inherited from the Hook (§0 #2):** the local poke is autonomous and `:7999`-free; the arbiter is an **additive observer of the Hook's exhaust, never a dependency in the poke path.** If the arbiter is down, every local Hook still pokes normally.

## 2. Home / identity (point 6)

Realize the arbiter by **extending the existing agentic Heartbeat Poker** (`HeartbeatPokerJob` / `cascade_heartbeat_scheduler`) — reuse its poll loop + commons-DM delivery rather than building a new daemon. The Hook=per-instance vs Poker=managed-fleet split already exists; this gives the Poker its sensory input (the event stream) and its analysis layer.

## 3. Input — consumer of the Hook's exhaust (point 1)

- **Source:** glob `~/.claude/heartbeat-events/*.jsonl` (the fleet-wide emit dir, canonical §0.2). One file per session; the arbiter is a **pure consumer — zero Hook retrofit** (the whole point of emit-now).
- **Tailing:** track a per-file read offset (or last-seen `ts`); on each poll, read only new lines. Resilient to malformed lines (skip, per `read_events`).
- **Record fields consumed** (schema_version 1): `session_id` · `persona` · `ts` · `outcome` (**poke / honored / cap_reached / idle** — `idle` = the v2 genuine-idle beacon) · `poke_count` · `cap` · `work_owed` (real bool once v2 oracle wires; null pre-v2) · `awaiting` · `reason`.

## 4. Data model — the fleet spine

Per-session view, rebuilt each poll from events + `commons_who`:

| Field | Source | Meaning |
|---|---|---|
| `liveness` | **event-file `ts` = PRIMARY**, `commons_who` = SECONDARY | recent ⇒ alive. Event-file ts is `:7999`-free (local read), so liveness/inference **degrades gracefully when `:7999` saturates** (our wedge history); `commons_who` only enriches it, never gates it. |
| `state` | last `outcome` | `poke`=nudged/working · `honored`=holding · `cap_reached`=stuck |
| `holding_on` | `awaiting` edge | `peer:X` / `user:Y` / `commons:Z` / `none` |
| `stuck` | repeated `cap_reached` + `work_owed=true` | poked to the cap, still owed ⇒ needs help |
| `poke_pressure` | `poke_count` vs `cap` | proximity to the cap |

**Dependency graph** — assembled from all `awaiting: peer:*` edges (who-waits-on-whom):
- **Cycle detection** = deadlock (A→B→A) ⇒ escalate to the user (no autonomous break).
- **`awaiting: user:<offline>`** = the AFK `owner_id` case ⇒ feeds the owner-pre-resolution / fleet keep-alive line (the original Poker arbiter concern).

## 5. Work-owed source / Q4 — RESOLVED (ref canonical §0.3)

The arbiter does **not** compute work-owed; the **local Hook v2** does, and stamps `work_owed` into each emitted record. Q4 ruling (canonical §0.3, summarized): the local oracle's source = **the session's OWN `Task*` state, replayed from its `transcript_path`** (`Stop`-hook input) — `TaskCreate` + `TaskUpdate` replayed by `taskId` → `work_owed = any task whose latest status ∈ {in_progress, pending}`. `owned_by_me` **TRUE BY CONSTRUCTION** (the calls live in that session's transcript — no cross-session attribution); **`:7999`-free** (local file read); built on the **same transcript-reader Rachel's token-rate instrumentation needs** (build once, fan out). **(Source re-targeted `TodoWrite`→`Task*` after Rachel's §0.3-mandated spike found `TodoWrite` is a dead signal — zero calls / not in this harness's registry; see canonical §0.3 correction.)** v2 scope = `Task*` only; project-`TODO.md` Pending-Decisions (no ownership) + inbound-`expect_reply`-DM (keep `:7999`-free) deferred to v2.1. Net effect for the arbiter: `work_owed` becomes a **real bool** in the event stream (was null in v1), enabling true `stuck` detection.

## 6. Behaviors

### 6.1 Auto-ping-the-blocker (point 4 — Rick condition 2)
For each session holding on `awaiting: peer:X`, the arbiter DMs X: *"Session ⟨persona⟩ is holding on you for: ⟨reason⟩ — where are we?"*
- **Throttle:** at most one ping per `(holder, X, reason)` edge per backoff window — never re-ping every poll (no storm; Sam-TTS lesson).
- **Resolution:** when the holder's next event drops the `awaiting:peer:X` edge (resumed or re-held elsewhere), clear the edge.
- **Escalation:** if X is offline / unresponsive past a threshold, surface to the manager (X may be a phantom or genuinely stuck).

### 6.2 Idle-roster (point 2 — Rick condition 3) — ✅ RULED: Option C, HYBRID (Rick, 2026-06-04)
Assemble the fleet-wide list of **idle / nothing-owed** sessions → manager-visible (for manager-actuated reassignment, §6.3). Detection uses **BOTH** signals:
- **INFERENCE (broad net):** idle ≈ alive (by **event-file `ts` PRIMARY**, `commons_who` secondary — N3) **AND** quiet (no heartbeat events + no commons activity) past a threshold. Catches every quiet session, including those that never emit a beacon. Heuristic ("quiet" can mean a long tool-run).
- **DECLARATION (authoritative beacon):** the arbiter consumes an explicit **genuine-idle** emission the Hook fires on `not_owed` + **empty `Task*` set** (the cascade below). A session that emits this is *authoritatively* available. **STICKY-until-superseded (N4):** because the emit is edge-triggered, treat the latest `idle` beacon as the session's standing state **until a later event supersedes it** (`poke`/`honored`/`cap_reached` ⇒ back to work). An arbiter restart / offset-reset can miss the original transition edge — **inference backstops that gap** (a session sitting idle still reads quiet), so the two signals together never strand a genuinely-idle session off the roster.
- **TRUST LABELING (Rick's mandate):** each roster entry is labeled **`quiet (inferred)`** vs **`declared-available`** so the **manager can weight trust** before reassigning — a declared-available session is a safer reassignment target than an inferred-quiet one (which might just be mid-long-run).
- **Roster output:** post to a `fleet-idle-roster` commons topic + DM the manager on roster change; entries carry the trust label + last-activity ts.

**Cascade to the Hook (v2 additive emit):** the current emit fires on `{poke, honored, cap_reached}`; **ADD a `idle` emission on `not_owed` + empty-`Task*` set** so the declared-available beacon exists for the arbiter to upgrade on. Small additive `emit_outcome` extension (Rachel/Tiffany lane; same fire-and-forget invariant; 100%-tested). **Constraint (María):** emit the `idle` beacon **edge-triggered / de-duped** — fire on the *transition* into idle (last emitted event for the session was not already `idle`), NOT on every idle stop, so a no-tasks session doesn't spam an `idle` line per turn. Canonical schema update in PIP §0.2.

### 6.3 Reassignment (point 3) — DECIDED: sensor + recommender; manager actuates
The arbiter is a **sensor + recommender, NOT an actuator.** It surfaces the idle-roster (§6.2) + the blocked dependency-graph (§4) to the **manager**, who **actuates** reassignment (pulls an idle worker, assigns work) under the standing spawn/harvest authority. Rationale: Rick's explicit framing (*"you Tiberius have the list and assign them something"*), lower blast-radius (auto-assigning work is high-risk), and it fits the manager-autonomy grant (`feedback_manager_standing_spawn_authority`). The arbiter MAY *recommend* a pairing (idle worker ↔ queued work) but never assigns autonomously.

### 6.4 Dependency-graph analyses (bonus)
Cycle=deadlock→escalate user; `awaiting:user-offline`=AFK owner_id keep-alive; longest-wait-edge surfaced first to the manager.

## 7. Safety — bounded by construction
- **Fleet-wide ping/poke throttle** (Wave-3 prereq B): a global rate cap across all arbiter-originated DMs; per-edge backoff (§6.1).
- **No-storm invariant** (Sam-TTS postmortem): every arbiter-originated message is rate-bounded; a backlog never replays unbounded.
- **Read-only on the Hook's plane:** the arbiter never writes the event logs; it only reads. It cannot corrupt a session's local state.
- **Degrades safe:** arbiter down ⇒ local Hooks unaffected (§1 invariant).

## 8. Build plan (on Rick's nod → implementers)
1. **Shared transcript-reader** (with Rachel's token-rate line, TODO 11) — build ONCE; fan out to (a) token-rate, (b) the Hook-v2 work-owed oracle feed (§5). *Pre-build spike: DONE (Rachel) — caught the `TodoWrite`→`Task*` correction; reader replays `TaskCreate`/`TaskUpdate` by `taskId`.*
2. **Hook v2 wire** (**Rachel** — the `stop.py` Branch-C adapter / call-site is her lane per the ratified v1 split; Tiffany owns the pure leaves): thin Branch-C adapter passes a REAL `oracle_verdict` (`Task*`-replay-fed `evaluate_work_owed`) instead of `None`. Oracle + `decide_heartbeat` already built/tested — last wire.
2b. **Genuine-idle emit** (Rachel/Tiffany lane): additive `emit_outcome` extension — fire an `idle` event on `not_owed` + empty-`Task*` set, **edge-triggered/de-duped** (§6.2 constraint). Same fire-and-forget invariant; 100%-tested; canonical schema in PIP §0.2.
3. **Arbiter consumer** (extends `HeartbeatPokerJob`): event-glob+tail (§3) → fleet data model (§4) → §6.1 auto-ping + §6.4 graph. 100% tested against synthetic event logs.
4. **Idle-roster** (§6.2) — HYBRID per Rick: inference (`commons_who` + event-quiet) UNION the declared `idle` beacon; each entry trust-labeled `quiet (inferred)` vs `declared-available`.
5. **Manager surface** (§6.3): roster + blocked-graph → manager DM / commons topic.

## 9. Open questions / deferred
- ✅ **§6.2 idle-detection source** — RULED **Option C / HYBRID** (Rick, 2026-06-04): inference + declared beacon + trust labels. No longer open.
- **Cross-host fleet** — `~/.claude/heartbeat-events/` is per-host; a multi-host fleet needs a shared/synced dir or a per-host arbiter. (v2 assumes single-host.)
- **v2.1 work-owed signals** — project-`TODO.md` Pending-Decisions (needs per-session ownership) + inbound-`expect_reply`-DM (file-based commons read, `:7999`-free).
- **Poll cadence + offset persistence** — tune against fleet size; persist offsets across arbiter restarts.

---

*Authored 2026-06-04 by María (design author), on Tiberius's approved shape. UNCOMMITTED pending Rick's nod; §6.2 finalizes on his idle-detection ruling.*
