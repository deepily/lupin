# Arbiter v2.1 — Direct-State Visibility — Implementation Log (Clayton 😎)

**Status:** ✅ All 3 build-lanes GREEN at the implementer (unit) tier — 100% line+branch+function on every owned module. **NO commits** (manager/Rick gate). Built commit-READY.
**Review outcome (2026-06-06):** Krishna 🦚 **APPROVE, no blocking findings**. Anchor A ruled WITH the broad `except Exception` (the middleware stamps BEFORE `call_next` → total-no-throw is structurally required; the single observable swallow-point beats an unobservable middleware-boundary guard — DO NOT narrow to OSError). **N2 (done):** coupling-contract comment added at the middleware stamp site. **N1 (logged follow-up, not now):** expose `get_bridge_touch_failure_count()` via `/api/queue/pool-status`. Mr-Radio 🦉: one regression `test_no_poke_falls_through_to_idle` (stop.py) traced to the HELD 2026-06-05 heartbeat-strip change (Thread A, parked on Rick's flag-vs-skip) — **NOT v2.1**; zero action here.
**Author:** Clayton 😎 (Implementer, SWE-Team inaugural run; was Rachel → re-requested Clayton per Rick's broadcast).
**Spec:** `03-arbiter-design.md` §10 (+ PIP source `planning-is-prompting/src/rnd/2026.06.05-arbiter-direct-state-visibility.md`). Redlines C1–C4 (§10.6 / §6.2).
**Manager:** Tiberius 👑 · **Steward:** María 🌸 · **Reviewer (pending):** Krishna 🦚 · **Tester (pending):** Mr-Radio 🦉.

---

## What was built (3 lanes + 1 shared primitive)

### Lane 0 — shared bridge-mtime primitive (the ONE host-side clock, C4)
`src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (additive):
- `touch_bridge_mtime()` — bare `os.utime(path, None)` on the resolved `cc-{ppid}.json`. Metadata-only, **no content write** (JSON-corruption gate, C1). Resolves via `_find_session_file()` (one `.exists()` stat in the PPID-hit case). **Fail-safe `except Exception`** (§10.6 "no-op on any error") + observability rider: a monotonic `_bridge_touch_failure_count` (long-lived processes) + a one-shot-per-process stderr line (the ephemeral hook). `get_bridge_touch_failure_count()` exposes the counter.
- `get_bridge_mtime(session_id)` — arbiter-side reader: `find_session_path_by_id(...).stat().st_mtime`; broad-catch → None.

### Lane SERVER — per-MCP-call stamp (C2/C4)
- `src/lupin_mcp/bridge_liveness_middleware.py` (NEW) — `BridgeLivenessMiddleware(Middleware).on_call_tool` calls `touch_bridge_mtime()` then `await call_next(context)`. Stamp-before-tool, never short-circuits, returns result unchanged. Reuses the one clock (C4).
- `src/lupin_mcp/cosa_voice_mcp.py` — 2 lines: import + `mcp.add_middleware(BridgeLivenessMiddleware())`. (Long-running per-session subprocess → editing in-tree only affects newly-started servers; not per-call re-exec like the hook.)

### Lane TOOL-HOOK — single PostToolUse stamp (C1/C3) — delivered as a PATCH
Built in an **isolated git worktree** (`/tmp/clayton-toolhook-wt`, branch `clayton-toolhook-dev`) per Tiberius's Option-a lock — the **live main-tree `post_tool_use.py` was byte-untouched**, zero fleet voice-drain disruption, zero settings.json change.
- `post_tool_use.py`: import `touch_bridge_mtime` + ONE `touch_bridge_mtime()` call right after payload-validation, before tool-name extraction → every non-empty tool call stamps. Single PostToolUse only (C3). No guard (the primitive is the proven no-throw boundary — would be a dead branch). Bootstrap `sys.path.insert` got a justified `# pragma: no cover` (bootstrap-exception per PATH MANAGEMENT mandate — genuinely unreachable under pytest).
- **Deliverable:** `clayton-toolhook-lane.patch` (2 files: hook + its test) — `git apply --check` CLEAN against main tree. Manager applies at commit time on Rick's word. Live-observable: the call is the REAL un-mocked `os.utime` (Mr-Radio asserts mtime-delta + byte-identical content on the live path).

### Lane RENDER/SNAPSHOT — arbiter render + queryable endpoint (C2/C4)
- `src/cosa/agents/heartbeat_arbiter/fleet_render.py` (NEW, pure) — `compute_liveness` (ages off bridge PRIMARY + event, + verdict label), `build_snapshot` (STATE and LIVENESS as **orthogonal keys**, C4), `frame_signature` (over SEMANTIC fields + verdict *bucket* only → ticking ages are NOT a change), `render_fleet_table` (full table, separate columns), `render_tick` (one-line, duration-since-change per Rick's D1 proviso).
- `src/cosa/rest/arbiter_snapshot_store.py` (NEW) — thread-safe singleton (set/get/clear); the in-pool arbiter updates it directly; mirrors `pool-status` backing.
- `src/cosa/rest/routers/arbiter.py` (NEW) — `GET /api/arbiter/fleet-snapshot` (read cache; explicit `awaiting` placeholder pre-first-push) + `POST /api/arbiter/fleet-snapshot` (standalone-arbiter push). **Credential (C2): `require_api_key_or_jwt`** (X-API-Key OR Bearer JWT). POST body Pydantic-validated (`FleetSnapshotIn`, `session_count` ge=0). NO standalone arbiter HTTP server (C2).
- `src/fastapi_app/main.py` — 2 lines: import + `app.include_router(arbiter.router)`.
- `src/cosa/agents/heartbeat_arbiter/arbiter_job.py` — wired `_publish_fleet_snapshot` into `_poll_once`: reads bridge mtimes per session, builds the snapshot, renders change-or-tick to the (injectable) render sink, pushes to the (injectable) snapshot sink. 3 new injectable seams (`bridge_mtime_fn` / `snapshot_sink` / `render_sink`), all defaulting to the canonical impls.

## Redline compliance
- **C1** (bare metadata touch, no write/transcript/POST/heavy logic): hook call is one `os.utime` via the shared primitive; byte-identical-content unit test proves no write.
- **C2** (named push endpoint + credential): `POST /api/arbiter/fleet-snapshot`, `require_api_key_or_jwt`. No standalone HTTP server.
- **C3** (single PostToolUse hook): stamp added to PostToolUse only; PreToolUse untouched.
- **C4** (converge on bridge-mtime; state ≠ liveness): one `touch_bridge_mtime` clock written by hook + server middleware (+ existing idle-waiter/Stop); snapshot keeps `state` and `liveness` as separate keys.

## Krishna-earmark pre-resolutions (Tiberius's two items + María's gate)
1. **Dropped hook try/except** → primitive hardened to `except Exception` with **fault-injection proof**: missing bridge dir, EPERM, ENOENT, FS-race (getcwd fails), non-OSError — each swallowed to a graceful no-op (test names in `test_session_bridge_mtime.py`).
2. **Observability rider** → counter + one-shot stderr; a silently-dropped stamp is now countable/diagnosable (no false-idle dishonesty).
3. **Bootstrap pragma** → reason names the bootstrap-exception/PATH MANAGEMENT pattern explicitly.

## Test evidence (all :7999-eligible — fast, non-mutating, no real-bridge perturbation)
| Module | Tests | Coverage |
|---|---|---|
| session_bridge.py (new funcs) | 16 | 100% on touched funcs (L669-790) |
| bridge_liveness_middleware.py | 3 | 100% |
| post_tool_use.py (worktree) | 14 | 100% (28 stmts / 8 branch) |
| fleet_render.py | 37 | 100% (88 stmts / 34 branch) |
| arbiter_snapshot_store.py | 6 | 100% |
| routers/arbiter.py | 4 | 100% (TestClient + dep-override) |
| arbiter_job.py | 35 (incl. regression) | 100% (150 stmts / 36 branch) |
| cosa_voice_mcp.py / main.py | (2-line registrations) | import-time covered; regression green |
| **Regression** | 190 | session_bridge + heartbeat/arbiter + MCP + pre_tool_use suites all PASS |

## Out of scope / handoffs
- **Live-fire hook smoke** (worktree-green ≠ live-green) → Mr-Radio 🦉, post-apply on the live path.
- **HTTP/auth integration of the endpoint** (real DB credential) → integration tier (:8000, scheduled).
- **cosa_voice_mcp.py / main.py whole-file 100%**: pre-existing large surface; only the 2-line registrations are mine and they execute at import (verified by the 42/42 MCP regression + clean main import chain).
