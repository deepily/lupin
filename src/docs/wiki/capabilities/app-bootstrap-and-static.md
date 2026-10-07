---
capability: app-bootstrap-and-static
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_app.main.lifespan@497f7d03a2
  - lupin_app.main.add_security_headers@d838bf9587
  - lupin_app.bootstrap_helpers.assert_lupin_root_valid@d54a4c870a
  - lupin_app.bootstrap_helpers.register_sigusr1_faulthandler@fafd1bc4ad
  - lupin_app.bootstrap_helpers.reload_enabled@f782f9421f
  - lupin_app.versioned_static.VersionedStaticFiles@b25f754164
  - lupin_app.asset_tokens.content_token@5f8206fef6
  - lupin_app.asset_tokens.verify@5b42cd938c
  - lupin_app.asset_tokens.stamp@137f804af5
---
# App bootstrap and static files

`src/lupin_app/main.py` builds the FastAPI app. Three small modules beside it check the startup root, serve `/static` and stamp cache-busting tokens.

## Startup
- Importing `main` calls `assert_lupin_root_valid`, which raises unless `src/conf/lupin-app.ini` exists under `LUPIN_ROOT`.
- It then prints `[BOOT] SIGUSR1 thread-dump handler:` and a status from `register_sigusr1_faulthandler`, which returns a string and never raises.
- `lifespan` runs the database migrations to head before it builds the queues. Nothing catches a migration error, so boot stops.

## Middleware and routes
- The app mounts 38 routers with `include_router`, and then mounts `/static` last.
- It adds an upload size guard, CORS and a security-header function. CORS allows every origin with credentials, and none of the three checks a token.
- The header function sets `nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection` and `Strict-Transport-Security` on every response that passes through it. A 500 from an unhandled exception carries none of them.

## Static files and tokens
- `VersionedStaticFiles` answers a request that has a `v` query parameter with `public, max-age=31536000, immutable`. Every other file response gets `no-cache`.
- The server never compares `v` with the file. Any value, even a blank one, earns the one-year cache.
- A token is the first 12 hex characters of the SHA-256 of the file's bytes, read from the working tree. It is written into the HTML and JS files as a literal `?v=`.
- `python -m lupin_app.asset_tokens` checks every token and exits 1 on drift. `--stamp` rewrites them until none change, and reports a reference cycle.
- No server code imports `asset_tokens`. Unit tests import it, and one failure message tells the author to run `--stamp`.

## Reload
- `reload_enabled` is true only when `LUPIN_RELOAD` is `1`, `true` or `yes` and `LUPIN_ENV` is not `production`, `test` or `testing`.
- `docker-compose.yml` sets `LUPIN_ENV` to `development` for `:7999` and `testing` for `:8000`, and sets no `LUPIN_RELOAD`. A `.py` change needs a bounce.
- The environment is read when the container is created, so changing `LUPIN_RELOAD` needs a recreate and not a restart.
