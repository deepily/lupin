---
capability: server-coverage-fold
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.server_coverage.blob_hash@7eb50daef6
  - cosa.utils.server_coverage.data_files@4fdc6b824b
  - cosa.utils.server_coverage.fold@67e7dcb12e
  - cosa.utils.server_coverage.reset@c22b182ba6
  - cosa.utils.server_coverage.server_dir@ac29fc02e8
  - cosa.utils.server_coverage.verdict@c231a4a046
  - cosa.utils.server_coverage.write_boot@feab5c1284
---
# Server coverage fold

`server_coverage` lets the coverage gate count what `src/lupin_app/main.py` does inside the `:8000` test server. Those lines are start-up work and the `__main__` block, which no unit test reaches. The gate is described in [[gate-reachability]] and the frame check in [[coverage-frame-and-visual-failures]].

## What it does
- With `LUPIN_SERVER_COVERAGE=1`, `src/scripts/run-fastapi-lupin-test.sh` runs `write-boot` and then starts the server under `coverage run --parallel-mode --branch`, measuring only `main.py`.
- The start script passes `--rcfile=src/conf/coverage-server.rc`, which sets `sigterm = true`. `docker stop` sends SIGTERM, and without that setting no data file is written.
- `write_boot( directory, main_py )` clears the previous boot's data and records `main_py_hash` in `boot.json`.
- `blob_hash( path )` returns the same value as `git hash-object`, computed without git.
- `server_dir( root )` is `io/coverage/server` under the root, or `LUPIN_SERVER_COVERAGE_DIR` when set.
- `data_files( directory )` lists the `.coverage.*` parallel files and `reset( directory )` removes them.
- `verdict( directory, main_py )` returns `( reason, message, arcs )`. The reason is `ok`, `no-data`, `no-boot`, `bad-boot`, `stale`, `unreadable`, `empty`, `main-missing` or `no-arcs`.
- `fold( directory, main_py, target )` adds only `main.py`'s arcs to the gate's data file, under the host path of `main.py`.
- `src/tests/run-coverage-gate.sh` runs `fold` after the tier-data check. Any reason other than `ok` is gate exit 2, with a message that names the scheduled `:8000` run.

## Don't
- Don't key staleness on the tree HEAD. Every commit would make the gate inconclusive. The key is `main.py`'s content hash.
- Don't take other files from the server data. They come from whatever tree the server booted on and would be double-counted.
- Don't stop the test container with a kill. The data is written when the process exits, so use `docker stop`.
- Don't turn the flag on with a plain restart. The container env resolves at create, so use `docker compose up -d --force-recreate lupin-rest-test`.

## Invariants
- No usable server data is never a pass and never exit 1.
- With the flag unset, the start script's last command is the unchanged `exec python3 -m lupin_app.main`.
- A refused fold leaves the gate's data file untouched.
