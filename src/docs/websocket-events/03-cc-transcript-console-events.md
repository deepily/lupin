> Part 3 of 6 of the [WebSocket Event System Documentation](../websocket-events.md): CC transcript console events, the watch and unwatch commands.

## CC Transcript Console Events

> **Status**: the contract is documented, and the server side lands in the first build phase. Plan and acceptance criteria: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md` section 2–section 3. Names are per ruling **OSQ-6** and supersede the earlier `transcript_*` spelling in that plan's ruling Q4b.

A read-only live window onto what a Claude Code seat is printing. The source is the seat's **transcript JSONL file** — not a terminal tee. Tailed by byte offset on `:7999` and pushed to the watching browser over the **existing** `/ws/queue/{session_id}` socket. No new socket, no new auth path.

**Four rules that are easy to get wrong, so they are stated before the payloads:**

1. **`cc_session_id` is the seat's `stable_session_id`** — the full id that survives a `/clear`. Never the post-clear id, and never the 8-character form the fleet uses elsewhere (`sender_id`'s `#<8hex>` suffix, a DM's `recipient_session_hash8`). Three id widths circulate in this fleet; a silent mismatch shows up as a roster row that cannot be watched.
2. **`offset` is the sequence number**. It is a byte offset into the source file. There is no separate `seq`, and `next_offset` always lands at the end of a **complete** line.
3. **`file_epoch` scopes every offset**. It names the transcript file. A `/clear` **swaps the path** rather than shrinking the file. So the epoch — not a shrink — is what tells a client its offset is void.
4. **Admin only**, enforced on **both** surfaces: the WS verb checks `websocket_manager.session_is_admin[ session_id ]`, and the REST backlog uses `require_admin`. Two different gates; both are load-bearing. No redaction in v1 — the stream carries whatever the seat read, including file contents.

### `cc_transcript_watch` (Client → Server)

Start receiving append frames for one seat. Sent on the already-authenticated `/ws/queue` socket.

```json
{
  "type"        : "cc_transcript_watch",
  "cc_session_id": "449359bc-c735-4970-8fc0-e83b635c8548",
  "from_offset" : 0,
  "file_epoch"  : null
}
```

- `from_offset` — **the server starts where the client asked**. It never silently starts at the current end of the file. Doing so would open a gap between the REST backlog fetch and the live watch.
- `file_epoch` — **nullable**. `null` means "whatever file is current", and the server answers with the epoch it chose. So a first watch needs no prior REST call. A **stale non-null** epoch is **refused, never silently rebased**: the server replies `cc_transcript_state {state: "epoch_mismatch"}` and sends no blocks. Rebasing would hand the client a whole new file labelled as its own continuation.
- A watch from a non-admin session is **refused**.

### `cc_transcript_unwatch` (Client → Server)

```json
{ "type": "cc_transcript_unwatch", "cc_session_id": "449359bc-..." }
```

Stops the frames. The tailer stops after the **last** watcher leaves, plus a grace period.

> Warning: **Unwatch is the polite path, not the reliable one**. A closed tab or a dropped socket never sends it. So `WebSocketManager.disconnect()` sweeps the watcher registry as well. That sweep is hand-maintained — it already deletes from `active_connections`, `session_timestamps`, `session_subscriptions`, `session_is_admin`, `session_client_types` and the user association one statement at a time. So the watcher map is a **sixth entry that has to be added there explicitly**. Miss it and the tailer polls forever while `emit_to_session` early-returns into a session already gone: a silent burn with no error anywhere.
