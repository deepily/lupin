> Part 2 of 3 of the [Fleet Liveness & Unified Task-Store — Architecture (Top to Bottom)](../fleet-liveness-and-task-store-architecture.md): the three readers.

## 3. Reader 1 — the heartbeat self-poke (Stop-hook liveness path)

**Goal**: when a session tries to Stop while it still owes work, nudge it to keep going instead of going dark. Token-cheap: a **count**, never the list, and **nothing is injected into context** beyond "you owe N items."

**Where**: `src/lupin_cli/claude_code/hooks/` — `stop.py` (the Stop hook), with libs:
- `lib/heartbeat_settings.py`. Reads `~/.claude/settings.json` → `heartbeat` block (`enabled`, `poke_cap`, `count_inbound_questions_as_owed`, **`owed_source_from_store`**).
- `lib/heartbeat_work_owed.py` — pure `evaluate_work_owed(...)`: owns no source of truth. Computes `work_owed` from injected signals.
- `lib/task_store_client.py` — `query_owed(owner, statuses)`: bounded-timeout (≤1–2s), never-raises urllib seam to `:7999`.
- `lib/heartbeat_hold.py` / `.heartbeat-hold-<stable_session_id>.json`. A session's "I'm intentionally holding, don't poke me" record (TTL'd).

**The owed signal is a union of three inputs** (do not regress this — it was hard-won):
1. **owed_items**. Post-cutover, the `COUNT` from `query_owed` (the store) when `owed_source_from_store=True`. Pre-cutover, transcript replay (`replay_task_state`, retained as the degraded fallback).
2. **outstanding delegations** — local manifest/bridge files (a manager owes a review/reap).
3. **unanswered inbound** — local commons board (a worker owes a DM reply).

Inputs 2 and 3 are **local / store-independent** and must keep poking even during a `:7999` outage. Only the owed_items `COUNT` fails safe.

**The cutover flag**: `heartbeat.owed_source_from_store` in `~/.claude/settings.json`. `False` = old transcript path; `True` = store-count path. Flipping it fleet-wide is the cutover (every session's Stop hook reads it). **Reversible**: flip back to `False` to revert.

**Fail-safe**: when the store is unreachable, times out or answers malformed, `owed_items` contributes 0.
The hook logs a distinct `heartbeat_store_unreachable` phase and does **not** spurious-poke. Bounce-windows (Rick restarts `:7999` constantly under `--reload`) = no-poke windows, and the hook is written to stay quiet in them.

**Muting the poke** (two switches, either one mutes): `heartbeat.poke_output_enabled = false` in `~/.claude/settings.json` is the hand switch. The fleet switch is a small file an admin flips from a notification client's toolbar (multiplexer or legacy) through `PUT /api/heartbeat/poke-mute`. The Stop hook reads it on every stop through `hooks/lib/heartbeat_poke_mute.py`, so a flip lands on each seat's next stop with no restart. The file sits in the flow-ratio settings folder, which both rest containers already mount. A missing or malformed file reads as not muted, and no timer touches it. While muted, a seat is shown `heartbeat.poke_disabled_message` when that is set. And otherwise a line naming who muted it and when. `heartbeat.enabled` must stay `true` for either message to appear.

**Skeleton crew also mutes the poke.** `heartbeat_settings.load_heartbeat_settings` reads the key `cc session skeleton crew enabled` fresh from `src/conf/lupin-app.ini` on every stop. When it is on, the poke is muted whatever the other two switches say, and a manager's Stop text is the operator's single line. Turning it off adds no mute of its own, so a mute left in `settings.json` or the switch file still holds. A switch read that raises leaves the poke on. `GET /api/heartbeat/poke-mute` returns `source` as `file`, `skeleton_crew`, `both` or `none`. The arbiter's external manager pokes on `:8001` are not affected. Reference: `src/docs/rest-api-reference/06-files-websockets-pages-push.md`, section 25c.

> **Known limitation**: the self-poke *delivery/effect* path (Stop-hook `decision:block`) has not been confirmed to force a continuation turn. The **reliable** wake path today is the arbiter's external tmux-injection (below), plus a session-run `/loop`.

---

## 4. Reader 2 — the arbiter (`:8001`, out-of-band fleet watcher)

**What**: a standalone host process (not in Docker) that watches the whole fleet and pokes/escalates. It is the **second line** of liveness (the Stop-hook self-poke is the first).

**Where**:
- App: `src/lupin_arbiter_app/` (FastAPI on `:8001`, `--factory create_production_app`, `reload=False`).
- Logic: `src/cosa/agents/heartbeat_arbiter/`. `arbiter_job.py` (the loops), `fleet_data_model.py` (roster + stuck detection).
- Launch: `src/scripts/run-lupin-arbiter-app.sh`, supervised by the systemd **`--user`** unit `lupin-arbiter-app.service` (`Restart=always`).
  **Bounce to deploy new arbiter code**: `systemctl --user restart lupin-arbiter-app.service`.
  It loads the **working-tree** code, so no push is needed. Managers hold standing authority to bounce it after a green review. Verify via `journalctl --user -u lupin-arbiter-app.service`.
- Routing/recipients doc: `src/docs/agents/heartbeat-arbiter-routing-guide.md`.

**Liveness signals it consumes**: a manager is "alive" if any signal is fresh.
The signals are the heartbeat event stream (`~/.claude/heartbeat-events/*.jsonl`, the `work_owed` verdict the Stop hook emits) and `commons_who` last-post timestamps.
They also include **bridge-mtime**, which any tool call refreshes, and live bridge presence.

**Detectors & their windows** (each has actuated a real or false alarm — know the thresholds):

| Detector | Window | What it checks |
|---|---|---|
| **Manager-staleness** | 2700s (45 min) | No liveness signal from a manager → advisory to Rick |
| **Manager tap-ACK** | 600s (10 min) | Arbiter "taps" a manager; expects activity (bridge-mtime ≥ tapped_at) within the window → else MANAGER-DOWN |
| **Whole-fleet-stall** | 1800s (30 min) | No fleet *progress* (commits / task-store transitions) while work is owed → escalate to Rick |
| **Stuck worker** | episodes | `cap_reached + work_owed` repeated in the event stream |

**Single-source guarantee**: the arbiter's owed signal flows from the **same** store query as the poke, via the Stop hook's emitted `work_owed`. So the poke and the arbiter cannot diverge once the flag is flipped. The `cap_reached` *episode* counter stays on the heartbeat **event stream** (the store has no `cap_reached` concept).

**Delivery**: the arbiter can inject directly into a dormant session's tmux (`cc_notification_listener._inject_via_tmux`) — this is the reliable external wake. It also posts advisories to the human (`live_notify`).

**Outreach idempotency + ack channel**: the blocker detector re-pings a silent blocker on an escalating backoff.
The owning-manager *cc* ("X is blocking worker Y") is deduped on a `(blocker, blocked_item, recipient)` cooldown.
It reuses the advisory-cooldown machinery.
A persistent block therefore cc's the manager at most once per window.
A new block (different `blocked_item`) still announces once.
The arbiter is a **headless observer with no DM inbox**.
The canonical channel for a chase-ack back to the arbiter is a **commons `system-events` post**, not a DM reply.
Ratified: no inbound inbox is added to the observe-only service.

**Known gaps (follow-ups)**: the manager tap-ACK (600s) is tighter than any practical management loop.
Neither tap-ACK nor whole-fleet-stall is **blocked-on-user / done-aware**.
So an idle-but-finished or legitimately Rick-gated manager gets false MANAGER-DOWN or whole-fleet-stall escalations.
Mitigations in use: keep management loops under 40 minutes.
Represent user-gated work as a `gate_class=ricks_court` item transitioned to `blocked_by:[{kind:user}]`.

**The sibling-gate lesson** (Krishna 🦚: three fixes, one family).
Every arbiter false-positive class fixed then had the same signature: **a correctness gate wired into one consumer of a signal but not its siblings**.
The three fixes were these:

- The blocked-edge roster leg lacked the store-corroboration the ping leg had (`edge_is_store_backed`).
- The worker-subject stuck advisory lacked the bridge-fresh veto that the poke leg and the manager-subject advisory had.
- The stuck-episode recovery scan consumed caps on `honored` but not on the sibling `idle` beacon.

**Detection method** (use it to find the fourth, if one exists): don't reason about the code. Read the journal until the arbiter *contradicts itself on a single poll*.
Examples are `edges=1, pings_fired=0, taps_fired=1`, or `arbiter_stuck_bridge_veto` beside a "1 stuck/dead" tap for the same persona in the same poll.

**Rule for new gates**: when adding a correctness gate to a consumer of a fleet-view signal, enumerate that signal's other consumers.
Grep the producer's field name to find them.
Then either wire the gate uniformly or document per-consumer why not.

Recovery-outcome membership rule: a recovery outcome is a liveness beacon **the session itself emits**.
Arbiter-side markers never qualify (`fleet_data_model.py`, `RECOVERY_OUTCOMES`).

---

## 5. Reader 3 — the human UI card

A **task-list card** in the multiplexer / cosa-voice UI, rendered from the store.
The human (Rick) tracks his *own* court and the fleet's owed work on it.
It has full fidelity (`blocked`, `blocked_by`, `next_chase_ts`, owner, accountable) that the native widget never had.

**Implementation pattern** (Tiberius's lane): clone the **fleet-status card** pattern.
The parts are `FleetStatusStore` (poll-driven, in-flight debounce), a renderer, a table template and `FleetApiClient` (handles JWT/401).
They become a `TaskListStore` and a renderer. 
**Data path**: back it onto the **existing** `GET /api/tasks?owner_persona=&status=`.
`/api/arbiter/fleet-state` is the wrong source: it is a fleet-composite proxy of the wrong shape.
The card is a read-only consumer.
A TypeScript variant is banked for cutover, and a JS-client variant landed in the in-service notifications client.

---
