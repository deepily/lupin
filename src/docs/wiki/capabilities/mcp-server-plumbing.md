---
capability: mcp-server-plumbing
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.jsonrpc_stdout.reserve_stdout_for_jsonrpc@1aa1d7aa5b
  - lupin_mcp.outbound_api_key.load_outbound_api_key@7d660725f7
  - lupin_mcp.outbound_api_key.outbound_key_failure_detail@dc982aba74
  - lupin_mcp.validation_alert_throttle.is_suppressed@d6babf7f87
  - lupin_mcp.validation_alert_throttle.record_sent@ae0a0ff0af
  - lupin_mcp.notify_outbox.spool@1bb5a378a9
  - lupin_mcp.notify_outbox.list_spooled@31b0d8d35c
  - lupin_mcp.notify_outbox.flush@41277f49c2
  - lupin_mcp.notify_outbox.start_flusher@fa5d28f371
  - lupin_mcp.config_write_lock.lock_dir@8bc366a99d
  - lupin_mcp.config_write_lock.lock_path@a95592c4e2
  - lupin_mcp.config_write_lock.write_lock@bf55f94153
  - lupin_mcp.podcast_for_rick.translate_host_path@fcc8189298
  - lupin_mcp.podcast_for_rick.podcast_for_rick_impl@9a5195b98c
---
# MCP server plumbing

Small helpers behind the cosa-voice MCP server ([[cosa-voice-mcp-server]]): the stdout guard, outbound key, outbox, alert cooldown, config lock and podcast tool.

## Process and credentials
- `reserve_stdout_for_jsonrpc` gives the JSON-RPC protocol a private copy of stdout and points fd 1 at stderr, so stray prints cannot corrupt a frame. Call it first, once. It also wraps the FastMCP `stdio_server` to write to that channel.
- `load_outbound_api_key` returns the key string from `src/conf/keys/notification-api-claude-code-dev`, or None. It never raises and records why a load failed.
- `outbound_key_failure_detail( endpoint )` renders that cause: file missing, unreadable (mode and owner uid) or empty. Callers put it in the `detail` of a `missing_auth_header` error.

## Alerts, outbox and lock
- `is_suppressed( project )` is true when this project's last delivered validation alert is under six hours old. A missing or corrupt state file, or a clock gone backwards, means send.
- `record_sent( project )` writes the delivery time atomically into `~/.lupin/mcp-validation-alerts.json`. It returns False, and raises nothing, when it cannot write. Record only after delivery.
- `spool( request, outbox_dir )` writes a failed notification as `<epoch_ms>-<idempotency_key>.json` and returns the path. `list_spooled` lists the files oldest first.
- `flush( send_fn, outbox_dir, ttl_seconds )` retries each file in order. It deletes a delivered, expired or corrupt file, leaves a refused one, and returns the counts.
- `start_flusher` starts one daemon thread per process that calls `flush` on an interval, and returns False if one already runs. The idempotency key lets the server drop a duplicate.
- `write_lock()` holds an exclusive `flock` for a with block, so two writers of the main configuration file cannot lose an edit. It waits for any holder and releases on error.
- `lock_dir` is `$LUPIN_CONFIG_LOCK_DIR`, else `$LUPIN_FLOW_RATIO_DIR`, else the fleet data root's `flow-ratio` folder. `lock_path` is `.lupin-app.ini.lock` there, outside the source tree.

## Podcast tool body
- `translate_host_path( host_path )` turns a seat's absolute path into `<scope>/<relative>`. It refuses a relative path, a missing file, a file in no git repository and a file in a linked worktree.
- `podcast_for_rick_impl` asks for the podcast card, polls it and starts the job on a yes. It returns `started`, `dry run`, `declined`, `default_used`, `expired` or an `error` with a reason. See [[rest-core-podcast-cards]].
