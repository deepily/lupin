---
name: server-lifecycle
description: When and how to update or bounce the Lupin Docker servers (:7999 dev, :8000 test). Use when the user says bounce/restart/refresh/reload/redeploy/rebuild a server, or asks "did my change land?" / "is a restart needed?". Also fires on ASR variants ("doctor" → "Docker"). Encodes the per-server reload-regime asymmetry, the "never volunteer a :7999 bounce" rule, and the :8000 monopolize-mode protocol.
metadata:
  author: lupin-team
  version: "1.0"
  last-updated: "2026-04-26"
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
| **Dev** | `lupin-rest-dev` | `:7999` | uvicorn `--reload` ON, watches `.py` only | Tight inner loop on the live source tree |
| **Test** | `lupin-rest-test` | `:8000` (host) → `:7999` (container) | `reload=False` **deliberate** | Tests run on a frozen snapshot of the codebase so concurrent dev work on the same source tree can't poison a running test |

**The asymmetry collapses to ONE row of the decision matrix**: `.py` source changes. Everything else is symmetric.

> ⚠️ **Bouncing `:8000` while a test is in flight invalidates the snapshot guarantee.** That is *why* `:8000` is monopolize-mode and gated by `/api/test-suite/submit` with a confirmed slot.

---

## Decision Matrix — What to do When X Changed

| What changed | `:7999` dev | `:8000` test |
|--------------|------------|--------------|
| `.py` (any path on `PYTHONPATH`, including `src/cosa/`) | **None** — auto-reload picks it up | `docker restart lupin-rest-test` (or `/refresh-test` slash command) |
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

### Rule 1 — NEVER volunteer a `:7999` bounce

Even when the matrix says a `:7999` bounce is technically required (e.g. an INI change), **do NOT proactively suggest one**. Wait for the user to ask.

**Why**: Auto-reload covers `.py` changes for free, and the user has been bitten too many times by Claude conflating "auto-reload exists" with "a bounce is needed for everything." Volunteering a bounce is a recurring source of friction.

**How to apply**:
- Land the change. Report what was done. If a config-cached layer is involved (INI), state the fact ("ConfigurationManager caches at startup, so the running container won't see this until next instantiation") **as a fact**, not as a suggestion to bounce.
- The user will ask if/when they want a bounce. Then execute it.
- **Exception**: when the user has *already* asked you to bounce, this rule is satisfied — proceed.

See `feedback_fastapi_auto_reload.md` for the full prohibited-phrases list and incident history.

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
- `src/scripts/refresh-test-server.sh` — canonical `:8000` refresh script
- `.claude/commands/refresh-test.md` — slash-command wrapper for the same
