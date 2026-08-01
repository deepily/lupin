---
name: server-lifecycle
description: When and how to update or bounce the Lupin Docker servers (:7999 dev, :8000 test). Use when the user says bounce/restart/refresh/reload/redeploy/rebuild a server, or asks "did my change land?" / "is a restart needed?". Also fires on ASR variants ("doctor" → "Docker"). Encodes the 2026-08-01 policy change (reload is OFF on :7999, anyone may bounce it via src/scripts/bounce-dev-server.sh), the restart-vs-force-recreate distinction, and the :8000 monopolize-mode protocol.
metadata:
  author: lupin-team
  version: "2.0"
  last-updated: "2026-08-01"
---

# Lupin Server Lifecycle

When does a code change land? When is a bounce needed? Which command? This skill is the canonical runbook.

## Trigger Phrases

This skill activates when the user says any of:

- "bounce / restart / refresh / reload / redeploy the [dev|test] server"
- "bounce :7999", "restart :8000", "refresh the dev container"
- "rebuild the image", "compose up", "compose down", "down and up"
- "did my change land?", "is the new code live?", "do I need to restart?"
- "update the env", "secrets changed", "Dockerfile changed"

**ASR aliases** (MacBook ASR sometimes mishears):
- **"doctor" → "Docker"** — if the user says "use the doctor command" or similar in a context where Docker fits, treat it as "Docker"
- Add new pairs to `references/change-impact-matrix.md` as encountered

---

## The Two Servers (and Why They Behave Differently)

| Server | Container | Port | Reload mode | Why |
|--------|-----------|------|-------------|-----|
| **Dev** | `lupin-rest-dev` | `:7999` | **`--reload` OFF by default since 2026-08-01** — opt-in via `LUPIN_RELOAD`, gated by `reload_enabled()` in `bootstrap_helpers.py` | Watching the tree caused repeated multi-minute outages for the whole fleet whenever anyone touched a watched file |
| **Test** | `lupin-rest-test` | `:8000` (host) → `:7999` (container) | `reload=False` **deliberate** | Tests run on a frozen snapshot of the codebase so concurrent dev work on the same source tree can't poison a running test |

> ⚠️ **CHANGED 2026-08-01 — the old asymmetry is GONE.** `:7999` no longer picks up `.py` changes on its own. **Both** servers now need a bounce for Python. Verify before asserting either way: `docker exec lupin-rest-dev sh -c 'echo $LUPIN_RELOAD'` — empty means reload is disarmed.
>
> **`reload_enabled()` reads the environment at container START**, so re-arming reload needs a **recreate**, not a restart.

> ⚠️ **Bouncing `:8000` while a test is in flight invalidates the snapshot guarantee.** That is *why* `:8000` is monopolize-mode and gated by `/api/test-suite/submit` with a confirmed slot.

---

## Decision Matrix — What to do When X Changed

| What changed | `:7999` dev | `:8000` test |
|--------------|------------|--------------|
| `.py` (any path on `PYTHONPATH`, including `src/cosa/`) | **`./src/scripts/bounce-dev-server.sh`** — reload is OFF since 2026-08-01 | `docker restart lupin-rest-test` (or `/refresh-test` slash command) |
| `.ini` (`lupin-app.ini`, `lupin-app-splainer.ini`) | `docker restart lupin-rest-dev` | `docker restart lupin-rest-test` |
| Frontend static (`.js`, `.html`, `.css` under `src/lupin_app/static/`) | Browser hard-refresh (Ctrl+Shift+R) | Browser hard-refresh |
| `docker-compose.yml` (mounts, env, ports) | `docker compose down && docker compose up -d` | same |
| `Dockerfile` | `docker compose build <svc> && docker compose up -d <svc>` | same |
| `requirements.txt` / `pyproject.toml` | `docker compose build <svc> && docker compose up -d <svc>` | same |
| `.env` / secrets | `docker compose up -d <svc>` (env reads at start, not at restart) | same |

**The trap behind "I changed the mount but it's not there":** `docker restart` reuses cached compose config. Any compose-level change (mount, env, port, depends_on, networks) requires `down`/`up` — `restart` will silently apply nothing.

For deeper edge cases (CoSA submodule reloads, Jinja templates, in-memory state loss), see `references/change-impact-matrix.md`.

---

## CRITICAL Behavioral Rules

### Rule 1 — `:7999` bounces are NORMAL now; use the managed script

**SUPERSEDED 2026-08-01.** This rule used to read *"NEVER volunteer a `:7999` bounce."* Rick changed the policy the same day he disarmed reload: **anybody may bounce `:7999`, within reason, to pick up fresh code.** His words: *"it's not that big a deal anymore."*

**Use the sanctioned path, not a raw docker command:**

```bash
./src/scripts/bounce-dev-server.sh          # verbose
./src/scripts/bounce-dev-server.sh --quiet  # one-line summary
```

It does what a bare `docker restart` cannot: posts an **ack-confirmed** warning broadcast so the fleet holds notifications *before* the server dies, restarts the container, then polls `/health` until ready. The **all-clear comes from the restarted server's own startup hook**, so it fires on every restart path — not just this script's.

**What survives from the old rule**: don't be tedious about it. Bounce when a bounce is warranted, say so in one clause, move on. Don't pad plans and summaries with "after restart" qualifiers, and don't reach for "stale code" as the first explanation of a failing test — it's still almost never the cause.

**Still gated**: a `--force-recreate` (mount / env / compose changes) is a longer outage on shared infra and is not covered by the routine-bounce policy — see Rule 1b.

### Rule 1b — `restart` ≠ `--force-recreate`

| you changed | verb | why |
|---|---|---|
| Python / bind-mounted source | `bounce-dev-server.sh` (`docker restart`) | reuses the container; serves the new code |
| `docker-compose.yml`, a bind mount, an env var | `docker compose up -d --force-recreate <svc>` | mount specs + env resolve at container **CREATE**; a restart reuses them and the change silently does not land |

**A recreate also discards container-local state.** Measured 2026-08-01 on `lupin-rest-dev`: `projects/`, `backups/`, `plans/`, `mcp-needs-auth-cache.json` sit in the writable layer with no bind behind them; `.credentials.json` and `sessions/` **are** host-bound and survive. Nothing precious — but "nothing is lost" would be false.

See `feedback_fastapi_auto_reload.md` for the reversal and the incident history behind the old rule.

### Rule 2 — `:7999` bounce courtesy: queue check before SIGKILL

Once authorized to bounce `:7999`, the courtesy bar:

- **Best**: post an advisory ("bouncing :7999 in ~10s to pick up <reason>") a few seconds before bouncing.
- **Acceptable fallback**: probe `GET /api/get-queue/run` + `/api/get-queue/todo`. If both empty AND `inflight=0` on pool-status, bounce silently.
- **Never**: bounce silently when queues have entries. Ask first.

See `feedback_dev_server_bounce_courtesy.md` for the rationale.

### Rule 3 — `:8000` is NEVER bounced ad-hoc

The test server is monopolize-mode. **Never** issue `docker restart lupin-rest-test`, `compose up`, or any state-changing command on `:8000` outside the canonical channel.

The canonical channel:
- Schedule work via `POST /api/test-suite/submit` with a non-overlapping `scheduled_at`
- Confirm the slot with the user (slot-availability, NOT budget approval)
- The scheduling system handles bounce timing at the end of the prior scheduled run

The `/refresh-test` slash command and `src/scripts/refresh-test-server.sh` exist for *intentional* test-server refreshes — these are user-invoked, not Claude-invoked.

See `feedback_test_server_monopolize_mode.md` for the rationale.

---

## Canonical Commands

### Bouncing `:7999` (when authorized)

```bash
docker restart lupin-rest-dev
```

Verify:
```bash
docker ps --filter name=lupin-rest-dev --format "{{.Status}}"   # expect (healthy)
curl -sS http://localhost:7999/health                           # expect 200 + fresh timestamp
```

For INI verification specifically:
```bash
docker exec lupin-rest-dev grep '<key>' /var/lupin/src/conf/lupin-app.ini
```

(`src/` is bind-mounted, so the file's content is visible immediately on host edit; the bounce only re-instantiates `ConfigurationManager`.)

> ⚠️ **That parenthetical is the whole warning — read it before reusing this shape.** The grep proves the FILE has the value. It says nothing about whether the running process has read it. For **INI on `:7999`** that gap is small and named above. For **CODE on `:8000`** it is not: see "Did my fix land in the RUNNING PROCESS?" below, where the same command returns a confident YES while the process holds the old module.

### Refreshing `:8000` (user-invoked)

```bash
./src/scripts/refresh-test-server.sh
# or
/refresh-test         # slash command equivalent
```

The script polls `/health` until 200 OK (30s timeout) and dumps `docker logs --tail 50` on failure.

### Compose-level changes (any server)

```bash
docker compose down
docker compose up -d <service>          # lupin-rest-dev or lupin-rest-test
```

### Image rebuild (any server)

```bash
docker compose build <service>
docker compose up -d <service>
```

### Identifying what's running

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expect three containers: `lupin-rest-dev`, `lupin-rest-test`, `lupin-postgres`.

---

## Did my fix land in the RUNNING PROCESS? (row `ce89669e`)

**Never answer this by grepping the container.** `:8000` bind-mounts `./src` but runs `reload=False` by design, so the file inside the container is the host's current file while the imported module is whatever loaded at process start.

> **The file is new. The process is old. And the obvious check reads the file.**

Measured 2026-07-26 while verifying commit `69295c25`:

```
docker exec lupin-rest-test grep -c <symbol> .../job.py    ->  3
container started 13:44 UTC  ·  fix committed 16:29 UTC
```

Three hits, zero of them running — and the report reads as a measurement to everyone downstream.

⚠️ **`git` inside the container lies identically.** The repo is bind-mounted too, so `docker exec <c> git rev-parse HEAD` tracks the **host working tree**, not the loaded code. Re-confirmed 2026-07-27: the `:8000` container reported a sha committed on the host minutes earlier against a process nearly an hour old. *"Just check the sha instead of grepping" is the grep with extra steps.*

**The polarity used to be what made this a habit problem**: `:7999` ran `--reload`, so the same grep on the DEV container usually WAS true — the habit got trained where it worked and carried to where it didn't.

⚠️ **Since 2026-08-01 reload is OFF on `:7999` too, so the grep now lies on BOTH servers.** The habit has lost even the half of the fleet where it used to be accidentally right. Grepping a bind-mounted file has never measured what a running process loaded; it just used to coincide with the answer on dev.

### Use one of these two instead

```bash
# 1. From a shell — compares process start time against the commit's AUTHOR date.
src/scripts/verify-running-code.sh lupin-rest-test <commit-ish>
#    exit 0 HAS IT  ·  1 MISSING (recreate)  ·  2 CANNOT DETERMINE (absent / down / bad ref)
```

```bash
# 2. Over HTTP, no docker socket needed — identity captured at MODULE IMPORT.
curl -sS http://localhost:8000/api/code-identity
#    compare `imported_at` against: git log -1 --format=%aI <commit-ish>
#    commit newer than imported_at  =>  the running process does NOT have it
```

**Three outcomes, deliberately not two.** "Does not have it" and "cannot tell" have different remedies, and collapsing them reproduces this row's own defect inside its fix.

| Verdict | Meaning | Remedy |
|---|---|---|
| `0` HAS IT | process started after the commit | none |
| `1` MISSING | commit is newer than the process | **recreate** (`docker rm -f` + `compose up -d`) — a `restart` does NOT re-import a loaded module |
| `2` CANNOT DETERMINE | container absent, never started, or **stopped** | start it, or fix the ref — **not** a recreate |

⚠️ **The recreate has its own trap.** `docker rm -f` succeeds *before* `docker compose up -d` is known to work: compose interpolates `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` from `~/.bashrc`, which a non-interactive shell never sources. The destructive half lands first. Export them before recreating — `verify-running-code.sh`'s MISSING verdict prints the exact line.

⚠️ **A stopped container is `2`, not `0`.** `docker inspect` returns the LAST start time for a container that has exited — non-empty and perfectly parseable — so a start-clock read *without* `.State.Running` certifies every commit older than that stale timestamp against a process that is not there. That was a real defect in this script (fixed 2026-07-27); the lesson generalizes to any check built on `StartedAt`.

---

## What This Skill Does NOT Cover

- **Container debugging** (won't start, keeps restarting, OOM): use `docker logs`, `docker inspect`, `docker compose logs -f` — out of scope here.
- **Database migrations**: separate concern; see migration-specific docs.
- **Container build failures**: a separate runbook layer.

This skill is purely about *intentional* lifecycle actions and the decision tree for "did my change land."

---

## Cross-References

- `feedback_fastapi_auto_reload.md` — prohibited phrases for `:7999` bounce mentions
- `feedback_dev_server_bounce_courtesy.md` — queue-check rule
- `feedback_dev_server_bounce_via_docker.md` — pointer to this skill
- `feedback_test_server_monopolize_mode.md` — `:8000` scheduling protocol
- `reference_port_routing_dual_container.md` — port mapping (host:8000 → container:7999)
- `src/scripts/verify-running-code.sh` — does the RUNNING process have this commit? (row `ce89669e`)
- `src/cosa/rest/code_identity.py` + `GET /api/code-identity` — the same answer over HTTP, captured at module import
- `src/scripts/refresh-test-server.sh` — canonical `:8000` refresh script
- `.claude/commands/refresh-test.md` — slash-command wrapper for the same
