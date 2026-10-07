---
capability: system-admin-and-stats
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.routers.system.health@803a59656b
  - cosa.rest.routers.system.busy@d612dce662
  - cosa.rest.routers.system.code_identity@5efda7e8a2
  - cosa.rest.routers.system.init@4a1bb872eb
  - cosa.rest.routers.system.bounce_dev_server@6686d21d79
  - cosa.rest.routers.mode.set_mode@09b1a8fd55
  - cosa.rest.routers.stats.get_time_saved_stats@2c391106b9
  - cosa.rest.routers.multiplexer_config.get_multiplexer_config@1c8041d3d3
  - cosa.rest.routers.pages.page_notifications@84a30924aa
  - cosa.rest.routers.websocket_admin.cleanup_websocket_sessions@c928a82de3
---
# System admin and stats

The small routers that report on the server, steer it, and map clean URLs to pages: `system`, `mode`, `stats`, `multiplexer_config`, `pages` and `websocket_admin`.

## What it does
- `system` serves `/` (health plus code identity), `/health`, `/api/busy`, `/api/code-identity`, `/api/init` and `/api/system/bounce`.
- `busy` reports queue occupancy, fleet-wide and without a login: pool in-flight, run queue, todo queue and the monopolize slot.
- `code_identity` returns the git sha, branch and load time captured when the module was imported.
- `bounce_dev_server` cannot restart its own container, so it writes a trigger file for the host-side watcher. Replies are 409 (already running), 503 (watcher heartbeat over 30 s old) or 202.
- `mode` lets a user read, set or clear a per-user agent mode; `None` means system mode. `stats` reports time saved by cached solution replays.
- `get_multiplexer_config` returns two display values, defaulting to 256000 bytes and 0.25, with no login.
- `pages` maps `/app/*` to static HTML with `Cache-Control: no-cache`. `/app/notifications` redirects to the multiplexer when the INI flag `legacy notifications redirect enabled` is on, unless `?classic=1`.
- `websocket_admin` lists, inspects, disconnects and cleans WebSocket sessions, and sets the single-session policy.

## Don't
- Don't add a field to `/health`. It stays at two fields because a docker healthcheck calls it and a test pins the count.
- Don't decide a venue is idle from pool-status. `/api/busy` also counts queued work, which pool-status cannot see.
- Don't read the running code from files in the container. Compare `imported_at` from `/api/code-identity` with the commit date.

## Invariants
- `init` is admin only. It re-reads configuration and then calls `invalidate_all` on the cache registry.
- `bounce_dev_server` checks for a bounce in progress before it checks the watcher heartbeat.
- `system` and `websocket_admin` both define `GET /api/websocket-sessions` and `POST /api/websocket-sessions/cleanup`. `main.py` includes `system` first.
