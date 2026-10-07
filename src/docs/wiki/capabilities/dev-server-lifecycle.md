---
capability: dev-server-lifecycle
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.rest.venue_idle.decide@1e8a175b8c
  - cosa.rest.venue_idle.read_signals@a2e28b041f
  - cosa.rest.managed_bounce_broadcast.build_bounce_message@d6b480c086
  - cosa.rest.managed_bounce_broadcast.next_boot_id@4f8721128c
  - cosa.rest.managed_bounce_broadcast.poll_acks_until_satisfied@0f16ce365f
  - cosa.rest.pytest_args_policy.validate_pytest_args@4fb07676e4
  - cosa.rest.code_identity.capture_code_identity@fcfb2adf69
  - cosa.rest.error_envelope.build_error_envelope@59c77236f3
---
# Dev server lifecycle

Small modules that say whether a server is free, announce its restarts and name the code it runs. One also limits what a test run may import.

## What it does
- `python -m cosa.rest.venue_idle --port 8000` reads `GET /api/busy` and exits 0 for `IDLE`, 1 for `BUSY` and 2 for `UNKNOWN`. `decide` holds the rule.
- `managed_bounce_broadcast` builds the fleet "warning" and "all-clear" messages for the server named by the INI `managed bounce server label`. That is `:7999` in the dev section and `:8000` in `[Lupin: Testing]`. The server's own startup hook sends the all-clear, and the host script sends the warning and waits for acks. A graceful shutdown also sends a best-effort warning from the server itself.
- `next_boot_id` increments a boot counter file, one per server label under `io/managed-bounce/`, so a crash loop reads as numbered all-clears.
- `capture_code_identity` records git sha, branch, load time and pid once at import. `/` and `/api/code-identity` serve it.
- `validate_pytest_args` checks every token of a caller's `pytest_args` against an allowlist, and `PytestArgsRejected` is its refusal.
- `build_error_envelope` shapes an unhandled 500 as `detail`, `exception_class` and `server_started_at`.

## Don't
- Don't call a venue idle from `pool-status` or the user-filtered queue listings. Only `/api/busy` sees every user's queued and inline work. The listings show only the caller's own.
- Don't add `-p`, `--junit-xml` or `--rootdir` to the pytest allowlist. The first imports a module, the second is a write path, and the third moves which conftest is imported.
- Don't put the exception message in the error envelope. Nobody has audited what it could expose.
- Don't compute code identity per request. A fresh read would answer from the files, not from the running process.

## Invariants
- `UNKNOWN` means a signal could not be read, including a container without `todo_queue_size`. It is never reported as `IDLE`.
- `BUSY` wins over `UNKNOWN` in `decide`. `IDLE` needs every required signal read and empty.
- Each `pytest_args` token is an allowlisted flag, a value bound to one, or a path under `src/tests` or `src/cosa/tests`. A token over 512 characters, or more than 64 tokens, is refused.
- `git_sha` reads `unavailable` when git cannot answer. A plausible default is never substituted.
- Compare `imported_at` with a commit's author date to learn whether a process has that commit.
- `boot_counter_path` names each file from the label's alphanumerics, so `:7999` and `:8000` never share one. Both containers share the `io/` mount.
