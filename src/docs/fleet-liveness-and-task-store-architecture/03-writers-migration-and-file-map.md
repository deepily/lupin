> Part 3 of 3 of the [Fleet Liveness & Unified Task-Store — Architecture (Top to Bottom)](../fleet-liveness-and-task-store-architecture.md): the writers, the migration and cutover machinery, the file map and the open follow-ups.

## 6. Writers — the manager/worker session lifecycle

The fleet is a set of real Claude Code sessions (detached tmux), each with a voice **persona**. Roles: **manager** (coordinates, never self-implements the build) and **worker** (author/reviewer/tester).

**Spawn / reap** (cosa-voice MCP, host-side): `spawn_sessions(count, role, task_prompt, persona_preference, …)` launches headless `claude` sessions.
They boot a persona and read `task_prompt` as their brief.
`dismiss_sessions` reaps them. Results flow back over DM threading to `dm-<manager-persona>`.

**The standing build loop** a manager runs:
1. Spawn a worker with a **baked brief** (null-persona workers can't be reliably DM'd inbound — — so the brief must be self-contained).
2. Worker builds in a **git worktree** (never the live tree).
   `stop.py` and the hook libs are *live enabled hooks*, and editing them in place runs unreviewed code on every trigger.
3. Worker reports **green** to `dm-<manager>`.
4. Manager spawns a **fresh-critical reviewer** (reproduce-not-trust).
5. On approve, the manager does a **commit and `--no-ff` held merge** to the working branch.
   It holds standing authority for that once the work is green and reviewed.
   It then closes the matching store rows with the merge receipt and reaps the workers.
6. **Push** is the human's gate (manager *executes* it on the human's word); commit + merge are not.

**Coordination**: managers DM each other (`dm_send`, body inline ≈ 200 tokens) and the human via `notify` / blocking `ask_*`. Two managers split a build by a **seam** (e.g. spine vs UI card) sharing only a stable read-contract.

---

## 7. The migration & cutover machinery

**Migration drain** — `src/lupin_cli/claude_code/hooks/lib/task_store_drain.py`: per **active session**, it replays the transcript's owed native items and `task_create`s any missing ones.
It is idempotent via `correlation_key` and `query_by_correlation_key`, and dry-run by default (`--apply` writes). Includes a per-session **count-parity** check (store owed-count == transcript owed-count). Run before flipping the flag so no session goes dark at cutover.

**Cutover sequence (executed 2026-06-17, Rick-supervised)**:
1. `drain --apply` → parity 4/4.
2. verify parity (would_create = 0).
3. flip `heartbeat.owed_source_from_store=True` in `~/.claude/settings.json`; verify it reads `True`.
4. (lockstep) the doctrine (pip surfaces + global `CLAUDE.md`) flips to "store-only / stop using native TaskCreate" **strictly after** the flag. No window where doctrine says store-only while the oracle still reads the transcript.

**The mirror (deprecated bridge)** — `post_tool_use.py` + `lib/task_store_mirror.py`: historically auto-copied harness `TaskCreate` → store. It is **retired in stages**, gated on evidence.
Keep it a **logged no-op** until its fire-log goes quiet fleet-wide, then delete it and drop the dead `TASK_STORE_WRITE_TOOLS` entries.
Pulling it early would silently dark not-yet-migrated sessions.
The collision fix (generation-aware correlation keys) makes it safe during the interim.

---

## 8. File map / source-of-truth

| Concern | File(s) |
|---|---|
| Store API + repo | `src/cosa/rest/routers/tasks.py`, `…/db/repositories/task_repository.py` |
| Store MCP verbs | cosa-voice server `task_create` / `task_query` / `task_transition` |
| Stop-hook seam | `src/lupin_cli/claude_code/hooks/stop.py` (~`_run_heartbeat`) |
| Heartbeat libs | `…/hooks/lib/{heartbeat_settings,heartbeat_work_owed,task_store_client,heartbeat_hold}.py` |
| Migration drain | `…/hooks/lib/task_store_drain.py` |
| Mirror (deprecated) | `…/hooks/post_tool_use.py`, `…/hooks/lib/task_store_mirror.py` |
| Project resolution | `…/hooks/lib/session_bridge.py` `resolve_project_name()` |
| Arbiter | `src/cosa/agents/heartbeat_arbiter/{arbiter_job,fleet_data_model}.py`, `src/lupin_arbiter_app/` |
| Arbiter launch | `src/scripts/run-lupin-arbiter-app.sh` + systemd `--user` `lupin-arbiter-app.service` |
| Cutover flag | `~/.claude/settings.json` → `heartbeat.owed_source_from_store` |
| Spawn/reap | cosa-voice `spawn_sessions` / `dismiss_sessions` |
| Design record | `src/rnd/v0.1.8/2026.06.16-store-canonical-task-mgmt-cascade-review.md` *(`REMOVED`; recover: `git show b113a3a7^:src/rnd/v0.1.8/2026.06.16-store-canonical-task-mgmt-cascade-review.md`)* (review + cutover log) |
| Arbiter routing | `src/docs/agents/heartbeat-arbiter-routing-guide.md` |

---

## 9. Open follow-ups (see the dedicated plan)

These are tracked separately in the follow-up plan (`src/rnd/v0.1.8/…-followups-plan.md`):

- **Mirror retirement**, gated on evidence.
- **Poke-cap**, held, reviewed-green and awaiting merge and push.
- **Arbiter detector gaps**: tap-ACK and whole-fleet-stall need done and blocked-on-user awareness.
- Minor residue: `count_only` adoption and connection reuse.
