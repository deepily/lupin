# Lupin Runtime Config in `~/.claude/settings.json` — Reference

| | |
|---|---|
| **Scope** | The Lupin-platform runtime knobs that live inside Claude Code's `~/.claude/settings.json` |
| **Read by** | `src/lupin_cli/claude_code/hooks/**` (the Lupin hook scripts Claude Code invokes on events) |
| **Verified** | 2026-07-23 (Mr. Radio 🦉) |
| **Companion** | `src/docs/fleet-liveness-and-task-store-architecture.md` (architecture of the readers below) |

---

## ⚠️ PROVISO — this is NOT the final resting place

**These keys configure *Lupin*, not Claude.** They tune how the Lupin platform *responds to* Claude Code
event hooks (Stop, PostToolUse, UserPromptSubmit, …) — the heartbeat poke, the task-store mirror, idle
detection. They live in `~/.claude/settings.json` today only because that is the file Claude Code hands to
the hook subprocess, and the hook scripts read their config from the same JSON for convenience.

**This couples Lupin's runtime behavior to a third-party tool's config file.** Consequences worth naming:

- The config sits **outside the Lupin repo** (`~/.claude/`), so it is **not version-controlled with the code
  it drives** and cannot be committed, reviewed, or rolled back through Lupin's git history.
- A Lupin-owned concern (fleet liveness, task store) is expressed in **Claude Code's namespace**, mixed in
  beside `theme`, `model`, `permissions`.
- Every session/host must hand-maintain the same block; there is no single Lupin-owned source.

**Planned refactor (not yet scheduled):** move these blocks to a Lupin-owned config surface — a repo-tracked
file (e.g. under `src/conf/`) or the existing `lupin-app.ini`/`ConfigurationManager` — with `settings.json`
retaining, at most, a thin pointer. Until then, **treat this document as the authoritative schema** and this
location as **provisional**.

---

## The three Lupin-consumed blocks

All three are **top-level keys** in `~/.claude/settings.json`, siblings of `hooks`, `permissions`, `model`.
Each hook subprocess re-reads the file fresh, so **every change takes effect on the very next event** — no
restart, toggleable mid-session.

### 1. `heartbeat` — Stop-hook liveness + poke

Loaded by `lib/heartbeat_settings.py::load_heartbeat_settings()`. Validates loudly (raises `ValueError` on a
bogus `poke_cap` or `verification_threshold_seconds`).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `False` | Master switch. Dormant until wired on. |
| `poke_cap` | int > 0 | **`1`** | Max times the Stop-hook poke fires per session before it stops nagging. Was `3`; lowered to `1` (2026-07-23) — rapid repeated pokes were noise. Owned by `heartbeat_poke_cap.DEFAULT_POKE_CAP`. |
| `count_inbound_questions_as_owed` | bool | `False` | Whether an unanswered inbound DM counts as OWED work. Off by default (arbiter self-inflation). |
| `owed_source_from_store` | bool | `False` | Owed-items SOURCE: `False` = transcript replay (legacy); `True` = unified task-store count. The store-only cutover flag. Reversible. |
| `verification_threshold_seconds` | number > 0 | `600` | Manager worker-verification debounce; fires `needs_verification` while a manager's last look-in is older than this and workers are out. |
| `poke_output_enabled` | bool | `True` | Runtime mute: `False` suppresses the obligations lookup + its poke output WITHOUT tearing down the block. |
| `poke_disabled_message` | str \| null | `""` | Substitute text emitted when muted. `""`/null ⇒ full silence. The hook **prepends** `[heartbeat: pokes muted]` (the `MUTE_PROMPT_SENTINEL`) at inject time — **do NOT bake that tag into this value** or it doubles. |

### 2. `task_store` — task-store mirror / owed-count client

Loaded by `lib/task_store_settings.py`. The store host is F2-ruled to `:7999`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `False` | Master switch for the hook-side store mirror. |
| `api_base_url` | non-empty str | `http://localhost:7999` | Lupin base URL the store client hits (`/api/tasks…`). Trailing slash stripped. |
| `timeout_seconds` | number > 0 | `3.0` | Bounded hook-side wait per store request (short, so a Stop never hangs). |
| `spool_ttl_seconds` | number > 0 | `86400` | Outbox spool TTL (24h), mirrors `notify outbox ttl seconds`. |

### 3. `idle_detection` — idle-poke backoff

Loaded by `lib/idle_settings.py`.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `enabled` | bool | `True` | Master switch for idle detection. |
| `backoff_minutes` | list[int] | `[5, 10, 20, 40, 60]` | Escalating backoff schedule between idle pokes. |

---

## The `hooks` registration block

Not Lupin config per se — Claude Code's standard hook registry — but it is what **wires** the Lupin scripts
into Claude Code's event loop. Each entry runs `"$LUPIN_ROOT/.venv/bin/python3" "$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/<script>.py"`:

| Event | Script |
|---|---|
| `SessionStart` | `register_session.py` |
| `PostToolUse` | `post_tool_use.py` |
| `PreToolUse` | `pre_tool_use.py` (+ PIP `memento_record_guard.py` on Write\|Edit) |
| `Stop` | `stop.py` (reads the `heartbeat` block) |
| `Notification` | `notification.py` |
| `UserPromptSubmit` | `user_prompt_submit.py` |
| `SessionEnd` | `session_end.py` |
| `PermissionRequest` | `permission_request.py` |

---

## Change / rollback discipline

- **Edit with the Write/Edit tools**, never Bash heredocs (permission-pattern friction).
- After any edit: `python3 -c "import json; json.load(open('~/.claude/settings.json'))"` to confirm valid JSON.
- **Rollback is a value flip** — every switch above reverts by editing the key back; no redeploy, effective on
  the next event.
- Because this file is **outside the repo**, a settings change is **not captured** by a Lupin commit. Record
  behavior-affecting flips in `history.md` / the relevant R&D doc so the change is traceable.
