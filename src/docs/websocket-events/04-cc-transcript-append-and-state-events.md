> Part 4 of 6 of the [WebSocket Event System Documentation](../websocket-events.md): CC transcript append and state events, and the REST companion.

### `cc_transcript_append` (Server → Client)

Coalesced roughly every 300 ms per seat, delivered by `emit_to_session` to watchers only.

```json
{
  "type"        : "cc_transcript_append",
  "cc_session_id": "449359bc-...",
  "file_epoch"  : "449359bc-c735-4970-8fc0-e83b635c8548",
  "offset"      : 20480,
  "next_offset" : 24576,
  "blocks"      : [
    { "ts": "2026-09-27T18:04:03Z", "role": "assistant", "kind": "text",
      "text": "Reading the spec now.", "truncated": false },
    { "ts": "2026-09-27T18:04:05Z", "role": "assistant", "kind": "tool_call",
      "text": "Bash( sha256sum … )", "truncated": false, "name": "Bash" },
    { "ts": "2026-09-27T18:04:06Z", "role": "user", "kind": "tool_result",
      "text": "41661313b706…", "truncated": true }
  ],
  "ts"          : "2026-09-27T18:04:06Z"
}
```

**Every `tool_call` block carries `name`**: the tool's own name (`"Bash"`, `"mcp__cosa-voice__notify"`).
A client therefore never parses the `text` chip to learn which tool ran.
The field is present on `tool_call` blocks and on **no other kind**.
It falls back to `"tool"` when the transcript's `tool_use` block has none, which is the word the chip uses.
The REST backlog serves the identical field, because both doors build blocks with one mapper.

**A `tool_result` carries the `name` of the call it answers**, paired by `tool_use_id`.
Mobile renders it as "Result — <name>".
The result arrives in a later record than its call, and on the live stream often in a later poll.
So the server keeps one `tool_use_id` → name index per watched seat, across polls.
The index is bounded at 4096 pairings, with the oldest evicted.
It is emptied on a `/clear` path swap, an in-place truncation and a new watch.

**An orphan result carries no `name` key, never a guess**.
Its call fell before the window the client asked for, left the index, or sat in the file before a rotation.
A backlog that starts after the call, or a `from_offset` mid-file, produces that case.
A call that never named itself lends nothing.
The client falls back to its own label.
REST and WS agree on any window they both cover.
A window's edge is where they can differ: the live index may still remember a call that the REST page's start cut off.

**Gap rule**: if `offset != last_next_offset`, the client **drops the frame** and repairs over REST from `last_next_offset`.

**A block's `kind` comes from the content block's type, never from the record's role**. In a census of 8,115 records across four recent lupin transcripts, **760 of the 1,026 `user` records carried tool results**. A role-based mapping would render three quarters of them as fake human turns.

**`kind` decides the renderer, and prose and tool content do not share one**. `text` renders as markdown. `tool_call`, `tool_result` and `thinking` render as **plain text** (`<pre>` / `textContent` on the web), collapsed and truncated.
`thinking` is folded and expandable. **A kind the client does not recognise renders as plain text — never dropped, never thrown on**. The mapper is open-ended by rule.
So a switch over three literals with no fallback would render nothing, silently, in the one surface whose whole job is to show everything.
The risk here is **mangling, not injection**.
A markdown renderer turns a raw file dump into markup, so `#` becomes a heading and a diff renders wrong.

**Blocks are budgeted**. A block over its budget arrives with `truncated: true` and the full text is available over REST. Following `routers/tasks.py`, **`budget == 0` means unbounded, not zero** — keep that sense rather than inventing a `cap` that reads the opposite way.

### `cc_transcript_state` (Server → Client)

```json
{
  "type"        : "cc_transcript_state",
  "cc_session_id": "449359bc-...",
  "file_epoch"  : "…",
  "state"       : "live"
}
```

| `state` | Meaning | Client action |
|---|---|---|
| `live` | The tailer is attached and following the file | none |
| `ended` | The **seat** exited — driven by the `SessionEnd` hook, with a staleness fallback for a seat that dies without firing it | stop expecting frames. The pane is final, not merely quiet |
| `rotated` | The `file_epoch` changed: a `/clear` swapped the transcript path, or the file was truncated in place | drop the buffer and offset, re-fetch the backlog over REST |
| `epoch_mismatch` | The watch named an epoch that is no longer current | same as `rotated` — clear and re-fetch. **No blocks accompany this frame** |
| `refused` | The server will not serve this watch; the frame's **`reason`** says why. Two reasons today: `not_found` — no such seat, or its transcript file is not here. `admin_only` — the caller's session does not hold the admin role (newer behaviour; before that a non-admin watch got a generic `error` frame, which a refused `cc_transcript_unwatch` still gets). The frame carries `file_epoch: null`. **Final:** no watcher is registered, no tailer starts, no blocks follow | show a static message, keep no buffer, do not retry. The web pane's status line reads **"Session not found"** for `not_found` and "Watch refused" for any other or missing reason |

A **real idle seat** is not refused: its transcript exists, so it resolves and reads `live` even with nothing new to send.

> **`ended` needs a producer, and the tailer's stop rule is not it**. The grace period stops the tailer when the last *watcher* leaves, never when the *seat* leaves. Without a producer, a viewer watching a seat that exits sees a pane that merely stops — indistinguishable from a quiet seat.

**Why a `/clear` is a path swap and not a shrink**. `register_session.py` runs on every SessionStart, and `/clear` fires SessionStart.
The hook rewrites the bridge with the **new** `transcript_path` while **preserving** `stable_session_id`. The old JSONL does not shrink; it simply stops growing while a different file appears elsewhere. So the tailer **re-resolves the bridge on every poll, and a changed `transcript_path` is the primary `/clear` detector**. A tailer watching only for a shrink sits on the dead file forever.
There is no epoch bump and no state frame, and the pane silently freezes at the moment of the clear.
That is the precise failure `file_epoch` exists to prevent. The shrink path stays as the **secondary** detector, for genuine in-place truncation.

### REST companion

`GET /api/cc-transcript/{cc_session_id}` serves the backlog and repairs gaps. It is documented in [`rest-api-reference.md`](../rest-api-reference.md) § "CC Transcript Console".

---
