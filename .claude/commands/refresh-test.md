# Refresh Test Server

**Project**: Lupin
**Prefix**: [LUPIN]

---

## Usage

`/refresh-test` - Force the test server on port 8000 to pick up source changes.

---

## Instructions to Claude

The test container (`lupin-rest-test`) runs uvicorn with `reload=False`, so disk edits
are not picked up until the Python process restarts. Source is bind-mounted, so no
image rebuild is required — only a container restart.

**Command**:
```bash
./src/scripts/refresh-test-server.sh
```

**What this does**:

- `docker restart lupin-rest-test`
- Polls `http://localhost:8000/health` until 200 OK (30s timeout)
- On failure: prints `docker logs --tail 50 lupin-rest-test`

**In-memory state is discarded by design** (queues, WS sessions, consumer thread
restart cold). If you need to preserve state, don't use this command.

**Do NOT use this on the dev server (:7999)** — dev runs with `--reload` and already
picks up edits automatically.
