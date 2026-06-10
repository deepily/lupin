# Fleet-Status — PID-liveness "offline" override (kill-0 fast-death detection)

**Date**: 2026-06-09
**Author**: Rio ⚡ (session 110ff47d)
**Status**: ✅ BUILT (Option A) — 170 unit tests green, 100% L/B on changed surface, HELD (no push). Needs an :8001 restart to land. See §11 As-built.
**Related**: [`01-design.md`](01-design.md) (the table) · [`02-context-window-columns.md`](02-context-window-columns.md) · context-pressure liveness `../2026.06.07-managing-context-memory/` · arbiter liveness union `../2026.06.04-heartbeat-hook/2026.06.08-arbiter-consumption-gap-and-operator-loop.md`

---

## 1. Problem

When a worker session ends — Rick types `/exit`, closes the terminal, or the process is killed — the **fleet-status table keeps showing it for up to an hour**.

Root cause: the table verdict (`fleet_render.compute_liveness` / `_verdict`) is **purely staleness-based**. It rides the *freshest of four signal ages* (bridge mtime · stop-event · commons · idle-prompt) and explicitly does **not** consult the OS process (`compute_liveness` docstring: *"state is NOT consulted here"*). So a dead session simply ages out:

| freshest age | verdict |
|---|---|
| ≤ 60s | LIVE |
| ≤ 600s (10m) | quiet |
| ≤ 3600s (1h) | stale |
| > 3600s | **offline** (then hidden by the default live-only view) |

**The information already exists, one section over.** The context-pressure path (`context_pressure.assess_liveness` / `_pid_alive`) already does `os.kill(pid, 0)` on **both** the worker's `listener_pid` AND `cc_pid` and returns `DEAD` when both are gone — within one arbiter poll (~60s). But that `DEAD` verdict lives in the context-pressure section's `liveness` field and is **never plumbed into the fleet table's verdict column**.

A `/exit` kills both PIDs (the SessionEnd hook SIGTERMs the listener; the CC process exits). So a cheap `kill -0` would let the table drop the session in ~60s instead of ~3600s.

## 2. Goal / non-goals

**Goal**: when a session's OS process is **confirmed dead** (both PIDs fail `kill -0`), force its fleet-status verdict to `offline` immediately, so it leaves the default table within one poll cycle (~60s) instead of waiting out the 1-hour staleness window.

**Non-goals / explicit guardrails**:
- **Bias-to-alive.** NEVER force offline on *absence* of data (unreadable bridge, missing PID field, Docker namespace). Only a **positive both-PIDs-dead reading** triggers the override. This preserves the lesson of the "false WHOLE-FLEET-STALL" bug — over-eager offline-marking is the failure mode we must not reintroduce.
- **Staleness stays as the backstop.** Hard kills where the bridge can't be read, or where host PIDs aren't visible, still age out via the existing path. The override is *additive acceleration*, never a replacement.
- **Decision logic untouched.** The arbiter's routing/stall-detection reads `fleet_view`, not the published snapshot — this change only affects the published snapshot's verdict, exactly like the §5.2 prune.

## 3. The host-PID-trust constraint (SAFETY-CRITICAL)

`os.kill(pid, 0)` is only meaningful if the arbiter process shares a PID namespace with the worker. The worker PIDs are **host** PIDs (pinned at spawn). `session_bridge` already exposes **`_can_trust_host_pids()`** (the Docker-detection guard the context-pressure path uses).

**Rule**: the PID-liveness override applies **only when `_can_trust_host_pids()` is True**. Inside a container that can't see host PIDs, the override is a no-op and the table falls back to staleness (today's behavior). This must be a first-class gate, not an afterthought — a container would otherwise read EVERY host PID as dead and wrongly offline the whole fleet (the exact catastrophe in §2).

> **Verify at implementation time**: confirm where `lupin-arbiter-app` (:8001) actually runs (host vs container) and that `_can_trust_host_pids()` returns True there. The context-pressure PID check already runs in this same process, so if context-pressure liveness is trustworthy today, this override is too — same guard, same process.

## 4. Design

### 4.1 New injected seam on `build_snapshot` (mirrors the existing pattern)

`build_snapshot` already takes optional `resolve_manager_fn=None` / `list_managers_fn=None` seams (default None → back-compat + pure testability). Add a third in the same shape:

```python
def build_snapshot( fleet_view, bridge_mtimes, now,
                    live_seconds       = DEFAULT_LIVE_SECONDS,
                    quiet_seconds      = DEFAULT_QUIET_SECONDS,
                    stale_seconds      = DEFAULT_STALE_SECONDS,
                    resolve_manager_fn = None,
                    list_managers_fn   = None,
                    process_dead_fn    = None,      # NEW seam: () -> { session_id: True }  (dead-only map)
                    include_offline    = False ):
```

- `process_dead_fn()` returns a map of **confirmed-dead** session-ids → `True`. **Only dead sessions appear** in the map (a sparse allow-list of deaths) — absence means "unknown / alive / can't-tell", never "dead". This shape makes bias-to-alive structural: a missing key can't force offline.
- Resolve once at the top, degrade-safe (same `try/except → {}` idiom as `list_managers_fn`):
  ```python
  process_dead = {}
  if process_dead_fn is not None:
      try:    process_dead = process_dead_fn() or {}
      except Exception:    process_dead = {}
  ```

### 4.2 Override point — in `build_snapshot`, NOT `compute_liveness`

`compute_liveness` documents a hard contract: four ages, orthogonal, *state not consulted* (C4). Keep it pure. Apply the override in `build_snapshot` AFTER computing the age-based liveness block:

```python
liveness = compute_liveness( view, (bridge_mtimes or {}).get(sid), now, live_seconds, quiet_seconds, stale_seconds )

# PID fast-death override: a CONFIRMED-dead process forces offline immediately,
# regardless of how recent its last signal was (bias-to-alive: only a positive
# dead reading overrides; absence falls through to the age verdict).
if _lookup_dead( process_dead, sid ):
    liveness[ "process_dead" ] = True          # transparency: surfaces in the tooltip
    liveness[ "verdict" ]      = "offline"

if not include_offline and liveness.get( "verdict" ) == "offline":
    continue
```

- `liveness["process_dead"] = True` is an **additive** field — lets the frontend tooltip distinguish "process gone" from "merely stale" without changing the verdict string.
- The existing §5.2 prune (`verdict == "offline" → continue`) then drops it from the published snapshot on the very next poll. **Zero frontend change required** (the `_splitFleetByLiveness` `verdict === "offline"` match still fires).

### 4.3 Prefix-tolerant session-id lookup (GOTCHA)

`fleet_view` keys are often short 8-char ids; bridge session-ids are full uuids. `build_snapshot` already carries `_sid_matches(a, b)` (prefix-tolerant) for the manager set. The dead-map lookup MUST reuse it — a plain `process_dead.get(sid)` would under-match:

```python
def _lookup_dead( process_dead, sid ):
    return any( _sid_matches( sid, dead_sid ) for dead_sid in process_dead )
```

(Whoever builds the map should prefer keying by the SAME id form `fleet_view` uses, to keep the match cheap; prefix-tolerance is the safety net.)

### 4.4 Building the dead-map at the caller (`arbiter_job._publish_fleet_snapshot`)

The caller already builds `bridge_mtimes = { sid: self._bridge_mtime_fn(sid) for sid in fleet_view }`. Add a parallel dead-map, gated on host-PID trust, reusing the existing context-pressure PID helpers (`_pid_alive`, and the bridge-read pattern from `assess_fleet_context_pressure`):

```python
snapshot = build_snapshot(
    fleet_view, bridge_mtimes, now,
    resolve_manager_fn = self._resolve_manager_fn,
    list_managers_fn   = _default_list_manager_session_ids,
    process_dead_fn    = self._process_dead_fn,    # injected seam (default → {} when host PIDs untrusted)
)
```

`self._process_dead_fn` (default impl, injected like the others):
1. If `not session_bridge._can_trust_host_pids()` → return `{}` (no-op; staleness backstops). **The whole feature short-circuits here in a container.**
2. Else, for each active bridge (reuse `find_active_voice_persona_sessions()` — the same walk context-pressure uses), read `listener_pid` + `cc_pid`; if `not (_pid_alive(listener_pid) or _pid_alive(cc_pid))` → add that `session_id` to the dead-map.
3. Return `{ session_id: True, ... }` (dead-only).

Recommended: extract a small shared helper (e.g. `context_pressure.fleet_dead_sessions(now) -> set[str]`) so the PID-read logic lives in ONE place and both the context-pressure section and this override consume it (no duplicated bridge-read loop — one-name rule).

## 5. Behavior after the change

| Event | Today | After |
|---|---|---|
| `/exit` (SessionEnd fires, both PIDs die) | table shows LIVE→quiet→stale→offline over ~1h | **offline within ~60s** (next poll), then hidden |
| terminal closed / SIGKILL (no hook) | ~1h staleness | **~60s** if bridge still readable + host PIDs trusted; else ~1h backstop |
| arbiter in a container (host PIDs invisible) | ~1h staleness | unchanged ~1h (override is a guarded no-op) |
| live session, momentarily quiet | stays visible (age < 1h) | unchanged — alive PID never enters the dead-map |
| bridge unreadable for a live worker | stays visible | unchanged — absence ≠ dead (bias-to-alive) |

## 6. Acceptance criteria

- **AC1** `build_snapshot` gains `process_dead_fn=None`; with it None/absent, output is byte-identical to today (back-compat).
- **AC2** A session whose id is in the dead-map gets `verdict="offline"` + `liveness.process_dead=True`, **even when its freshest age is well under the LIVE threshold** (e.g. 5s).
- **AC3** A session NOT in the dead-map keeps its age-based verdict unchanged.
- **AC4** A throwing/None `process_dead_fn` degrades to no override (no exception; age verdict stands).
- **AC5** Dead-map lookup is prefix-tolerant (short-id `fleet_view` key matches full-uuid dead entry, and vice-versa).
- **AC6** The default dead-map builder returns `{}` when `_can_trust_host_pids()` is False (container safety) — proven by test with the guard faked both ways.
- **AC7** PID-read logic is not duplicated — one shared helper feeds both the context-pressure section and this override.
- **AC8** 100% lines/branches/functions on every changed file (Python `--cov-fail-under=100`).
- **AC9** No frontend change required; the existing `_splitFleetByLiveness` offline-hide still works. (Optional, separately scoped: a tooltip badge reading "process dead" off the new `process_dead` flag.)

## 7. Test plan (all :7999-eligible — pure unit, no state mutation)

`src/tests/unit/test_fleet_render.py` (extend `TestBuildSnapshot`):
- override forces offline despite a fresh age (AC2)
- non-dead session unaffected (AC3)
- None / throwing `process_dead_fn` → no override (AC1, AC4)
- prefix-tolerant match both directions (AC5)
- `process_dead` flag present on the overridden row's liveness block

`src/tests/unit/test_context_pressure.py` (or arbiter_job tests) for the default dead-map builder:
- `_can_trust_host_pids()` False → `{}` (AC6)
- both PIDs dead → session in map; either alive → not in map
- unreadable bridge → not in map (bias-to-alive)
- shared-helper single-source (AC7)

## 8. Blast radius

- **Files**: `fleet_render.py` (seam + override), `arbiter_job.py` (inject default seam), `context_pressure.py` (extract/expose shared dead-session helper), tests. **No frontend, no INI, no DB.**
- **Deploy**: backend — requires an **:8001 arbiter restart** to land (unlike the §5.1/§5.2 frontend work). Rick's deploy gate.
- **Back-compat**: seam defaults None → existing callers/tests unaffected.

## 9. OPEN DECISION for Rick — verdict label

When a process is confirmed dead, what should the table show?

- **Option A (RECOMMENDED): force `"offline"`.** Zero frontend change; dead sessions hide on next poll exactly like aged-out ones. Distinction available via the additive `process_dead` flag (tooltip) if ever wanted. Smallest blast radius, ships fastest.
- **Option B: a distinct `"dead"` verdict.** Visually separates "process gone, never coming back" from "stale, might resume." BUT requires touching the frontend `_splitFleetByLiveness` (`verdict === "offline"` → also treat `"dead"` as offline-equivalent) + the offline-toggle count + tests. More signal, more surface.

**Recommendation: A** — it delivers the ~60s win Rick asked for with the least risk; B can be a fast follow if the visual distinction proves valuable.

## 10. Out of scope (named, not silently dropped)

- A tooltip/badge rendering the new `process_dead` flag (frontend; optional polish).
- Eager bridge-file deletion on death (today: pruned to `voice_persona=null` / aged out at 12h TTL) — orthogonal lifecycle concern.
- Making the staleness thresholds INI-configurable (they're render-layer constants today).

## 11. As-built (Option A, 2026-06-09) — three deviations from the §4 sketch

Rick chose **Option A** (force `"offline"`, no new verdict). Built with three refinements vs the original sketch:

1. **`process_dead` is a DATA arg, not a `process_dead_fn` seam.** `build_snapshot( …, process_dead=None )` takes an iterable of confirmed-dead session-ids (parallel to `bridge_mtimes`, which is also caller-built data). Keeps `build_snapshot` 100% pure with no fn-call indirection. `_lookup_dead( process_dead, sid )` does the prefix-tolerant membership test via `_sid_matches`.

2. **The dead-scan lives in `session_bridge.find_dead_sessions`, NOT `context_pressure`.** Discovery during build: **every existing bridge-locator (`find_session_path_by_id`, `find_active_voice_persona_sessions`) SKIPS dead-PID bridges host-side** — so none of them can ever *surface* a dead session. `find_dead_sessions` is therefore a NEW **unfiltered** scan of `~/.claude/sessions/cc-*.json` that positively confirms death. It belongs in `session_bridge` (which owns `SESSION_DIR` + the PID primitives), not in `context_pressure`. `arbiter_job._default_dead_session_ids( fleet_view )` wraps it degrade-safe and is passed at the `_publish_fleet_snapshot` call site.

3. **A stricter `_pid_confirmed_dead` (bias-to-alive) replaces reuse of `_is_pid_alive`.** `_is_pid_alive` treats `PermissionError` (EPERM, exists-but-not-ours) as **dead** — wrong for a force-offline decision. `_pid_confirmed_dead` confirms death **only** on `ProcessLookupError`; EPERM / other OSError / non-int all count as alive. A session is dead iff it has ≥1 known int pid (filename pid ∪ `listener_pid` ∪ `cc_pid`) AND **all** of them are `_pid_confirmed_dead`.

**Guardrails as shipped:** host-PID-trust gate (`_can_trust_host_pids()` → empty set in a container) ✓; bias-to-alive (no bridge / no pid / any-alive / any-error → not dead) ✓; verdict string set unchanged (frontend untouched) ✓; additive `liveness.process_dead=True` for a future tooltip ✓.

**Files**: `session_bridge.py` (`_pid_confirmed_dead` + `find_dead_sessions`), `fleet_render.py` (`_lookup_dead` + `build_snapshot` `process_dead` override), `arbiter_job.py` (`_default_dead_session_ids` + call-site), + unit tests in `test_session_bridge_lookup.py`, `test_fleet_render.py`, `test_heartbeat_arbiter_job.py`.

**Tests**: 170 green across the three suites (+15 new). 100% lines/branches on the changed surface of all three source files (verified via `--cov-branch` JSON).

**Deploy**: backend — **:8001 arbiter restart** required to land (Rick's gate). Held, not pushed.
