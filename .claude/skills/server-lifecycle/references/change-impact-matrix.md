# Change-Impact Matrix — Edge Cases & Rationale

Companion to `SKILL.md`. Use when the user's change doesn't fit cleanly into the main decision matrix.

---

## CoSA Submodule (`src/cosa/`)

`src/cosa/` is on the container's `PYTHONPATH` via the bind mount of `src/`. From a reload-detection standpoint:

- `.py` files inside `src/cosa/` behave **identically** to `.py` files in the parent `src/` tree
- Dev `:7999` auto-reloads them; test `:8000` requires a bounce
- The submodule's *git state* is not the AI's concern from parent context (see `feedback_lupin_only_never_cosa.md`), but **editing** `src/cosa/*.py` files and relying on auto-reload is fine

CLAUDE.md memory entry `feedback_cosa_edit_vs_manage_git.md` confirms this.

---

## Static Assets — Why No Bounce Ever

`src/lupin_app/static/` files (`.js`, `.html`, `.css`, images, etc.) are served fresh from disk on every HTTP request. The Python process never caches them.

- Browser caching is the *only* layer that needs invalidation
- Hard-refresh (Ctrl+Shift+R / Cmd+Shift+R) bypasses the browser cache
- Versioned URLs (`?v=...`) work too if available

This applies to BOTH `:7999` and `:8000`. The reload-mode asymmetry doesn't matter here — Python doesn't import these files.

---

## Jinja Templates

If a template lives in `src/lupin_app/templates/` or `src/templates/`:

- FastAPI's `Jinja2Templates` instance reads templates fresh per request (default behavior)
- No bounce needed on `:7999` or `:8000`
- Same as static assets

If a future change adds template caching (`auto_reload=False` on Jinja2), this row needs revisiting.

---

## INI Files — Why a Bounce Is Required

`ConfigurationManager` (`src/cosa/config/configuration_manager.py`) reads `lupin-app.ini` and `lupin-app-splainer.ini` **once at instantiation** and caches the parsed values. The instance lives for the lifetime of the FastAPI process.

- uvicorn's `--reload` watches `.py` files only — INI edits do not trigger a reload on `:7999`
- A `docker restart` rebuilds the process and re-instantiates `ConfigurationManager`
- This is true on both servers; the asymmetry doesn't apply because INI doesn't fall under the `--reload` watcher

If someone wants live INI reload in the future, the path would be:
1. Add `*.ini` to uvicorn's `--reload-include` glob
2. Add a config-mgr signal handler that re-reads on SIGHUP
3. Audit all consumers that hold cached references to config values

None of that exists today.

---

## `.env` — Why `restart` Isn't Enough

Environment variables are loaded by `docker compose` at container *creation* time (`up`), not at *restart*. `docker restart` reuses the existing container's already-loaded env.

To pick up `.env` changes:
```bash
docker compose up -d <service>
```

`compose up -d` recreates the container if its config (env, mounts, image) has drifted from the compose file. Otherwise it's a no-op.

---

## `docker-compose.yml` — Why `restart` Isn't Enough

`docker restart` does NOT re-read `docker-compose.yml`. It reuses the container's existing runtime config (mounts, env, ports, depends_on, networks) — all of which were materialized when the container was originally created with `up`.

If you change ANY of:
- `volumes:` (mount paths, host paths, mount options)
- `environment:` / `env_file:`
- `ports:`
- `depends_on:`
- `networks:`
- `command:` / `entrypoint:`

…then `docker compose down && up -d` is required. `restart` will silently do nothing visible.

**Symptom that signals this trap**: "I changed the bind mount path but the container still sees the old path." → You forgot `down`/`up`.

---

## In-Memory State Loss

Every bounce — restart, recreate, rebuild — **discards all in-memory state**:

- Job queues (todo, running, done) — persisted to LanceDB, but in-memory views reset
- WebSocket sessions — clients reconnect (auto-reconnect logic handles this)
- ConsumerThread — restarts cold; in-flight job in the agentic pool is lost (the Future never completes)
- Notification subscriptions — clients re-register on WS reconnect

If you have a long-running job in the running queue and bounce mid-flight, you'll dead-letter that job. The courtesy queue-check (Rule 2 in SKILL.md) exists exactly to prevent this.

---

## ASR Phonetic Neighbors

The user dictates from a MacBook with imperfect ASR. Track aliases as encountered:

| Heard | Likely intended | Context cue |
|-------|-----------------|-------------|
| **doctor** | **Docker** | "use the doctor command", "doctor restart" |
| | | (Add others as encountered) |

Heuristic: if the literal word doesn't fit context but a phonetic neighbor matches a known tool/command in this skill's vocabulary, prefer the neighbor.

---

## Verification Cheat Sheet

After any state-changing action, run the matching verifier:

| Action | Verifier |
|--------|----------|
| `docker restart lupin-rest-dev` | `docker ps --filter name=lupin-rest-dev --format "{{.Status}}"` → `(healthy)`; `curl http://localhost:7999/health` → 200 |
| `docker restart lupin-rest-test` | same with `lupin-rest-test`, port `:8000` |
| INI value change + bounce | `docker exec <container> grep '<key>' /var/lupin/src/conf/lupin-app.ini` |
| `compose down/up` | `docker ps` shows new container ID; `docker inspect <container> --format '{{.Created}}'` is fresh |
| Image rebuild | `docker images <image> --format "{{.CreatedSince}}"` reflects the rebuild |

---

## Anti-Patterns to Avoid

| Anti-pattern | What's wrong | Correct approach |
|--------------|--------------|------------------|
| `kill -TERM <host-PID>` | Bypasses Docker's lifecycle interface; "works" only because Docker's restart policy respawns the container | `docker restart <container>` |
| `docker restart` after editing `docker-compose.yml` | Silently applies nothing; cached compose config persists | `docker compose down && up -d` |
| Volunteering a `:7999` bounce | Violates "never mention restarts" rule | State the change is applied; let the user request a bounce if needed |
| Side-door inject to `:8000` (curl, ad-hoc API push, in-process server) | Collides with in-flight scheduled tests | `POST /api/test-suite/submit` with confirmed `scheduled_at` |
| `docker compose restart` after `requirements.txt` change | Doesn't rebuild the image; pip ran at build time | `docker compose build <svc> && up -d <svc>` |
