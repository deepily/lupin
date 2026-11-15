---
capability: mcp-notify-outbox
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_mcp.notify_outbox.spool@1bb5a378a9
  - lupin_mcp.notify_outbox.list_spooled@31b0d8d35c
  - lupin_mcp.notify_outbox.flush@41277f49c2
  - lupin_mcp.notify_outbox.flush_tick@a130f95bd8
  - lupin_mcp.notify_outbox.run_flusher@4e5b3c16cf
  - lupin_mcp.notify_outbox.start_flusher@5f79d10ce7
---
# Notify outbox

When the notification server cannot be reached, the cosa-voice MCP server ([[cosa-voice-mcp-server]]) spools the request to a file and retries it later. The retries run on a daemon thread that checks a scheduled-job switch before every flush ([[mcp-cron-switch-read]]).

## Spool and flush
- `spool( request, outbox_dir )` writes a failed notification as `<epoch_ms>-<idempotency_key>.json` and returns the path. `list_spooled` lists the files oldest first.
- `flush( send_fn, outbox_dir, ttl_seconds )` retries each file in order. It deletes a delivered, expired or corrupt file, leaves a refused one, and returns the counts.

## The flush daemon
- `flush_tick( switch, send_fn, outbox_dir, ttl_seconds )` flushes the spool unless the switch says off. A skipped tick leaves the spool alone. A `flush` error is logged and never raised.
- `run_flusher` sleeps, then makes one `flush_tick`, and repeats until its `stop` callable says to end.
- `start_flusher` starts one daemon thread per process that runs `run_flusher`, and returns False if one already runs.
- It builds the `cron job notify-outbox enabled` switch before it marks the daemon started. A failure to build it leaves the daemon startable on the next call.
- The loop checks that switch fresh from disk before every flush. A false or unreadable switch skips that flush and the loop keeps running.
- The idempotency key lets the server drop a duplicate.
